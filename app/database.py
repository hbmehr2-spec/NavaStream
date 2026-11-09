import aiosqlite
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "navastream.db"


async def _ensure_column(db, table, column, definition):
    cursor = await db.execute(f"PRAGMA table_info({table})")
    columns = {row[1] for row in await cursor.fetchall()}
    if column not in columns:
        await db.execute(
            f"ALTER TABLE {table} ADD COLUMN {column} {definition}"
        )


async def init_db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)

    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("PRAGMA journal_mode=WAL")
        await db.execute("PRAGMA foreign_keys=ON")

        await db.executescript("""
        CREATE TABLE IF NOT EXISTS sources (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            url TEXT NOT NULL UNIQUE,
            enabled INTEGER NOT NULL DEFAULT 1,
            last_checked_at TEXT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS tracks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            artist TEXT,
            title TEXT NOT NULL,
            version TEXT,
            release_date TEXT,
            source_id INTEGER,
            source_url TEXT UNIQUE,
            artwork_url TEXT,
            fingerprint TEXT UNIQUE,
            rights_status TEXT NOT NULL DEFAULT 'unknown',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            external_id TEXT,
            audio_url TEXT,
            validation_status TEXT NOT NULL DEFAULT 'needs_review',
            validation_note TEXT,
            FOREIGN KEY (source_id) REFERENCES sources(id)
        );

        CREATE TABLE IF NOT EXISTS processing_queue (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            track_id INTEGER NOT NULL UNIQUE,
            status TEXT NOT NULL DEFAULT 'pending',
            attempts INTEGER NOT NULL DEFAULT 0,
            last_error TEXT,
            next_attempt_at TEXT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (track_id) REFERENCES tracks(id)
        );

        CREATE INDEX IF NOT EXISTS idx_tracks_artist
        ON tracks(artist);

        CREATE INDEX IF NOT EXISTS idx_tracks_created
        ON tracks(created_at);

        CREATE INDEX IF NOT EXISTS idx_queue_status
        ON processing_queue(status);
        """)

        await _ensure_column(db, "tracks", "external_id", "TEXT")
        await _ensure_column(db, "tracks", "audio_url", "TEXT")
        await _ensure_column(
            db, "tracks", "validation_status",
            "TEXT NOT NULL DEFAULT 'needs_review'"
        )
        await _ensure_column(db, "tracks", "validation_note", "TEXT")
        await _ensure_column(db, "tracks", "source_categories_json", "TEXT")
        await _ensure_column(db, "tracks", "mood_tags_json", "TEXT")
        await _ensure_column(db, "tracks", "genre_tags_json", "TEXT")
        await _ensure_column(db, "tracks", "language_tags_json", "TEXT")
        await _ensure_column(db, "tracks", "region_tags_json", "TEXT")
        await _ensure_column(db, "tracks", "version_type", "TEXT")
        await _ensure_column(db, "tracks", "artist_source", "TEXT")
        await _ensure_column(db, "tracks", "artist_confidence", "TEXT")
        await _ensure_column(db, "processing_queue", "telegram_message_id", "INTEGER")
        await _ensure_column(db, "processing_queue", "published_at", "TEXT")

        await db.execute("""
            CREATE INDEX IF NOT EXISTS idx_tracks_external_id
            ON tracks(source_id, external_id)
        """)
        await db.execute(
            """
            INSERT OR IGNORE INTO sources (name, url)
            VALUES (?, ?)
            """,
            ("Musics-fa", "https://musics-fa.com/")
        )
        await db.commit()


async def get_stats():
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("SELECT COUNT(*) FROM sources")
        sources = (await cursor.fetchone())[0]

        cursor = await db.execute("SELECT COUNT(*) FROM tracks")
        tracks = (await cursor.fetchone())[0]

        cursor = await db.execute(
            "SELECT COUNT(*) FROM processing_queue WHERE status = 'pending'"
        )
        pending = (await cursor.fetchone())[0]

        cursor = await db.execute(
            "SELECT COUNT(*) FROM tracks WHERE validation_status = 'needs_review'"
        )
        needs_review = (await cursor.fetchone())[0]

        return {
            "sources": sources,
            "tracks": tracks,
            "pending": pending,
            "needs_review": needs_review,
        }
