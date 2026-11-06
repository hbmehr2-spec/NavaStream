import asyncio
from app.database import init_db, get_stats


async def main():
    print("Starting NavaStream...")

    await init_db()
    stats = await get_stats()

    print("Database initialized successfully.")
    print(f"Sources: {stats['sources']}")
    print(f"Tracks: {stats['tracks']}")
    print(f"Pending review jobs: {stats['pending']}")
    print(f"Tracks needing metadata review: {stats['needs_review']}")
    print("NavaStream is ready.")


if __name__ == "__main__":
    asyncio.run(main())
