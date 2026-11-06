import aiohttp
import asyncio
from urllib.parse import urlparse

from bs4 import BeautifulSoup
import aiosqlite

from app.database import DB_PATH
from app.parsers.musics_fa import parse_track_detail, parse_tracks


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


async def get_tracks_needing_review(source_id):
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            """
            SELECT external_id, source_url
            FROM tracks
            WHERE source_id = ?
              AND validation_status != 'matched'
              AND source_url IS NOT NULL
            ORDER BY id
            """,
            (source_id,)
        )
        return await cursor.fetchall()


async def enrich_tracks_from_details(session, source_id, tracks):
    # Include unresolved older records even when they are no longer on
    # the source homepage, so their detail pages can be checked again.
    candidates = {}

    for track in tracks:
        source_url = track.get("source_url")
        if source_url:
            candidates[source_url] = dict(track)

    unresolved = await get_tracks_needing_review(source_id)
    for external_id, source_url in unresolved:
        if source_url and source_url not in candidates:
            candidates[source_url] = {
                "external_id": external_id,
                "source_url": source_url,
            }

    semaphore = asyncio.Semaphore(5)

    async def fetch_and_parse(source_url, fallback):
        async with semaphore:
            detail_html = await fetch_page(session, source_url)

        if detail_html is None:
            return fallback

        detail = parse_track_detail(detail_html, source_url)
        if detail is None:
            return fallback

        merged = dict(fallback)

        # Prefer values read from the detail page, but retain useful
        # listing-page values when a detail field is absent.
        for key in (
            "external_id",
            "artist",
            "title",
            "release_date",
            "source_url",
            "artwork_url",
            "audio_url",
            "fingerprint",
        ):
            if detail.get(key) is not None:
                merged[key] = detail[key]

        merged["validation_status"] = detail["validation_status"]
        merged["validation_note"] = detail["validation_note"]
        return merged

    urls = list(candidates)
    results = await asyncio.gather(
        *(
            fetch_and_parse(url, candidates[url])
            for url in urls
        ),
        return_exceptions=True
    )

    enriched = []
    detail_successes = 0

    for url, result in zip(urls, results):
        if isinstance(result, Exception):
            print(f"Detail parse failed: {url} | {result}")
            fallback = candidates[url]
            # Do not insert skeletal records that came only from the
            # unresolved-record lookup if the detail page could not load.
            if fallback.get("artist") or fallback.get("title"):
                enriched.append(fallback)
            continue

        if (
            result.get("artist")
            or result.get("title")
            or result.get("audio_url")
        ):
            enriched.append(result)
            if result.get("validation_note", "").startswith(
                "Audio filename matches"
            ) or result.get("validation_note", "").startswith(
                "Audio filename does not match"
            ) or result.get("validation_note", "").startswith(
                "Artist/title metadata"
            ):
                detail_successes += 1

    print(
        f"Musics-fa detail pages: checked {len(urls)}, "
        f"parsed {detail_successes}"
    )
    return enriched


async def save_tracks(source_id, tracks):
    inserted = 0
    updated = 0

    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("PRAGMA foreign_keys=ON")

        for track in tracks:
            existing = None

            external_id = track.get("external_id")
            fingerprint = track.get("fingerprint")

            if external_id:
                cursor = await db.execute(
                    """
                    SELECT id, validation_status
                    FROM tracks
                    WHERE source_id = ? AND external_id = ?
                    LIMIT 1
                    """,
                    (source_id, external_id)
                )
                existing = await cursor.fetchone()

            if existing is None and fingerprint:
                cursor = await db.execute(
                    """
                    SELECT id, validation_status
                    FROM tracks
                    WHERE fingerprint = ?
                    LIMIT 1
                    """,
                    (fingerprint,)
                )
                existing = await cursor.fetchone()

            values = (
                track.get("artist"),
                track.get("title") or "Unknown title",
                track.get("release_date"),
                source_id,
                track.get("source_url"),
                track.get("artwork_url"),
                fingerprint,
                external_id,
                track.get("audio_url"),
                track.get("validation_status", "needs_review"),
                track.get("validation_note"),
            )

            if existing:
                # Never let an incomplete crawl downgrade a previously matched record.
                incoming_status = track.get(
                    "validation_status", "needs_review"
                )
                if not (
                    existing[1] == "matched"
                    and incoming_status != "matched"
                ):
                    await db.execute(
                        """
                        UPDATE tracks
                        SET artist = ?,
                            title = ?,
                            release_date = ?,
                            source_id = ?,
                            source_url = ?,
                            artwork_url = ?,
                            fingerprint = ?,
                            external_id = ?,
                            audio_url = ?,
                            validation_status = ?,
                            validation_note = ?
                        WHERE id = ?
                        """,
                        (*values, existing[0])
                    )
                    updated += 1
                track_id = existing[0]
            else:
                cursor = await db.execute(
                    """
                    INSERT INTO tracks (
                        artist, title, release_date, source_id, source_url,
                        artwork_url, fingerprint, external_id, audio_url,
                        validation_status, validation_note, rights_status
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'unknown')
                    """,
                    values
                )
                track_id = cursor.lastrowid
                inserted += 1

            # Preserve any existing queue status, attempts and error history.
            await db.execute(
                """
                INSERT OR IGNORE INTO processing_queue (track_id)
                VALUES (?)
                """,
                (track_id,)
            )

        await db.commit()

    return inserted, updated


async def crawl_source(session, source):
    print(f"Checking: {source['name']}")

    html = await fetch_page(session, source["url"])

    if html is None:
        return None

    hostname = (urlparse(source["url"]).hostname or "").lower()

    if hostname == "musics-fa.com" or hostname.endswith(".musics-fa.com"):
        listing_tracks = parse_tracks(html, source["url"])
        tracks = await enrich_tracks_from_details(
            session,
            source["id"],
            listing_tracks,
        )
        inserted, updated = await save_tracks(source["id"], tracks)

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

        review_count = sum(
            1 for item in tracks
            if item.get("validation_status") != "matched"
        )

        print(
            f"Musics-fa: found {len(listing_tracks)} listing tracks, "
            f"processed {len(tracks)} detail records, "
            f"new {inserted}, updated {updated}, review {review_count}"
        )

        return {
            "source_id": source["id"],
            "source_name": source["name"],
            "tracks_found": len(tracks),
            "tracks_inserted": inserted,
            "tracks_updated": updated,
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

    # Use the site's default response; its custom-UA variant omits artist metadata.
    async with aiohttp.ClientSession(
        connector=connector
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
