import asyncio
import os
import re
import tempfile
import time
import traceback
from io import BytesIO

import aiohttp
import aiosqlite
from dotenv import load_dotenv
from mutagen.id3 import ID3, ID3NoHeaderError, delete as delete_id3
from PIL import Image

from app.database import DB_PATH


load_dotenv()

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TARGET_CHAT_ID = os.getenv("TELEGRAM_TARGET_CHAT_ID", "").strip()
API_BASE = "https://api.telegram.org"
MAX_AUDIO_BYTES = 49 * 1024 * 1024
MAX_ARTWORK_BYTES = 5 * 1024 * 1024
MAX_THUMBNAIL_BYTES = 200 * 1024
MIN_SECONDS_BETWEEN_SENDS = 30.0
MAX_RATE_LIMIT_RETRIES = 5


class TelegramConfigurationError(RuntimeError):
    pass


class TelegramRateLimitError(RuntimeError):
    def __init__(self, message, retry_after):
        super().__init__(message)
        self.retry_after = max(1, int(retry_after or 1))


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


async def _telegram_request(
    session,
    method,
    data=None,
    thumbnail=None,
    audio_file=None,
):
    token, _ = _configuration()
    url = f"{API_BASE}/bot{token}/{method}"

    if thumbnail is not None or audio_file is not None:
        form = aiohttp.FormData()
        for key, value in (data or {}).items():
            form.add_field(key, str(value))
        if audio_file is not None:
            form.add_field(
                "audio",
                audio_file,
                filename="audio.mp3",
                content_type="audio/mpeg",
            )
        if thumbnail is not None:
            form.add_field(
                "thumbnail",
                thumbnail,
                filename="cover.jpg",
                content_type="image/jpeg",
            )
        request_data = form
        request_json = None
    else:
        request_data = None
        request_json = data

    async with session.post(
        url,
        data=request_data,
        json=request_json,
        timeout=aiohttp.ClientTimeout(total=180),
    ) as response:
        payload = await response.json(content_type=None)

    if not payload.get("ok"):
        description = payload.get("description", "Unknown Telegram API error")
        parameters = payload.get("parameters") or {}
        retry_after = parameters.get("retry_after")
        if retry_after:
            raise TelegramRateLimitError(
                f"Telegram {method} rate limited: {description}",
                retry_after,
            )
        raise RuntimeError(f"Telegram {method} failed: {description}")

    return payload["result"]


async def _send_audio_with_retry(
    session,
    data,
    audio_file,
    thumbnail=None,
):
    for attempt in range(MAX_RATE_LIMIT_RETRIES + 1):
        try:
            return await _telegram_request(
                session,
                "sendAudio",
                data,
                thumbnail=thumbnail,
                audio_file=audio_file,
            )
        except TelegramRateLimitError as error:
            if attempt >= MAX_RATE_LIMIT_RETRIES:
                raise
            wait_seconds = error.retry_after + 1
            print(
                f"Telegram rate limit: waiting {wait_seconds}s "
                f"before retry ({attempt + 1}/{MAX_RATE_LIMIT_RETRIES})"
            )
            await asyncio.sleep(wait_seconds)


async def _download_audio(session, audio_url):
    if not audio_url or not audio_url.startswith("https://"):
        raise RuntimeError("Audio URL must use HTTPS.")

    async with session.get(
        audio_url,
        timeout=aiohttp.ClientTimeout(total=180),
    ) as response:
        if response.status != 200:
            raise RuntimeError(
                f"Audio download failed with HTTP {response.status}."
            )

        content_length = response.headers.get("Content-Length")
        if content_length and int(content_length) > MAX_AUDIO_BYTES:
            raise RuntimeError(
                "Audio file exceeds Telegram's 50 MB bot upload limit."
            )

        raw_audio = await response.content.read(MAX_AUDIO_BYTES + 1)

    if not raw_audio:
        raise RuntimeError("Downloaded audio file is empty.")
    if len(raw_audio) > MAX_AUDIO_BYTES:
        raise RuntimeError(
            "Audio file exceeds Telegram's 50 MB bot upload limit."
        )

    return _remove_source_branding_from_mp3(raw_audio)


def _has_source_branding(value):
    text = str(value or "").lower()
    return (
        "music-fa" in text
        or "musics-fa" in text
        or "musicfa" in text
        or "musicsfa" in text
        or "موزیک فا" in text
    )


def _remove_source_branding_from_mp3(raw_audio):
    """Remove ID3 metadata blocks while preserving the MP3 audio stream."""
    if not raw_audio:
        return raw_audio

    audio = raw_audio

    # ID3v2 uses a 10-byte header and a 28-bit synchsafe size.
    # Strip the metadata block by its declared boundary; do not parse its frames.
    if len(audio) >= 10 and audio[:3] == b"ID3":
        size_bytes = audio[6:10]
        if any(value & 0x80 for value in size_bytes):
            raise RuntimeError("Invalid ID3v2 size header; refusing to alter audio.")

        tag_size = (
            ((size_bytes[0] & 0x7F) << 21)
            | ((size_bytes[1] & 0x7F) << 14)
            | ((size_bytes[2] & 0x7F) << 7)
            | (size_bytes[3] & 0x7F)
        )
        tag_end = 10 + tag_size

        # Some files have inconsistent ID3 size fields. Search for the first
        # MPEG audio frame near the declared boundary and require a valid sync.
        if tag_end > len(audio):
            raise RuntimeError(
                f"ID3v2 tag boundary ({tag_end}) exceeds file size ({len(audio)})."
            )

        audio = audio[tag_end:]

    # Remove the optional 128-byte ID3v1 footer.
    if len(audio) >= 128 and audio[-128:-125] == b"TAG":
        audio = audio[:-128]

    if len(audio) < 4 or audio[0] != 0xFF or (audio[1] & 0xE0) != 0xE0:
        raise RuntimeError(
            "MP3 audio frame sync was not found after removing ID3 metadata."
        )

    return audio

async def _download_thumbnail(session, artwork_url):
    if not artwork_url or not artwork_url.startswith("https://"):
        return None

    try:
        async with session.get(
            artwork_url,
            timeout=aiohttp.ClientTimeout(total=20),
        ) as response:
            if response.status != 200:
                return None

            content_length = response.headers.get("Content-Length")
            if content_length and int(content_length) > MAX_ARTWORK_BYTES:
                return None

            raw_image = await response.content.read(MAX_ARTWORK_BYTES + 1)
            if len(raw_image) > MAX_ARTWORK_BYTES:
                return None

        with Image.open(BytesIO(raw_image)) as source:
            image = source.convert("RGB")
            image.thumbnail((320, 320))

            for quality in (88, 80, 72, 64, 56):
                output = BytesIO()
                image.save(
                    output,
                    format="JPEG",
                    quality=quality,
                    optimize=True,
                )
                thumbnail = output.getvalue()
                if len(thumbnail) <= MAX_THUMBNAIL_BYTES:
                    return thumbnail

        return None
    except Exception as error:
        print(f"Artwork thumbnail unavailable: {error!r}")
        return None


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


def _clean_audio_metadata(value, fallback):
    """Remove source-site branding from Telegram's audio title/performer fields."""
    value = (value or "").strip()
    value = re.sub(
        r"(?i)(?:https?://)?(?:www\.)?musics?[-_ ]?fa(?:\.?com)?",
        " ",
        value,
    )
    value = re.sub(r"موزیک\s*فا", " ", value)
    value = re.sub(r"\s+", " ", value)
    value = value.strip(" \t\r\n-–—|،,؛;:：•·")
    return value or fallback


def _make_caption(track):
    artist = _clean_audio_metadata(
        track.get("artist"),
        "هنرمند نامشخص",
    )
    title = _clean_audio_metadata(
        track.get("title"),
        "عنوان نامشخص",
    )
    caption = f"🎵 {artist} — {title}\\n🌐 NavaStreamMusic.com"

    return caption[:1024]


async def publish_pending_tracks(limit=1):
    """
    Publish matched tracks after downloading and cleaning their MP3 metadata.
    Audio is uploaded as a file instead of asking Telegram to fetch the source
    URL, so embedded source-site branding can be removed before publication.
    Successful Telegram message IDs are persisted to prevent duplicates.
    Telegram flood limits are handled using retry_after and a 30-second
    minimum interval between consecutive send attempts.
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
                t.audio_url,
                t.artwork_url
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
    last_send_time = None

    async with aiohttp.ClientSession() as session:
        for track in tracks:
            try:
                audio_file = await _download_audio(
                    session,
                    track["audio_url"],
                )
                thumbnail = await _download_thumbnail(
                    session,
                    track.get("artwork_url"),
                )

                if last_send_time is not None:
                    elapsed = time.monotonic() - last_send_time
                    remaining = MIN_SECONDS_BETWEEN_SENDS - elapsed
                    if remaining > 0:
                        print(
                            f"Waiting {remaining:.1f}s to respect "
                            "the Telegram publishing interval."
                        )
                        await asyncio.sleep(remaining)

                result = await _send_audio_with_retry(
                    session,
                    {
                        "chat_id": TARGET_CHAT_ID,
                        "caption": _make_caption(track),
                        "title": _clean_audio_metadata(
                            track.get("title"),
                            "عنوان نامشخص",
                        )[:64],
                        "performer": _clean_audio_metadata(
                            track.get("artist"),
                            "هنرمند نامشخص",
                        )[:64],
                    },
                    audio_file=audio_file,
                    thumbnail=thumbnail,
                )
                last_send_time = time.monotonic()

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
                last_send_time = time.monotonic()
                error_details = (
                    f"{type(error).__name__}: {error!r}\n"
                    f"{traceback.format_exc()}"
                )
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
                        (error_details[:1000], track["queue_id"]),
                    )
                    await db.commit()

                failed += 1
                print(
                    f"Telegram publish failed for track "
                    f"{track['track_id']}: {error_details}"
                )

    return {
        "published": published,
        "failed": failed,
        "message": f"Published {published}; failed {failed}.",
    }
