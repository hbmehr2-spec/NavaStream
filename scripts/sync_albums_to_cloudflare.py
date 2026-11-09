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
API_URL = os.getenv("NAVASTREAM_API_URL", "https://navastream-api.hb-mehr2.workers.dev").rstrip("/")
BATCH_SIZE = 25


def load_albums(limit):
    connection = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True, timeout=15)
    connection.row_factory = sqlite3.Row
    try:
        albums = connection.execute(
            "SELECT id, name, source_url, release_date, artwork_url FROM catalog_albums ORDER BY id LIMIT ?",
            (limit,),
        ).fetchall()
        result = []
        for album in albums:
            artists = connection.execute(
                "SELECT a.source_url FROM catalog_artist_albums aa JOIN catalog_artists a ON a.id = aa.artist_id WHERE aa.album_id = ?",
                (album["id"],),
            ).fetchall()
            result.append({
                "name": album["name"],
                "source_url": album["source_url"],
                "release_date": album["release_date"],
                "artwork_url": album["artwork_url"],
                "artist_source_urls": list(dict.fromkeys(row["source_url"] for row in artists)),
            })
        return result
    finally:
        connection.close()


def send_batch(secret, albums):
    body = json.dumps({"albums": albums}, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    request = urllib.request.Request(
        f"{API_URL}/internal/album-import",
        data=body,
        method="POST",
        headers={
            "Authorization": f"Bearer {secret}",
            "Content-Type": "application/json; charset=utf-8",
            "User-Agent": "NavaStream-Album-Sync/1.0",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=90) as response:
            result = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Album import returned HTTP {error.code}: {detail}") from error
    except urllib.error.URLError as error:
        raise RuntimeError(f"Could not reach NavaStream API: {error.reason}") from error
    if not result.get("ok"):
        raise RuntimeError(f"Server did not confirm album import: {result}")
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=2000)
    args = parser.parse_args()
    if not 1 <= args.limit <= 10000:
        raise ValueError("--limit must be between 1 and 10000")
    secret = os.getenv("NAVASTREAM_INGEST_SECRET", "").strip()
    if len(secret) < 32:
        raise RuntimeError("Set NAVASTREAM_INGEST_SECRET in the environment.")
    if not DB_PATH.exists():
        raise RuntimeError(f"SQLite database not found: {DB_PATH}")
    albums = load_albums(args.limit)
    print(f"Album records ready: {len(albums)}")
    imported = 0
    for start in range(0, len(albums), BATCH_SIZE):
        result = send_batch(secret, albums[start:start + BATCH_SIZE])
        imported += result.get("imported", 0)
        print(f"Batch {start // BATCH_SIZE + 1}: albums={result.get('imported', 0)}")
    print(f"Album sync complete: {imported} albums.")


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(f"ALBUM SYNC FAILED: {error}", file=sys.stderr)
        sys.exit(1)
