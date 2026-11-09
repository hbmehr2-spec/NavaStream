CREATE TABLE IF NOT EXISTS catalog_tracks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    artist TEXT,
    audio_url TEXT NOT NULL,
    artwork_url TEXT,
    source_url TEXT NOT NULL UNIQUE,
    external_id TEXT,
    release_date TEXT,
    validation_status TEXT NOT NULL DEFAULT 'needs_review',
    published_at TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

INSERT OR IGNORE INTO catalog_tracks (
    title, artist, audio_url, artwork_url, source_url,
    validation_status, published_at
)
SELECT
    title,
    artist,
    audio_url,
    artwork_url,
    'legacy:' || id,
    'matched',
    published_at
FROM tracks
WHERE audio_url LIKE 'https://%';

CREATE INDEX IF NOT EXISTS idx_catalog_tracks_created
ON catalog_tracks(created_at DESC, id DESC);

CREATE INDEX IF NOT EXISTS idx_catalog_tracks_title
ON catalog_tracks(title);

CREATE INDEX IF NOT EXISTS idx_catalog_tracks_artist
ON catalog_tracks(artist);
