import unittest

from app.parsers.musics_fa_archives import extract_artist_links, parse_artist_archive


class MusicsFaArchiveParserTests(unittest.TestCase):
    def test_extracts_only_artist_archive_links(self):
        html = """
        <a href="/artists/mohsen-chavoshi/">محسن چاوشی</a>
        <a href="/category/happy/">آهنگ شاد</a>
        <a href="https://example.com/artists/foreign/">External</a>
        <a href="/artists/mohsen-chavoshi/">آرشیو محسن چاوشی</a>
        """
        artists = extract_artist_links(html, "https://musics-fa.com/")
        self.assertEqual(len(artists), 1)
        self.assertEqual(artists[0]["name"], "محسن چاوشی")
        self.assertEqual(
            artists[0]["source_url"],
            "https://musics-fa.com/artists/mohsen-chavoshi/",
        )

    def test_parses_artist_identity_and_track_list(self):
        html = """
        <html>
          <head><title>دانلود تمام آهنگهای محسن چاوشی جدید و کامل MP3</title>
          <meta name="description" content="آرشیو کامل آثار محسن چاوشی"></head>
          <body>
            <h1>دانلود تمام آهنگ های محسن چاوشی</h1>
            <article class="mf_pst" data-id="123">
              <header><h2><a href="/download-song/123/">دانلود آهنگ محسن چاوشی رود سوخته</a></h2></header>
              <p>دانلود آهنگ رود سوخته با صدای محسن چاوشی</p>
              <p>Download New Music BY : Mohsen Chavoshi | Roode Sookhte With Text And 2 Quality 320 And 128 On Music-fa</p>
              <span class="play" data-song="https://dls.musics-fa.com/Mohsen%20Chavoshi%20-%20Roode%20Sookhte.mp3"></span>
            </article>
            <a rel="next" href="/artists/mohsen-chavoshi/page/2/">بعدی</a>
          </body>
        </html>
        """
        artist = parse_artist_archive(html, "https://musics-fa.com/artists/mohsen-chavoshi/")
        self.assertEqual(artist["name"], "محسن چاوشی")
        self.assertEqual(artist["description"], "آرشیو کامل آثار محسن چاوشی")
        self.assertEqual(len(artist["tracks"]), 1)
        self.assertEqual(artist["albums"], [])
        self.assertEqual(
            artist["next_pages"],
            ["https://musics-fa.com/artists/mohsen-chavoshi/page/2/"],
        )

    def test_extracts_album_entity_without_misclassifying_it_as_track(self):
        html = """
        <html>
          <head><title>دانلود تمام آهنگهای حمید هیراد</title></head>
          <body>
            <h1>دانلود تمام آهنگ های حمید هیراد</h1>
            <article class="mf_pst" data-id="900">
              <header><h2><a href="/download-song/900/">دانلود آلبوم حمید هیراد ای بی خبر</a></h2>
              <div><span>6 شهریور 1403</span></div></header>
              <p>دانلود آلبوم جدید حمید هیراد ای بی خبر</p>
              <p>Download New Album BY : Hamid Hiraad | Ey Bi Khabar With Text And 2 Quality 320 And 128 On Music-fa</p>
              <span class="play" data-song="https://dls.musics-fa.com/Hamid-Hiraad-Ey-Bi-Khabar.zip"></span>
            </article>
          </body>
        </html>
        """
        artist = parse_artist_archive(html, "https://musics-fa.com/artists/hamid-hiraad/")
        self.assertEqual(len(artist["albums"]), 1)
        self.assertEqual(artist["albums"][0]["name"], "Ey Bi Khabar")
        self.assertEqual(artist["albums"][0]["artist_name"], "Hamid Hiraad")
        self.assertEqual(artist["albums"][0]["release_date"], "6 شهریور 1403")
        self.assertEqual(artist["tracks"], [])


if __name__ == "__main__":
    unittest.main()
