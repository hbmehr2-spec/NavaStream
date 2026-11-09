import argparse
import json
import os
import sqlite3
import sys
import urllib.error
import urllib.request
from urllib.parse import urlparse

from dotenv import load_dotenv

from app.database import DB_PATH


load_dotenv()

API_URL = os.getenv(
    "NAVASTREAM_API_URL",
    "https://navastream-api.hb-mehr2.workers.dev",
).rstrip("/")
BATCH_SIZE = 50
TAXONOMY_FIELDS = (
    "source_categories_json",
    "mood_tags_json",
    "genre_tags_json",
    "language_tags_json",
    "region_tags_json",
)


def load_configuration():
    secret = os.getenv("NAVASTREAM_INGEST_SECRET", "").strip()
    if len(secret) < 32:
        raise RuntimeError(
            "Set NAVASTREAM_INGEST_SECRET in the environment or .env file."
        )
    if not DB_PATH.exists():
        raise RuntimeError(f"SQLite database not found: {DB_PATH}")
    return secret


def read_catalog_tracks(limit):
    connection = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True, timeout=15)
    connection.row_factory = sqlite3.Row
    try:
        rows = connection.execute(
            """
            SELECT
                id, title, artist, audio_url, artwork_url,
                source_url, external_id, release_date, validation_status,
                source_categories_json, mood_tags_json, genre_tags_json,
                language_tags_json, region_tags_json, version_type,
                artist_source, artist_confidence
            FROM tracks
            WHERE audio_url LIKE 'https://%'
              AND source_url IS NOT NULL
              AND validation_status != 'excluded'
            ORDER BY id
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [
            {
                "title": row["title"] or "عنوان نامشخص",
                "artist": row["artist"],
                "audio_url": row["audio_url"],
                "artwork_url": row["artwork_url"],
                "source_url": row["source_url"],
                "external_id": row["external_id"],
                "release_date": row["release_date"],
                "validation_status": row["validation_status"] or "needs_review",
                "source_categories_json": row["source_categories_json"] or "[]",
                "mood_tags_json": row["mood_tags_json"] or "[]",
                "genre_tags_json": row["genre_tags_json"] or "[]",
                "language_tags_json": row["language_tags_json"] or "[]",
                "region_tags_json": row["region_tags_json"] or "[]",
                "version_type": row["version_type"],
                "artist_source": row["artist_source"],
                "artist_confidence": row["artist_confidence"],
            }
            for row in rows
        ]
    finally:
        connection.close()


def send_batch(secret, tracks):
    body = json.dumps(
        {"tracks": tracks},
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    request = urllib.request.Request(
        f"{API_URL}/internal/catalog-import",
        data=body,
        method="POST",
        headers={
            "Authorization": f"Bearer {secret}",
            "Content-Type": "application/json; charset=utf-8",
            "User-Agent": "NavaStream-Catalog-Sync/1.1",
            "Accept": "application/json",
        },
    )

    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            result = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        raise RuntimeError(
            f"Catalog import returned HTTP {error.code}: {detail}"
        ) from error
    except urllib.error.URLError as error:
        raise RuntimeError(
            f"Could not reach NavaStream API: {error.reason}"
        ) from error

    if not result.get("ok"):
        raise RuntimeError(f"Cloudflare did not confirm catalog import: {result}")
    return result


def _valid_json_array(value):
    if not isinstance(value, str) or len(value) > 8000:
        return False
    try:
        decoded = json.loads(value)
        return (
            isinstance(decoded, list)
            and len(decoded) <= 100
            and all(isinstance(item, str) and len(item) <= 100 for item in decoded)
        )
    except (TypeError, ValueError):
        return False


def catalog_track_errors(track):
    errors = []

    title = track.get("title")
    if not isinstance(title, str) or not title.strip() or len(title) > 500:
        errors.append("title")

    artist = track.get("artist")
    if artist is not None and (not isinstance(artist, str) or len(artist) > 500):
        errors.append("artist")

    for field in ("audio_url", "source_url"):
        value = track.get(field)
        if not isinstance(value, str) or len(value) > 2048:
            errors.append(field)
            continue
        parsed = urlparse(value)
        if parsed.scheme != "https" or not parsed.netloc:
            errors.append(field)

    artwork = track.get("artwork_url")
    if artwork not in (None, ""):
        if not isinstance(artwork, str) or len(artwork) > 2048:
            errors.append("artwork_url")
        else:
            parsed = urlparse(artwork)
            if parsed.scheme != "https" or not parsed.netloc:
                errors.append("artwork_url")

    external_id = track.get("external_id")
    if external_id is not None and (
        not isinstance(external_id, str) or len(external_id) > 100
    ):
        errors.append("external_id")

    release_date = track.get("release_date")
    if release_date is not None and (
        not isinstance(release_date, str) or len(release_date) > 64
    ):
        errors.append("release_date")

    status = track.get("validation_status") or "needs_review"
    if status not in ("matched", "mismatch", "needs_review", "excluded"):
        errors.append("validation_status")

    for field in TAXONOMY_FIELDS:
        if not _valid_json_array(track.get(field, "[]")):
            errors.append(field)

    for field, max_length in (
        ("version_type", 50),
        ("artist_source", 50),
        ("artist_confidence", 20),
    ):
        value = track.get(field)
        if value is not None and (
            not isinstance(value, str) or len(value) > max_length
        ):
            errors.append(field)

    return errors


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=1000)
    args = parser.parse_args()
    if args.limit < 1 or args.limit > 5000:
        raise ValueError("Limit must be between 1 and 5000.")

    secret = load_configuration()
    tracks = read_catalog_tracks(args.limit)
    print(f"SQLite database: {DB_PATH}")
    print(f"Eligible catalog records: {len(tracks)}")

    if not tracks:
        print("Nothing to transfer.")
        return

    valid_tracks = []
    invalid_count = 0
    for index, track in enumerate(tracks, start=1):
        errors = catalog_track_errors(track)
        if errors:
            invalid_count += 1
            print(
                f"SKIPPED invalid record #{index}: "
                f"fields={','.join(errors)}; source_url={track.get('source_url')}"
            )
        else:
            valid_tracks.append(track)

    print(
        f"Pre-validation: {len(valid_tracks)} valid, "
        f"{invalid_count} invalid records."
    )

    imported = 0
    for start in range(0, len(valid_tracks), BATCH_SIZE):
        batch = valid_tracks[start:start + BATCH_SIZE]
        result = send_batch(secret, batch)
        imported += result.get("imported", 0)
        print(
            f"Batch {start // BATCH_SIZE + 1}: "
            f"accepted {result.get('imported', 0)}; "
            f"server catalog total: {result.get('catalogTracks', 0)}"
        )

    print(
        f"Catalog sync completed. Records sent: {imported}; "
        f"invalid records skipped: {invalid_count}."
    )
    print(f"Check API: {API_URL}/health")


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(f"CATALOG SYNC FAILED: {error}", file=sys.stderr)
        sys.exit(1)
