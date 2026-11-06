import json
import os
import sqlite3
import sys
import urllib.error
import urllib.request
from pathlib import Path

from dotenv import load_dotenv

from app.database import DB_PATH


load_dotenv()

API_URL = os.getenv(
    "NAVASTREAM_API_URL",
    "https://navastream-api.hb-mehr2.workers.dev",
).rstrip("/")
BATCH_SIZE = 50


def load_configuration():
    load_dotenv()
    secret = os.getenv("NAVASTREAM_INGEST_SECRET", "").strip()
    if len(secret) < 32:
        raise RuntimeError(
            "Set NAVASTREAM_INGEST_SECRET in your local .env file. "
            "It must be the same secret configured in GitHub Actions."
        )
    if not DB_PATH.exists():
        raise RuntimeError(f"SQLite database not found: {DB_PATH}")
    return secret


def read_published_tracks():
    connection = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True, timeout=10)
    connection.row_factory = sqlite3.Row
    try:
        rows = connection.execute(
            """
            SELECT
                t.id,
                t.title,
                t.artist,
                t.audio_url,
                t.artwork_url,
                q.published_at,
                q.telegram_message_id
            FROM processing_queue AS q
            JOIN tracks AS t ON t.id = q.track_id
            WHERE q.status = 'published'
              AND q.telegram_message_id IS NOT NULL
              AND t.audio_url LIKE 'https://%'
            ORDER BY q.published_at, t.id
            """
        ).fetchall()
        return [
            {
                "id": int(row["id"]),
                "title": row["title"] or "عنوان نامشخص",
                "artist": row["artist"],
                "audio_url": row["audio_url"],
                "artwork_url": row["artwork_url"],
                "duration_seconds": None,
                "published_at": row["published_at"],
                "telegram_message_id": int(row["telegram_message_id"]),
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
        f"{API_URL}/internal/import",
        data=body,
        method="POST",
        headers={
            "Authorization": f"Bearer {secret}",
            "Content-Type": "application/json; charset=utf-8",
        },
    )

    try:
        with urllib.request.urlopen(request, timeout=45) as response:
            result = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        raise RuntimeError(
            f"Cloudflare import returned HTTP {error.code}: {detail}"
        ) from error
    except urllib.error.URLError as error:
        raise RuntimeError(f"Could not reach the NavaStream API: {error.reason}") from error

    if not result.get("ok"):
        raise RuntimeError(f"Cloudflare did not confirm the import: {result}")
    return result


def main():
    secret = load_configuration()
    tracks = read_published_tracks()
    print(f"SQLite database: {DB_PATH}")
    print(f"Eligible published tracks: {len(tracks)}")

    if not tracks:
        print("Nothing to transfer.")
        return

    imported = 0
    for start in range(0, len(tracks), BATCH_SIZE):
        batch = tracks[start : start + BATCH_SIZE]
        result = send_batch(secret, batch)
        imported += result.get("imported", 0)
        print(
            f"Batch {start // BATCH_SIZE + 1}: "
            f"accepted {result.get('imported', 0)}; "
            f"D1 published total: {result.get('publishedTracks', 0)}"
        )

    print(f"Sync completed. Records sent: {imported}.")
    print(f"Check API: {API_URL}/health")


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(f"SYNC FAILED: {error}", file=sys.stderr)
        sys.exit(1)
