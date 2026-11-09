ALTER TABLE catalog_tracks
ADD COLUMN catalog_scope TEXT NOT NULL DEFAULT 'uncertain';

ALTER TABLE catalog_tracks
ADD COLUMN scope_confidence TEXT NOT NULL DEFAULT 'low';

ALTER TABLE catalog_tracks
ADD COLUMN scope_evidence TEXT;

ALTER TABLE catalog_artists
ADD COLUMN catalog_scope TEXT NOT NULL DEFAULT 'uncertain';

ALTER TABLE catalog_artists
ADD COLUMN scope_confidence TEXT NOT NULL DEFAULT 'low';

ALTER TABLE catalog_artists
ADD COLUMN scope_evidence TEXT;
