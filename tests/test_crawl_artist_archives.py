import unittest
from unittest.mock import AsyncMock, patch

from scripts import crawl_artist_archives as crawler


class ArtistArchiveVerificationTests(unittest.IsolatedAsyncioTestCase):
    def test_normalizes_source_urls_for_exact_comparison(self):
        self.assertEqual(
            crawler._normalized_source_url(
                "https://Musics-fa.com/download-song/123/?ref=archive#top"
            ),
            "musics-fa.com/download-song/123",
        )
        self.assertEqual(
            crawler._normalized_source_url(
                "https://musics-fa.com/download-song/123/"
            ),
            "musics-fa.com/download-song/123",
        )

    async def test_verifies_exact_song_url_found_in_artist_archive(self):
        candidate = {
            "name": "خواننده",
            "source_url": "https://musics-fa.com/artists/singer/",
            "track_url": "https://musics-fa.com/download-song/123/",
            "expected_artist": "خواننده",
        }
        with (
            patch.object(crawler, "fetch_page", new=AsyncMock(return_value="<html></html>")),
            patch.object(
                crawler,
                "parse_artist_archive",
                return_value={
                    "tracks": [
                        {"source_url": "https://musics-fa.com/download-song/123"}
                    ],
                    "next_pages": [],
                },
            ),
        ):
            results = await crawler.verify_artist_candidates(object(), [candidate])

        self.assertEqual(results[0]["status"], "verified_exact_source_url")
        self.assertEqual(results[0]["archive_pages_checked"], 1)

    async def test_does_not_verify_different_song_url(self):
        candidate = {
            "name": "خواننده",
            "source_url": "https://musics-fa.com/artists/singer/",
            "track_url": "https://musics-fa.com/download-song/123/",
            "expected_artist": "خواننده",
        }
        with (
            patch.object(crawler, "fetch_page", new=AsyncMock(return_value="<html></html>")),
            patch.object(
                crawler,
                "parse_artist_archive",
                return_value={
                    "tracks": [
                        {"source_url": "https://musics-fa.com/download-song/999/"}
                    ],
                    "next_pages": [],
                },
            ),
        ):
            results = await crawler.verify_artist_candidates(object(), [candidate])

        self.assertEqual(results[0]["status"], "not_found_in_checked_archive_pages")

    async def test_reports_fetch_failure_as_inconclusive(self):
        candidate = {
            "name": "خواننده",
            "source_url": "https://musics-fa.com/artists/singer/",
            "track_url": "https://musics-fa.com/download-song/123/",
            "expected_artist": "خواننده",
        }
        with patch.object(
            crawler, "fetch_page", new=AsyncMock(return_value=None)
        ):
            results = await crawler.verify_artist_candidates(object(), [candidate])

        self.assertEqual(results[0]["status"], "inconclusive_fetch_failed")


if __name__ == "__main__":
    unittest.main()
