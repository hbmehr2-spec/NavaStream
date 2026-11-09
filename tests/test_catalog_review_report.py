import sqlite3
import tempfile
import unittest
from pathlib import Path

from scripts.catalog_review_report import (
    fetch_artist_rows,
    fetch_track_rows,
    generate_report,
    fetch_unlinked_track_rows,
    fetch_orphan_artist_rows,
    fetch_orphan_album_rows,
    is_track_review_candidate,
)


class CatalogReviewReportTests(unittest.TestCase):
    def test_track_review_policy_keeps_unverified_origin_for_review(self):
        self.assertTrue(is_track_review_candidate({
            "catalog_scope": "uncertain",
            "artist": "Known Name",
            "artist_confidence": "high",
            "validation_status": "matched",
        }))

    def test_track_review_policy_includes_missing_artist_and_mismatch(self):
        self.assertTrue(is_track_review_candidate({
            "catalog_scope": "foreign",
            "artist": None,
            "artist_confidence": None,
            "validation_status": "matched",
        }))
        self.assertTrue(is_track_review_candidate({
            "catalog_scope": "foreign",
            "artist": "Artist",
            "artist_confidence": "high",
            "validation_status": "mismatch",
        }))

    def test_fetches_only_uncertain_artists_when_scope_exists(self):
        connection = sqlite3.connect(":memory:")
        connection.execute("""
            CREATE TABLE catalog_artists (
                id INTEGER PRIMARY KEY, name TEXT, source_url TEXT,
                catalog_scope TEXT, scope_confidence TEXT, scope_evidence TEXT
            )
        """)
        connection.executemany(
            "INSERT INTO catalog_artists VALUES (?, ?, ?, ?, ?, ?)",
            [
                (1, "Uncertain", "https://example.com/a", "uncertain", "low", "none"),
                (2, "Foreign", "https://example.com/b", "foreign", "high", "curated"),
            ],
        )
        self.assertEqual([row["name"] for row in fetch_artist_rows(connection)], ["Uncertain"])
        connection.close()

    def test_report_is_read_only_and_writes_three_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database = root / "catalog.db"
            output = root / "out"
            connection = sqlite3.connect(database)
            connection.executescript("""
                CREATE TABLE tracks (
                    id INTEGER PRIMARY KEY, title TEXT, artist TEXT,
                    source_url TEXT, audio_url TEXT, validation_status TEXT,
                    artist_confidence TEXT, catalog_scope TEXT
                );
                INSERT INTO tracks VALUES (
                    1, 'Song', NULL, 'https://example.com/song',
                    'https://example.com/song.mp3', 'needs_review', 'low', 'uncertain'
                );
                CREATE TABLE catalog_artists (
                    id INTEGER PRIMARY KEY, name TEXT, source_url TEXT,
                    catalog_scope TEXT
                );
                INSERT INTO catalog_artists VALUES (
                    1, 'Singer', 'https://example.com/singer', 'uncertain'
                );
                CREATE TABLE catalog_track_artists (track_id INTEGER, artist_id INTEGER);
                CREATE TABLE catalog_artist_albums (artist_id INTEGER, album_id INTEGER);
                CREATE TABLE catalog_albums (
                    id INTEGER PRIMARY KEY, name TEXT
                );
                INSERT INTO catalog_albums VALUES (1, 'Album');
            """)
            connection.commit()
            connection.close()

            summary, paths = generate_report(database, output)

            self.assertEqual(len(paths), 6)
            self.assertTrue(all(path.exists() for path in paths))
            self.assertEqual(summary["track_total"], 1)
            self.assertEqual(summary["track_review_candidates"], 1)
            self.assertEqual(summary["artist_review_candidates"], 1)
            self.assertEqual(summary["album_total"], 1)
            self.assertEqual(summary["tracks_without_artist_link"], 1)
            self.assertEqual(summary["artists_without_track_link"], 1)
            self.assertEqual(summary["albums_without_artist_link"], 1)
            check = sqlite3.connect(database)
            self.assertEqual(check.execute("SELECT COUNT(*) FROM tracks").fetchone()[0], 1)
            check.close()


if __name__ == "__main__":
    unittest.main()
