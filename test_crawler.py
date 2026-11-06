import asyncio

from app.database import init_db, get_stats
from app.sources import add_source, delete_source
from app.crawler import crawl_all_sources


async def main():
    await init_db()

    test_url = "https://example.com/"

    print("Adding test source...")

    try:
        source_id = await add_source(
            "NavaStream Test",
            test_url
        )
    except ValueError:
        print("Test source already exists.")
        return

    try:
        print("\nStarting crawler...\n")

        results = await crawl_all_sources()

        print("\nCrawler results:")

        for result in results:
            print(result)

        print("\nDatabase stats:")
        print(await get_stats())

    finally:
        await delete_source(source_id)
        print("\nTest source removed.")


if __name__ == "__main__":
    asyncio.run(main())
