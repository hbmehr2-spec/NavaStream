import aiohttp
import asyncio
from bs4 import BeautifulSoup
from app.database import DB_PATH
import aiosqlite


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

    description_tag = soup.find(
        "meta",
        attrs={"name": "description"}
    )

    description = (
        description_tag.get("content", "").strip()
        if description_tag else None
    )

    canonical_tag = soup.find(
        "link",
        rel=lambda value: value and "canonical" in value
    )

    canonical_url = (
        canonical_tag.get("href")
        if canonical_tag else page_url
    )

    return {
        "title": title,
        "description": description,
        "canonical_url": canonical_url
    }


async def crawl_source(session, source):
    print(f"Checking: {source['name']}")

    html = await fetch_page(session, source["url"])

    if html is None:
        return None

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

    connector = aiohttp.TCPConnector(
        limit=5,
        ssl=False
    )

    headers = {"User-Agent": USER_AGENT}

    async with aiohttp.ClientSession(
        connector=connector,
        headers=headers
    ) as session:

        tasks = [
            crawl_source(session, source)
            for source in sources
        ]

        results = await asyncio.gather(
            *tasks,
            return_exceptions=True
        )

    successful = [
        result for result in results
        if isinstance(result, dict)
    ]

    print(f"Crawl completed: {len(successful)}/{len(sources)}")

    return successful

