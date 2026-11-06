# NavaStream

Automated music discovery, review, and Telegram publishing platform.

## Core Features

- Discover new music releases from configured sources
- Extract and validate track metadata
- Maintain a persistent processing and publishing queue
- Resume processing after internet interruptions
- Publish matched tracks to the configured Telegram channel
- Record Telegram message IDs to prevent duplicate publication

## Project Structure

- `app/`: Application source code
- `data/`: Local database and persistent state
- `logs/`: Application logs

## Telegram destination

Target channel: https://t.me/caferavandApp

1. Create a bot with [@BotFather](https://t.me/BotFather).
2. Add the bot to the target channel as an administrator.
3. Grant permission to post messages.
4. Copy `.env.example` to `.env` and set the bot token.
5. Keep `.env` local. Never commit or share the real token.

Example local configuration:

```env
TELEGRAM_BOT_TOKEN=your_bot_token
TELEGRAM_TARGET_CHAT_ID=@caferavandApp
```

The database migration adds Telegram message tracking to `processing_queue`.
Only tracks with `validation_status = 'matched'` and an HTTPS audio URL are eligible.
The publisher is deliberately not started automatically; first verify the connection
and then publish one test track manually.

Verify bot and channel access:

```bash
python -c "import asyncio; from app.telegram_publisher import check_telegram_connection; print(asyncio.run(check_telegram_connection()))"
```

Publish at most one eligible track:

```bash
python -c "import asyncio; from app.telegram_publisher import publish_pending_tracks; print(asyncio.run(publish_pending_tracks(limit=1)))"
```

A successful send stores the Telegram message ID and marks that queue item as
published, preventing the same item from being sent again.
