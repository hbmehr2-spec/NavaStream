import aiohttp
import asyncio
from urllib.parse import urlparse

from bs4 import BeautifulSoup
import aiosqlite

from app.database import DB_PATH
from app.parsers.musics_fa import parse_tracks


USER_AGENT = (
    "Mozilla/5.0 (Linux; Android 10) "
    "AppleWebKit/537.36 Chrome/120.0 Mobile Safari/537.36"
)


async def get_enabled_sources():
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row

        cursor = await db.execute(
            """
            SELECT id, name, url
            FROM sources
            WHERE enabled = 1
            ORDER BY id
            """
        )

        return [dict(row) for row in await cursor.fetchall()]


async def fetch_page(session, url):
    try:
        async with session.get(
            url,
            timeout=aiohttp.ClientTimeout(total=25),
            allow_redirects=True
        ) as response:
            response.raise_for_status()
            return await response.text(errors="replace")

    except (aiohttp.ClientError, asyncio.TimeoutError) as error:
        print(f"Fetch failed: {url} | {error}")
        return None


def extract_page_info(html, page_url):
    soup = BeautifulSoup(html, "html.parser")

    title = soup.title.get_text(" ", strip=True) if soup.title else None

    description_tag = soup.find(
        "meta",
        attrs={"name": "description"}
    )

    description = (
        description_tag.get("content", "").strip()
        if description_tag else None
    )

    canonical_tag = soup.find(
        "link",
        rel=lambda value: value and "canonical" in value
    )

    canonical_url = (
        canonical_tag.get("href")
        if canonical_tag else page_url
    )

    return {
        "title": title,
        "description": description,
        "canonical_url": canonical_url
    }


async def save_tracks(source_id, tracks):
    inserted = 0

    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("PRAGMA foreign_keys=ON")

        for track in tracks:
            await db.execute(
                """
                INSERT OR IGNORE INTO tracks (
                    artist, title, release_date, source_id, source_url,
                    artwork_url, fingerprint, external_id, audio_url,
                    validation_status, validation_note, rights_status
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'unknown')
                """,
                (
                    track.get("artist"),
                    track.get("title") or "Unknown title",
                    track.get("release_date"),
                    source_id,
                    track.get("source_url"),
                    track.get("artwork_url"),
                    track.get("fingerprint"),
                    track.get("external_id"),
                    track.get("audio_url"),
                    track.get("validation_status", "needs_review"),
                    track.get("validation_note"),
                )
            )

            if db.total_changes:
                inserted += 1

            cursor = await db.execute(
                "SELECT id FROM tracks WHERE fingerprint = ?",
                (track.get("fingerprint"),)
            )
            row = await cursor.fetchone()

            if row:
                await db.execute(
                    """
                    INSERT OR IGNORE INTO processing_queue (track_id)
                    VALUES (?)
                    """,
                    (row[0],)
                )

        await db.commit()

    return inserted


async def crawl_source(session, source):
    print(f"Checking: {source['name']}")

    html = await fetch_page(session, source["url"])

    if html is None:
        return None

    hostname = (urlparse(source["url"]).hostname or "").lower()

    if hostname == "musics-fa.com" or hostname.endswith(".musics-fa.com"):
        tracks = parse_tracks(html, source["url"])
        inserted = await save_tracks(source["id"], tracks)

        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                """
                UPDATE sources
                SET last_checked_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (source["id"],)
            )
            await db.commit()

        print(
            f"Musics-fa: found {len(tracks)} tracks, "
            f"new {inserted}, review {sum(1 for item in tracks if item.get('validation_status') != 'matched')}"
        )

        return {
            "source_id": source["id"],
            "source_name": source["name"],
            "tracks_found": len(tracks),
            "tracks_inserted": inserted,
        }

    page_info = extract_page_info(html, source["url"])

    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            UPDATE sources
            SET last_checked_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (source["id"],)
        )
        await db.commit()

    print(f"Found page: {page_info['title']}")

    return {
        "source_id": source["id"],
        "source_name": source["name"],
        **page_info
    }


async def crawl_all_sources():
    sources = await get_enabled_sources()

    if not sources:
        print("No enabled sources found.")
        return []

    connector = aiohttp.TCPConnector(
        limit=5,
        ssl=False
    )

    headers = {"User-Agent": USER_AGENT}

    async with aiohttp.ClientSession(
        connector=connector,
        headers=headers
    ) as session:

        tasks = [
            crawl_source(session, source)
            for source in sources
        ]

        results = await asyncio.gather(
            *tasks,
            return_exceptions=True
        )

    successful = [
        result for result in results
        if isinstance(result, dict)
    ]

    failures = [
        result for result in results
        if isinstance(result, Exception)
    ]

    for error in failures:
        print(f"Crawl task failed: {error}")

    print(f"Crawl completed: {len(successful)}/{len(sources)}")

    return successful
