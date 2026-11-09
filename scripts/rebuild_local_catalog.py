import argparse
import asyncio
import os
import sys

from app.crawler import crawl_all_sources
from app.database import DB_PATH, init_db
from scripts.crawl_artist_archives import crawl_artist_archives
from scripts.reset_local_catalog import reset_local_catalog


async def rebuild(limit: int, artist_limit: int, page_limit: int) -> None:
    os.environ["NAVASTREAM_CRAWL_LIMIT"] = str(limit)

    backup_result = reset_local_catalog(DB_PATH)
    print(f"Local database backup: {backup_result['backup']}")
    print("Old local catalog and processing queue cleared.")

    # Apply all schema migrations before the crawler writes any tracks.
    await init_db()

    await crawl_all_sources()
    await crawl_artist_archives(limit=artist_limit, page_limit=page_limit)

    print("Fresh local Musics-fa crawl completed.")
    print("Cloudflare was not modified.")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Back up, reset, and rebuild the local NavaStream catalog from Musics-fa."
    )
    parser.add_argument("--limit", type=int, default=5000)
    parser.add_argument("--artist-limit", type=int, default=2000)
    parser.add_argument("--page-limit", type=int, default=100)
    args = parser.parse_args()

    if not 1 <= args.limit <= 5000:
        raise ValueError("--limit must be between 1 and 5000")
    if not 1 <= args.artist_limit <= 2000:
        raise ValueError("--artist-limit must be between 1 and 2000")
    if not 1 <= args.page_limit <= 100:
        raise ValueError("--page-limit must be between 1 and 100")

    asyncio.run(rebuild(args.limit, args.artist_limit, args.page_limit))


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(f"LOCAL CATALOG REBUILD FAILED: {error}", file=sys.stderr)
        sys.exit(1)
