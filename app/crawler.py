import aiohttp
import asyncio
import os
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
    description_tag = soup.find("meta", attrs={"name": "description"})
    description = (
        description_tag.get("content", "").strip()
        if description_tag else None
    )
    canonical_tag = soup.find(
        "link",
        rel=lambda value: value and "canonical" in value
    )
    canonical_url = canonical_tag.get("href") if canonical_tag else page_url
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
        for key in (
            "external_id",
            "artist",
            "title",
            "release_date",
            "source_url",
            "artwork_url",
            "audio_url",
            "fingerprint",
            "source_categories_json",
            "mood_tags_json",
            "genre_tags_json",
            "language_tags_json",
            "region_tags_json",
            "trend_tags_json",
            "version_type",
            "artist_source",
            "artist_confidence",
        ):
            if detail.get(key) is not None:
                merged[key] = detail[key]

        merged["validation_status"] = detail["validation_status"]
        merged["validation_note"] = detail["validation_note"]
        return merged

    urls = list(candidates)
    results = await asyncio.gather(
        *(fetch_and_parse(url, candidates[url]) for url in urls),
        return_exceptions=True
    )

    enriched = []
    detail_successes = 0
    for url, result in zip(urls, results):
        if isinstance(result, Exception):
            print(f"Detail parse failed: {url} | {result}")
            fallback = candidates[url]
            if fallback.get("artist") or fallback.get("title"):
                enriched.append(fallback)
            continue

        if result.get("artist") or result.get("title") or result.get("audio_url"):
            enriched.append(result)
            if result.get("validation_note", "").startswith(
                ("Audio filename matches", "Audio filename does not match",
                 "Artist/title metadata", "Artist is a candidate")
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
                track.get("source_categories_json", "[]"),
                track.get("mood_tags_json", "[]"),
                track.get("genre_tags_json", "[]"),
                track.get("language_tags_json", "[]"),
                track.get("region_tags_json", "[]"),
                track.get("trend_tags_json", "[]"),
                track.get("version_type"),
                track.get("artist_source"),
                track.get("artist_confidence"),
            )

            if existing:
                incoming_status = track.get(
                    "validation_status", "needs_review"
                )
                if not (
                    existing[1] == "matched"
                    and incoming_status not in ("matched", "excluded")
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
                            validation_note = ?,
                            source_categories_json = ?,
                            mood_tags_json = ?,
                            genre_tags_json = ?,
                            language_tags_json = ?,
                            region_tags_json = ?,
                            trend_tags_json = ?,
                            version_type = ?,
                            artist_source = ?,
                            artist_confidence = ?
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
                        validation_status, validation_note,
                        source_categories_json, mood_tags_json, genre_tags_json,
                        language_tags_json, region_tags_json, trend_tags_json,
                        version_type, artist_source, artist_confidence, rights_status
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'unknown')
                    """,
                    values
                )
                track_id = cursor.lastrowid
                inserted += 1

            await db.execute(
                """
                INSERT OR IGNORE INTO processing_queue (track_id)
                VALUES (?)
                """,
                (track_id,)
            )

            if track.get("validation_status") == "excluded":
                await db.execute(
                    """
                    UPDATE processing_queue
                    SET status = "excluded",
                        updated_at = CURRENT_TIMESTAMP
                    WHERE track_id = ?
                      AND status = "pending"
                      AND telegram_message_id IS NULL
                    """,
                    (track_id,),
                )
            elif track.get("validation_status") == "matched":
                await db.execute(
                    """
                    UPDATE processing_queue
                    SET status = "pending",
                        updated_at = CURRENT_TIMESTAMP
                    WHERE track_id = ?
                      AND status = "excluded"
                      AND telegram_message_id IS NULL
                    """,
                    (track_id,),
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
        target_limit = max(1, int(os.getenv("NAVASTREAM_CRAWL_LIMIT", "1000")))
        max_listing_pages = min(100, max(10, (target_limit // 10) + 5))
        listing_tracks = []
        seen_listing_urls = set()

        for page_number in range(1, max_listing_pages + 1):
            if page_number == 1:
                page_url = source["url"]
                page_html = html
            else:
                page_url = f"https://{hostname}/page/{page_number}/"
                page_html = await fetch_page(session, page_url)

            if page_html is None:
                print(f"Musics-fa pagination stopped at page {page_number}: fetch failed")
                break

            page_tracks = parse_tracks(page_html, page_url)
            if not page_tracks:
                print(f"Musics-fa pagination stopped at page {page_number}: no tracks found")
                break

            added_on_page = 0
            for item in page_tracks:
                item_url = item.get("source_url")
                if item_url and item_url not in seen_listing_urls and len(listing_tracks) < target_limit:
                    seen_listing_urls.add(item_url)
                    listing_tracks.append(item)
                    added_on_page += 1

            print(
                f"Musics-fa listing page {page_number}: "
                f"{len(page_tracks)} tracks, {added_on_page} new "
                f"(catalog {len(listing_tracks)}/{target_limit})"
            )

            if len(listing_tracks) >= target_limit:
                print(f"Musics-fa crawl target reached: {target_limit}")
                break
            if added_on_page == 0:
                break

        tracks = await enrich_tracks_from_details(
            session, source["id"], listing_tracks
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

    connector = aiohttp.TCPConnector(limit=5, ssl=False)
    async with aiohttp.ClientSession(connector=connector) as session:
        tasks = [crawl_source(session, source) for source in sources]
        results = await asyncio.gather(*tasks, return_exceptions=True)

    successful = [result for result in results if isinstance(result, dict)]
    failures = [result for result in results if isinstance(result, Exception)]
    for error in failures:
        print(f"Crawl task failed: {error}")

    print(f"Crawl completed: {len(successful)}/{len(sources)}")
    return successful
