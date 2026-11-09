import unittest

from app.parsers.musics_fa_archives import (\n    extract_artist_links,\n    extract_artist_links_from_track_page,\n    parse_artist_archive,\n)


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

    def test_excludes_category_archives_and_pagination_links(self):
        html = """
        <a href="/artists/mohsen-chavoshi/">محسن چاوشی</a>
        <a href="/artists/turkish-songs/">ترکی</a>
        <a href="/artists/kurdish-songs/">کردی</a>
        <a href="/artists/ai-music/">هوش مصنوعی</a>
        <a href="/artists/mohsen-chavoshi/page/2/">صفحه بعدی</a>
        """
        artists = extract_artist_links(html, "https://musics-fa.com/")
        self.assertEqual(
            artists,
            [{
                "name": "محسن چاوشی",
                "source_url": "https://musics-fa.com/artists/mohsen-chavoshi/",
            }],
        )

    def test_normalizes_devotional_archive_heading_to_person_name(self):
        html = """
        <html>
          <head><title>دانلود تمام نوحه های محمود کریمی</title></head>
          <body><h1>دانلود تمام نوحه های محمود کریمی</h1></body>
        </html>
        """
        archive = parse_artist_archive(
            html,
            "https://musics-fa.com/artists/mahmoud-karimi/",
        )
        self.assertEqual(archive["name"], "محمود کریمی")

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


    def test_extracts_artist_links_only_from_song_article(self):
        html = """
        <html>
          <body>
            <nav><a href="/artists/navigation-link/">Navigation</a></nav>
            <article class="mf_pst">
              <a href="/artists/artist-one/">Artist One</a>
              <a href="/artists/kurdish-songs/">کردی</a>
              <a href="/category/pop/">Pop</a>
            </article>
            <footer><a href="/artists/footer-link/">Footer</a></footer>
          </body>
        </html>
        """
        artists = extract_artist_links_from_track_page(
            html, "https://musics-fa.com/download-song/123/"
        )
        self.assertEqual(
            artists,
            [{
                "name": "Artist One",
                "source_url": "https://musics-fa.com/artists/artist-one/",
            }],
        )

    def test_track_page_without_song_article_has_no_artist_links(self):
        html = '<a href="/artists/navigation-link/">Navigation</a>'
        self.assertEqual(
            extract_artist_links_from_track_page(
                html, "https://musics-fa.com/download-song/123/"
            ),
            [],
        )


if __name__ == "__main__":
    unittest.main()
