from app.database import DB_PATH
import aiosqlite


async def add_source(name: str, url: str):
    name = name.strip()
    url = url.strip()

    if not name or not url:
        raise ValueError("Source name and URL are required.")

    async with aiosqlite.connect(DB_PATH) as db:
        try:
            cursor = await db.execute(
                "INSERT INTO sources (name, url) VALUES (?, ?)",
                (name, url)
            )
            await db.commit()
            return cursor.lastrowid
        except aiosqlite.IntegrityError:
            raise ValueError("This source URL already exists.")


async def list_sources():
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row

        cursor = await db.execute(
            """
            SELECT id, name, url, enabled, last_checked_at, created_at
            FROM sources
            ORDER BY id
            """
        )

        rows = await cursor.fetchall()
        return [dict(row) for row in rows]


async def set_source_enabled(source_id: int, enabled: bool):
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "UPDATE sources SET enabled = ? WHERE id = ?",
            (1 if enabled else 0, source_id)
        )
        await db.commit()
        return cursor.rowcount > 0


async def delete_source(source_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "DELETE FROM sources WHERE id = ?",
            (source_id,)
        )
        await db.commit()
        return cursor.rowcount > 0


async def update_last_checked(source_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            """
            UPDATE sources
            SET last_checked_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (source_id,)
        )
        await db.commit()
        return cursor.rowcount > 0
