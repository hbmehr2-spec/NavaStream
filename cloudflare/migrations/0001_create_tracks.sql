CREATE TABLE IF NOT EXISTS tracks (
    id INTEGER PRIMARY KEY,
    title TEXT NOT NULL,
    artist TEXT,
    audio_url TEXT NOT NULL,
    artwork_url TEXT,
    duration_seconds INTEGER,
    published_at TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    telegram_message_id INTEGER NOT NULL UNIQUE
);

CREATE INDEX IF NOT EXISTS idx_tracks_published
ON tracks(published_at DESC, id DESC);

CREATE INDEX IF NOT EXISTS idx_tracks_title
ON tracks(title);

CREATE INDEX IF NOT EXISTS idx_tracks_artist
ON tracks(artist);
