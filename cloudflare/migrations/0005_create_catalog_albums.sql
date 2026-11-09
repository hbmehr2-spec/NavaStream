CREATE TABLE IF NOT EXISTS catalog_albums (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    source_url TEXT NOT NULL UNIQUE,
    release_date TEXT,
    artwork_url TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS catalog_artist_albums (
    artist_id INTEGER NOT NULL,
    album_id INTEGER NOT NULL,
    source_url TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (artist_id, album_id),
    FOREIGN KEY (artist_id) REFERENCES catalog_artists(id) ON DELETE CASCADE,
    FOREIGN KEY (album_id) REFERENCES catalog_albums(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_catalog_albums_name
ON catalog_albums(name);

CREATE INDEX IF NOT EXISTS idx_catalog_artist_albums_album
ON catalog_artist_albums(album_id);
