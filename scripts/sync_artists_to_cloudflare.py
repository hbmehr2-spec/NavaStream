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
BATCH_SIZE = 2


def load_data(limit):
    connection = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True, timeout=15)
    connection.row_factory = sqlite3.Row
    try:
        artists = connection.execute(
            "SELECT id, name, source_url, description, artwork_url,
                   catalog_scope, scope_confidence, scope_evidence
            FROM catalog_artists ORDER BY id LIMIT ?",
            (limit,),
        ).fetchall()
        output = []
        for artist in artists:
            links = connection.execute(
                "SELECT t.source_url FROM catalog_track_artists ta JOIN tracks t ON t.id = ta.track_id WHERE ta.artist_id = ? AND t.source_url LIKE 'https://%' ORDER BY t.id",
                (artist["id"],),
            ).fetchall()
            output.append({
                "name": artist["name"],
                "source_url": artist["source_url"],
                "description": artist["description"],
                "artwork_url": artist["artwork_url"],
                "catalog_scope": artist["catalog_scope"] or "uncertain",
                "scope_confidence": artist["scope_confidence"] or "low",
                "scope_evidence": artist["scope_evidence"] or "no_verified_origin_evidence",
                "track_source_urls": list(dict.fromkeys(row["source_url"] for row in links)),
            })
        return output
    finally:
        connection.close()


def send_batch(secret, artists):
    body = json.dumps({"artists": artists}, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    request = urllib.request.Request(
        f"{API_URL}/internal/artist-import",
        data=body,
        method="POST",
        headers={
            "Authorization": f"Bearer {secret}",
            "Content-Type": "application/json; charset=utf-8",
            "User-Agent": "NavaStream-Artist-Sync/1.0",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=90) as response:
            result = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Artist import returned HTTP {error.code}: {detail}") from error
    except urllib.error.URLError as error:
        raise RuntimeError(f"Could not reach NavaStream API: {error.reason}") from error
    if not result.get("ok"):
        raise RuntimeError(f"Server did not confirm artist import: {result}")
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=250)
    args = parser.parse_args()
    if not 1 <= args.limit <= 2000:
        raise ValueError("--limit must be between 1 and 2000")
    secret = os.getenv("NAVASTREAM_INGEST_SECRET", "").strip()
    if len(secret) < 32:
        raise RuntimeError("Set NAVASTREAM_INGEST_SECRET in the environment.")
    if not DB_PATH.exists():
        raise RuntimeError(f"SQLite database not found: {DB_PATH}")
    artists = load_data(args.limit)
    print(f"Artist records ready: {len(artists)}")
    imported = linked = 0
    for start in range(0, len(artists), BATCH_SIZE):
        result = send_batch(secret, artists[start:start + BATCH_SIZE])
        imported += result.get("imported", 0)
        linked += result.get("linkedTracks", 0)
        print(f"Batch {start // BATCH_SIZE + 1}: artists={result.get('imported', 0)}, links={result.get('linkedTracks', 0)}")
    print(f"Artist sync complete: {imported} artists, {linked} track links.")


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(f"ARTIST SYNC FAILED: {error}", file=sys.stderr)
        sys.exit(1)
