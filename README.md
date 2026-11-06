# NavaStream

Automated music discovery, review, and Telegram publishing platform, with a read-only API for the NavaStream Android app.

## Core features

- Discover new music releases from configured sources
- Extract and validate track metadata
- Maintain a persistent processing and publishing queue
- Resume processing after internet interruptions
- Publish matched tracks to the configured Telegram channel
- Record Telegram message IDs to prevent duplicate publication
- Serve published tracks, Persian metadata, and cover-art URLs to the Android app

## Telegram destination

Target channel: https://t.me/NavaStreamMusic

1. Create a bot with [@BotFather](https://t.me/BotFather).
2. Add the bot to the target channel as an administrator.
3. Grant permission to post messages.
4. Copy `.env.example` to `.env` and set the bot token.
5. Keep `.env` local. Never commit or share the real token.

Example local configuration:

```env
TELEGRAM_BOT_TOKEN=your_bot_token
TELEGRAM_TARGET_CHAT_ID=@NavaStreamMusic
```

Only tracks with `validation_status = 'matched'` and an HTTPS audio URL are eligible for publishing. The publisher is not started automatically; verify the connection and publish test tracks manually.

## Read-only music API

The API exposes only tracks successfully published to Telegram. Pending, rejected, and review-needed tracks are never returned.

- `GET /health` — service and published-track count
- `GET /v1/tracks?limit=30&q=<search>&cursor=<offset>` — newest published tracks, optionally searched by Persian title or artist
- `GET /v1/tracks/{id}` — one published track

Example response:

```json
{
  "items": [
    {
      "id": "123",
      "title": "نام آهنگ",
      "artist": "نام خواننده",
      "audioUrl": "https://cdn.example.com/audio/track.mp3",
      "artworkUrl": "https://cdn.example.com/covers/track.jpg",
      "durationSeconds": null,
      "publishedAt": "2026-11-06 12:00:00"
    }
  ],
  "nextCursor": null
}
```

Run locally from the project root:

```bash
pip install -r requirements.txt
uvicorn app.api:app --host 0.0.0.0 --port 8000
```

The API uses the same SQLite database as the crawler and publisher. Set `NAVASTREAM_DB_PATH` if the database is stored elsewhere. It opens the database read-only.

## Container deployment

```bash
docker build -t navastream-api .
docker run --restart unless-stopped -p 8000:8000 \
  -v /absolute/path/to/data:/app/data:ro \
  -e NAVASTREAM_DB_PATH=/app/data/navastream.db \
  navastream-api
```

Put a TLS-enabled reverse proxy in front of port 8000 before exposing the API publicly.

## Android app

The Android app is maintained in the separate private repository:
https://github.com/hbmehr2-spec/NavaStream-Android
