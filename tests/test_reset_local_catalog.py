import sqlite3
import tempfile
import unittest
from pathlib import Path

from scripts.reset_local_catalog import reset_local_catalog


class ResetLocalCatalogTests(unittest.TestCase):
    def test_reset_backs_up_and_clears_only_catalog_tables(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "navastream.db"
            connection = sqlite3.connect(database)
            connection.executescript("""
                CREATE TABLE sources (id INTEGER PRIMARY KEY, name TEXT);
                CREATE TABLE tracks (id INTEGER PRIMARY KEY, title TEXT);
                CREATE TABLE processing_queue (id INTEGER PRIMARY KEY, track_id INTEGER);
                CREATE TABLE catalog_artists (id INTEGER PRIMARY KEY, name TEXT);
                CREATE TABLE catalog_albums (id INTEGER PRIMARY KEY, name TEXT);
                CREATE TABLE catalog_track_artists (track_id INTEGER, artist_id INTEGER);
                CREATE TABLE catalog_artist_albums (artist_id INTEGER, album_id INTEGER);
                INSERT INTO sources VALUES (1, 'Musics-fa');
                INSERT INTO tracks VALUES (1, 'Old track');
                INSERT INTO processing_queue VALUES (1, 1);
                INSERT INTO catalog_artists VALUES (1, 'Old artist');
                INSERT INTO catalog_albums VALUES (1, 'Old album');
                INSERT INTO catalog_track_artists VALUES (1, 1);
                INSERT INTO catalog_artist_albums VALUES (1, 1);
            """)
            connection.commit()
            connection.close()

            result = reset_local_catalog(database)
            self.assertTrue(Path(result["backup"]).is_file())

            connection = sqlite3.connect(database)
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM sources").fetchone()[0], 1)
            for table in (
                "tracks", "processing_queue", "catalog_artists", "catalog_albums",
                "catalog_track_artists", "catalog_artist_albums",
            ):
                self.assertEqual(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0], 0)
            connection.close()

            backup = sqlite3.connect(result["backup"])
            self.assertEqual(backup.execute("SELECT COUNT(*) FROM tracks").fetchone()[0], 1)
            self.assertEqual(backup.execute("SELECT COUNT(*) FROM processing_queue").fetchone()[0], 1)
            backup.close()


if __name__ == "__main__":
    unittest.main()
