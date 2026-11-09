CREATE TABLE IF NOT EXISTS catalog_artists (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    source_url TEXT NOT NULL UNIQUE,
    description TEXT,
    artwork_url TEXT,
    last_crawled_at TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS catalog_track_artists (
    artist_id INTEGER NOT NULL,
    track_id INTEGER NOT NULL,
    source_url TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (artist_id, track_id),
    FOREIGN KEY (artist_id) REFERENCES catalog_artists(id) ON DELETE CASCADE,
    FOREIGN KEY (track_id) REFERENCES catalog_tracks(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_catalog_artists_name
ON catalog_artists(name);

CREATE INDEX IF NOT EXISTS idx_catalog_track_artists_track
ON catalog_track_artists(track_id);
