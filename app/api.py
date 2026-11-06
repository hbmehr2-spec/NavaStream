import os
import sqlite3
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from app.database import DB_PATH


def _database_path() -> Path:
    configured = os.getenv("NAVASTREAM_DB_PATH", "").strip()
    return Path(configured).expanduser() if configured else DB_PATH


def _connect() -> sqlite3.Connection:
    path = _database_path()
    if not path.exists():
        raise HTTPException(status_code=503, detail="Music database is not available.")
    connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=5)
    connection.row_factory = sqlite3.Row
    return connection


def _track_payload(row: sqlite3.Row) -> dict:
    return {
        "id": str(row["id"]),
        "title": row["title"] or "عنوان نامشخص",
        "artist": row["artist"] or "هنرمند نامشخص",
        "audioUrl": row["audio_url"],
        "artworkUrl": row["artwork_url"],
        "durationSeconds": None,
        "publishedAt": row["published_at"],
    }


app = FastAPI(
    title="NavaStream API",
    description="Public read-only music catalogue for the NavaStream Android app.",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET"],
    allow_headers=["*"],
)


@app.get("/health")
def health():
    try:
        with _connect() as db:
            row = db.execute(
                """
                SELECT
                    COUNT(*) AS published_tracks,
                    MAX(q.published_at) AS latest_publication
                FROM processing_queue AS q
                JOIN tracks AS t ON t.id = q.track_id
                WHERE q.status = 'published'
                  AND q.telegram_message_id IS NOT NULL
                  AND t.audio_url LIKE 'https://%'
                """
            ).fetchone()
        return {
            "ok": True,
            "service": "navastream-api",
            "publishedTracks": row["published_tracks"],
            "latestPublication": row["latest_publication"],
        }
    except HTTPException:
        raise
    except sqlite3.Error as error:
        raise HTTPException(status_code=503, detail="Database is temporarily unavailable.") from error


@app.get("/v1/tracks")
def list_tracks(
    q: Optional[str] = Query(default=None, max_length=120),
    limit: int = Query(default=30, ge=1, le=100),
    cursor: Optional[str] = Query(default=None, max_length=20),
):
    try:
        offset = max(0, int(cursor or "0"))
    except ValueError as error:
        raise HTTPException(status_code=400, detail="Invalid cursor.") from error

    filters = [
        "q.status = 'published'",
        "q.telegram_message_id IS NOT NULL",
        "t.audio_url LIKE 'https://%'",
    ]
    params = []

    search = (q or "").strip()
    if search:
        filters.append("(t.title LIKE ? OR t.artist LIKE ?)")
        pattern = f"%{search}%"
        params.extend([pattern, pattern])

    where_clause = " AND ".join(filters)

    try:
        with _connect() as db:
            rows = db.execute(
                f"""
                SELECT
                    t.id,
                    t.title,
                    t.artist,
                    t.audio_url,
                    t.artwork_url,
                    q.published_at
                FROM processing_queue AS q
                JOIN tracks AS t ON t.id = q.track_id
                WHERE {where_clause}
                ORDER BY COALESCE(q.published_at, q.updated_at) DESC, t.id DESC
                LIMIT ? OFFSET ?
                """,
                [*params, limit + 1, offset],
            ).fetchall()
    except HTTPException:
        raise
    except sqlite3.Error as error:
        raise HTTPException(status_code=503, detail="Database is temporarily unavailable.") from error

    has_more = len(rows) > limit
    items = [_track_payload(row) for row in rows[:limit]]
    next_cursor = str(offset + limit) if has_more else None

    return {"items": items, "nextCursor": next_cursor}


@app.get("/v1/tracks/{track_id}")
def get_track(track_id: int):
    try:
        with _connect() as db:
            row = db.execute(
                """
                SELECT
                    t.id,
                    t.title,
                    t.artist,
                    t.audio_url,
                    t.artwork_url,
                    q.published_at
                FROM processing_queue AS q
                JOIN tracks AS t ON t.id = q.track_id
                WHERE t.id = ?
                  AND q.status = 'published'
                  AND q.telegram_message_id IS NOT NULL
                  AND t.audio_url LIKE 'https://%'
                LIMIT 1
                """,
                (track_id,),
            ).fetchone()
    except HTTPException:
        raise
    except sqlite3.Error as error:
        raise HTTPException(status_code=503, detail="Database is temporarily unavailable.") from error

    if row is None:
        raise HTTPException(status_code=404, detail="Track not found.")

    return _track_payload(row)
