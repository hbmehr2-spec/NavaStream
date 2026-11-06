import os

import aiohttp
import aiosqlite
from dotenv import load_dotenv

from app.database import DB_PATH


load_dotenv()

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TARGET_CHAT_ID = os.getenv("TELEGRAM_TARGET_CHAT_ID", "").strip()
API_BASE = "https://api.telegram.org"


class TelegramConfigurationError(RuntimeError):
    pass


def _configuration():
    if not BOT_TOKEN:
        raise TelegramConfigurationError(
            "TELEGRAM_BOT_TOKEN is not configured in the local .env file."
        )
    if not TARGET_CHAT_ID:
        raise TelegramConfigurationError(
            "TELEGRAM_TARGET_CHAT_ID is not configured in the local .env file."
        )
    return BOT_TOKEN, TARGET_CHAT_ID


async def _telegram_request(session, method, data=None):
    token, _ = _configuration()
    url = f"{API_BASE}/bot{token}/{method}"

    async with session.post(
        url,
        json=data,
        timeout=aiohttp.ClientTimeout(total=45),
    ) as response:
        payload = await response.json(content_type=None)

    if not payload.get("ok"):
        description = payload.get("description", "Unknown Telegram API error")
        raise RuntimeError(f"Telegram {method} failed: {description}")

    return payload["result"]


async def check_telegram_connection():
    """Verify the bot token and that the bot can access the target channel."""
    _, chat_id = _configuration()

    async with aiohttp.ClientSession() as session:
        bot = await _telegram_request(session, "getMe")
        chat = await _telegram_request(
            session,
            "getChat",
            {"chat_id": chat_id},
        )

    return {
        "bot_username": bot.get("username"),
        "bot_id": bot.get("id"),
        "chat_id": chat.get("id"),
        "chat_title": chat.get("title") or chat.get("username"),
        "chat_type": chat.get("type"),
    }


def _make_caption(track):
    artist = (track.get("artist") or "هنرمند نامشخص").strip()
    title = (track.get("title") or "عنوان نامشخص").strip()
    caption = f"🎵 {artist} — {title}"

    source_url = track.get("source_url")
    if source_url:
        caption += f"\n\nمنبع: {source_url}"

    return caption[:1024]


async def publish_pending_tracks(limit=1):
    """
    Publish only matched tracks with HTTPS audio URLs.
    Successful Telegram message IDs are persisted to prevent duplicates.
    """
    _configuration()

    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            """
            SELECT
                q.id AS queue_id,
                q.track_id,
                t.artist,
                t.title,
                t.source_url,
                t.audio_url
            FROM processing_queue AS q
            JOIN tracks AS t ON t.id = q.track_id
            WHERE q.status = 'pending'
              AND t.validation_status = 'matched'
              AND t.audio_url LIKE 'https://%'
              AND q.telegram_message_id IS NULL
            ORDER BY q.created_at, q.id
            LIMIT ?
            """,
            (max(1, int(limit)),),
        )
        tracks = [dict(row) for row in await cursor.fetchall()]

    if not tracks:
        return {"published": 0, "failed": 0, "message": "No eligible tracks."}

    published = 0
    failed = 0

    async with aiohttp.ClientSession() as session:
        for track in tracks:
            try:
                result = await _telegram_request(
                    session,
                    "sendAudio",
                    {
                        "chat_id": TARGET_CHAT_ID,
                        "audio": track["audio_url"],
                        "caption": _make_caption(track),
                    },
                )

                async with aiosqlite.connect(DB_PATH) as db:
                    await db.execute(
                        """
                        UPDATE processing_queue
                        SET status = 'published',
                            attempts = attempts + 1,
                            telegram_message_id = ?,
                            published_at = CURRENT_TIMESTAMP,
                            last_error = NULL,
                            updated_at = CURRENT_TIMESTAMP
                        WHERE id = ?
                          AND telegram_message_id IS NULL
                        """,
                        (result["message_id"], track["queue_id"]),
                    )
                    await db.commit()

                published += 1
                print(
                    f"Published track {track['track_id']} "
                    f"as Telegram message {result['message_id']}"
                )

            except Exception as error:
                async with aiosqlite.connect(DB_PATH) as db:
                    await db.execute(
                        """
                        UPDATE processing_queue
                        SET attempts = attempts + 1,
                            last_error = ?,
                            updated_at = CURRENT_TIMESTAMP
                        WHERE id = ?
                          AND telegram_message_id IS NULL
                        """,
                        (str(error)[:1000], track["queue_id"]),
                    )
                    await db.commit()

                failed += 1
                print(f"Telegram publish failed for track {track['track_id']}: {error}")

    return {
        "published": published,
        "failed": failed,
        "message": f"Published {published}; failed {failed}.",
    }
