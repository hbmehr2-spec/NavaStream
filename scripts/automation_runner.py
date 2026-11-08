import asyncio
import os
import sqlite3
import sys

from dotenv import load_dotenv

from app.crawler import crawl_all_sources
from app.database import DB_PATH, init_db
from app.telegram_publisher import publish_pending_tracks
from scripts.sync_to_cloudflare import main as sync_to_cloudflare


CRAWL_INTERVAL_MINUTES = max(
    10,
    int(os.getenv("NAVASTREAM_CRAWL_INTERVAL_MINUTES", "60")),
)


def crawl_is_due():
    if not DB_PATH.exists():
        return True

    with sqlite3.connect(DB_PATH, timeout=10) as db:
        row = db.execute(
            """
            SELECT COUNT(*)
            FROM sources
            WHERE enabled = 1
              AND (
                last_checked_at IS NULL
                OR last_checked_at <= datetime('now', ?)
              )
            """,
            (f"-{CRAWL_INTERVAL_MINUTES} minutes",),
        ).fetchone()

    return bool(row and row[0])


async def run():
    load_dotenv()
    await init_db()

    print(f"Persistent database: {DB_PATH}")
    if crawl_is_due():
        print("Scheduled source crawl is due.")
        results = await crawl_all_sources()
        if not results:
            print("WARNING: crawler returned no successful source results.")
    else:
        print("Source crawl is not due; keeping this run focused on publishing.")

    result = await publish_pending_tracks(limit=1)
    print(
        "Publishing result: "
        f"published={result.get('published', 0)}, "
        f"failed={result.get('failed', 0)}, "
        f"message={result.get('message', '')}"
    )

    # Push successful Telegram message IDs to D1 during the same run.
    # This narrows the duplicate window if the ephemeral runner is interrupted.
    sync_to_cloudflare()

    print("Automation cycle completed.")


if __name__ == "__main__":
    try:
        asyncio.run(run())
    except Exception as error:
        print(
            f"NAVASTREAM AUTOMATION FAILED: {type(error).__name__}: {error}",
            file=sys.stderr,
        )
        raise
