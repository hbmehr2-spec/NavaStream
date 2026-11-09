import argparse
import asyncio
import json
import os
from urllib.parse import urlparse

import aiohttp
import aiosqlite

from app.crawler import USER_AGENT, fetch_page, save_tracks
from app.database import DB_PATH, init_db
from app.parsers.musics_fa_archives import (
    extract_artist_links,
    extract_artist_links_from_track_page,
    parse_artist_archive,
)


async def ensure_artist_tables():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.executescript("""
        CREATE TABLE IF NOT EXISTS catalog_artists (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            source_url TEXT NOT NULL UNIQUE,
            description TEXT,
            artwork_url TEXT,
            catalog_scope TEXT NOT NULL DEFAULT 'uncertain',
            scope_confidence TEXT NOT NULL DEFAULT 'low',
            scope_evidence TEXT,
            source_name TEXT NOT NULL DEFAULT 'Musics-fa',
            last_crawled_at TEXT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS catalog_track_artists (
            track_id INTEGER NOT NULL,
            artist_id INTEGER NOT NULL,
            source_url TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (track_id, artist_id),
            FOREIGN KEY (track_id) REFERENCES tracks(id) ON DELETE CASCADE,
            FOREIGN KEY (artist_id) REFERENCES catalog_artists(id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS catalog_albums (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            source_url TEXT NOT NULL UNIQUE,
            release_date TEXT,
            artwork_url TEXT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS catalog_artist_albums (
            artist_id INTEGER NOT NULL,
            album_id INTEGER NOT NULL,
            source_url TEXT NOT NULL,
            PRIMARY KEY (artist_id, album_id),
            FOREIGN KEY (artist_id) REFERENCES catalog_artists(id) ON DELETE CASCADE,
            FOREIGN KEY (album_id) REFERENCES catalog_albums(id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_catalog_artists_name
            ON catalog_artists(name);
        CREATE INDEX IF NOT EXISTS idx_catalog_albums_name
            ON catalog_albums(name);
        CREATE INDEX IF NOT EXISTS idx_track_artists_artist
            ON catalog_track_artists(artist_id, track_id);
        """)
        cursor = await db.execute("PRAGMA table_info(catalog_artists)")
        columns = {row[1] for row in await cursor.fetchall()}
        for column, definition in (
            ("catalog_scope", "TEXT NOT NULL DEFAULT 'uncertain'"),
            ("scope_confidence", "TEXT NOT NULL DEFAULT 'low'"),
            ("scope_evidence", "TEXT"),
        ):
            if column not in columns:
                await db.execute(
                    f"ALTER TABLE catalog_artists ADD COLUMN {column} {definition}"
                )
        await db.commit()


async def save_artist_and_links(artist, source_tracks, albums):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            INSERT INTO catalog_artists (
                name, source_url, description, artwork_url,
                catalog_scope, scope_confidence, scope_evidence, last_crawled_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(source_url) DO UPDATE SET
                name = excluded.name,
                description = COALESCE(excluded.description, catalog_artists.description),
                artwork_url = COALESCE(excluded.artwork_url, catalog_artists.artwork_url),
                catalog_scope = excluded.catalog_scope,
                scope_confidence = excluded.scope_confidence,
                scope_evidence = excluded.scope_evidence,
                last_crawled_at = CURRENT_TIMESTAMP
            """,
            (
                artist["name"],
                artist["source_url"],
                artist.get("description"),
                artist.get("artwork_url"),
                artist.get("catalog_scope", "uncertain"),
                artist.get("scope_confidence", "low"),
                artist.get("scope_evidence", "no_verified_origin_evidence"),
            ),
        )
        row = await db.execute(
            "SELECT id FROM catalog_artists WHERE source_url = ?",
            (artist["source_url"],),
        )
        artist_id = (await row.fetchone())[0]

        for track in source_tracks:
            source_url = track.get("source_url")
            if not source_url:
                continue
            cursor = await db.execute(
                "SELECT id FROM tracks WHERE source_url = ? LIMIT 1",
                (source_url,),
            )
            track_row = await cursor.fetchone()
            if track_row:
                await db.execute(
                    """
                    INSERT OR IGNORE INTO catalog_track_artists
                        (track_id, artist_id, source_url)
                    VALUES (?, ?, ?)
                    """,
                    (track_row[0], artist_id, source_url),
                )
        for album in albums:
            await db.execute(
                """
                INSERT INTO catalog_albums (name, source_url, release_date, artwork_url)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(source_url) DO UPDATE SET
                    name = excluded.name,
                    release_date = COALESCE(excluded.release_date, catalog_albums.release_date),
                    artwork_url = COALESCE(excluded.artwork_url, catalog_albums.artwork_url)
                """,
                (album["name"], album["source_url"], album.get("release_date"), album.get("artwork_url")),
            )
            album_row = await db.execute(
                "SELECT id FROM catalog_albums WHERE source_url = ? LIMIT 1",
                (album["source_url"],),
            )
            album_id = (await album_row.fetchone())[0]
            await db.execute(
                """
                INSERT OR IGNORE INTO catalog_artist_albums (artist_id, album_id, source_url)
                VALUES (?, ?, ?)
                """,
                (artist_id, album_id, album["source_url"]),
            )
        await db.commit()



async def discover_artist_links_from_track_pages(session, limit):
    """Find archive links in a small sample of currently unlinked song pages."""
    if limit <= 0:
        return []

    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            """
            SELECT MIN(t.source_url)
            FROM tracks AS t
            WHERE t.source_url IS NOT NULL
              AND TRIM(t.source_url) != ''
              AND t.artist IS NOT NULL
              AND TRIM(t.artist) != ''
              AND NOT EXISTS (
                  SELECT 1
                  FROM catalog_track_artists AS cta
                  WHERE cta.track_id = t.id
              )
            GROUP BY TRIM(t.artist)
            ORDER BY MIN(t.id)
            LIMIT ?
            """,
            (limit,),
        )
        track_urls = [row[0] for row in await cursor.fetchall() if row[0]]

    discovered = {}
    for track_url in track_urls:
        html = await fetch_page(session, track_url)
        if not html:
            continue
        for artist in extract_artist_links_from_track_page(html, track_url):
            discovered.setdefault(artist["source_url"], artist)

    return list(discovered.values())


async def crawl_artist_archives(
    limit=250, page_limit=20, discover_track_pages=0, discover_only=False
):
    await init_db()
    await ensure_artist_tables()
    connector = aiohttp.TCPConnector(limit=5, ssl=False)
    headers = {"User-Agent": USER_AGENT}
    timeout = aiohttp.ClientTimeout(total=30)

    async with aiohttp.ClientSession(
        connector=connector, headers=headers, timeout=timeout
    ) as session:
        homepage = await fetch_page(session, "https://musics-fa.com/")
        if not homepage:
            raise RuntimeError("Could not fetch Musics-fa homepage.")

        homepage_artists = extract_artist_links(homepage, "https://musics-fa.com/")
        discovered = await discover_artist_links_from_track_pages(
            session, discover_track_pages
        )

        # Discovery mode is deliberately isolated from the regular homepage crawl.
        # This keeps a five-page test small and prevents unrelated catalog updates.
        artists = discovered if discover_track_pages else homepage_artists
        print(
            f"Artist archives: {len(homepage_artists)} on homepage; "
            f"{len(discovered)} found in {discover_track_pages} unlinked song page(s)"
        )

        if discover_only:
            for artist in discovered:
                print(f"DISCOVERED: {artist['name']} -> {artist['source_url']}")
            return {"discovered": len(discovered), "archives_crawled": 0}

        artists = artists[:limit]

        totals = {"artists": 0, "albums": 0, "tracks_seen": 0, "tracks_inserted": 0, "tracks_updated": 0}
        for index, artist_link in enumerate(artists, start=1):
            current_url = artist_link["source_url"]
            seen_pages = set()
            collected = {}
            collected_albums = {}
            artist_record = None

            for _ in range(page_limit):
                if current_url in seen_pages:
                    break
                seen_pages.add(current_url)
                html = await fetch_page(session, current_url)
                if not html:
                    break
                parsed = parse_artist_archive(html, current_url)
                if not artist_record:
                    artist_record = parsed
                    if not artist_record.get("name"):
                        artist_record["name"] = artist_link["name"]
                for track in parsed["tracks"]:
                    if track.get("source_url"):
                        collected[track["source_url"]] = track
                for album in parsed.get("albums", []):
                    if album.get("source_url"):
                        collected_albums[album["source_url"]] = album
                next_url = next(
                    (url for url in parsed["next_pages"] if url not in seen_pages),
                    None,
                )
                if not next_url:
                    break
                current_url = next_url

            if not artist_record or not artist_record.get("name"):
                print(f"[{index}/{len(artists)}] skipped: no artist identity: {artist_link['source_url']}")
                continue

            artist_record["source_url"] = artist_link["source_url"]
            track_list = list(collected.values())
            if track_list:
                source_id = await _get_musics_fa_source_id()
                inserted, updated = await save_tracks(source_id, track_list, enqueue=False)
                totals["tracks_seen"] += len(track_list)
                totals["tracks_inserted"] += inserted
                totals["tracks_updated"] += updated
            album_list = list(collected_albums.values())
            await save_artist_and_links(artist_record, track_list, album_list)
            totals["artists"] += 1
            totals["albums"] += len(album_list)
            print(
                f"[{index}/{len(artists)}] {artist_record['name']}: "
                f"{len(track_list)} tracks, {len(album_list)} albums across {len(seen_pages)} page(s)"
            )

        print("Artist archive crawl summary:", json.dumps(totals, ensure_ascii=False))
        return totals


async def _get_musics_fa_source_id():
    async with aiosqlite.connect(DB_PATH) as db:
        row = await db.execute(
            "SELECT id FROM sources WHERE url = ? LIMIT 1",
            ("https://musics-fa.com/",),
        )
        result = await row.fetchone()
        if not result:
            cursor = await db.execute(
                "INSERT INTO sources (name, url) VALUES (?, ?)",
                ("Musics-fa", "https://musics-fa.com/"),
            )
            await db.commit()
            return cursor.lastrowid
        return result[0]


def main():
    parser = argparse.ArgumentParser(description="Crawl Musics-fa artist archives.")
    parser.add_argument("--limit", type=int, default=int(os.getenv("NAVASTREAM_ARTIST_LIMIT", "250")))
    parser.add_argument("--page-limit", type=int, default=int(os.getenv("NAVASTREAM_ARTIST_PAGE_LIMIT", "20")))
    parser.add_argument(
        "--discover-track-pages",
        type=int,
        default=0,
        help="Inspect this many distinct unlinked song pages for artist archive links.",
    )
    parser.add_argument(
        "--discover-only",
        action="store_true",
        help="Print discovered archive links without crawling or saving them.",
    )
    args = parser.parse_args()
    if not 1 <= args.limit <= 2000:
        raise ValueError("--limit must be between 1 and 2000")
    if not 1 <= args.page_limit <= 100:
        raise ValueError("--page-limit must be between 1 and 100")
    if not 0 <= args.discover_track_pages <= 5000:
        raise ValueError("--discover-track-pages must be between 0 and 5000")
    asyncio.run(
        crawl_artist_archives(
            args.limit,
            args.page_limit,
            args.discover_track_pages,
            args.discover_only,
        )
    )


if __name__ == "__main__":
    main()
