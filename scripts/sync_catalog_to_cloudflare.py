import argparse
import json
import os
import sqlite3
import sys
import urllib.error
import urllib.request

from dotenv import load_dotenv

from app.database import DB_PATH


load_dotenv()

API_URL = os.getenv(
    "NAVASTREAM_API_URL",
    "https://navastream-api.hb-mehr2.workers.dev",
).rstrip("/")
BATCH_SIZE = 50


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
                source_url, external_id, release_date, validation_status
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
            "User-Agent": "NavaStream-Catalog-Sync/1.0",
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

    imported = 0
    for start in range(0, len(tracks), BATCH_SIZE):
        batch = tracks[start:start + BATCH_SIZE]
        result = send_batch(secret, batch)
        imported += result.get("imported", 0)
        print(
            f"Batch {start // BATCH_SIZE + 1}: "
            f"accepted {result.get('imported', 0)}; "
            f"server catalog total: {result.get('catalogTracks', 0)}"
        )

    print(f"Catalog sync completed. Records sent: {imported}.")
    print(f"Check API: {API_URL}/health")


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(f"CATALOG SYNC FAILED: {error}", file=sys.stderr)
        sys.exit(1)
