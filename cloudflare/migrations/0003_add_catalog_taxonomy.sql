ALTER TABLE catalog_tracks ADD COLUMN source_categories_json TEXT;
ALTER TABLE catalog_tracks ADD COLUMN mood_tags_json TEXT;
ALTER TABLE catalog_tracks ADD COLUMN genre_tags_json TEXT;
ALTER TABLE catalog_tracks ADD COLUMN language_tags_json TEXT;
ALTER TABLE catalog_tracks ADD COLUMN region_tags_json TEXT;
ALTER TABLE catalog_tracks ADD COLUMN trend_tags_json TEXT;
ALTER TABLE catalog_tracks ADD COLUMN version_type TEXT;
ALTER TABLE catalog_tracks ADD COLUMN artist_source TEXT;
ALTER TABLE catalog_tracks ADD COLUMN artist_confidence TEXT;

CREATE INDEX IF NOT EXISTS idx_catalog_tracks_version_type
ON catalog_tracks(version_type);
