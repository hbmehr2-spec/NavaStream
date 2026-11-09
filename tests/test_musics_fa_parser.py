import json
import unittest

from app.parsers.musics_fa import classify_catalog_scope, parse_track_detail, parse_tracks


class MusicsFaParserTests(unittest.TestCase):
    def test_extracts_persian_metadata_and_matching_audio(self):
        html = """
        <article class="mf_pst" data-id="128456" data-cover="/cover.jpg">
          <header><h2><a href="/download-song/128456/">دانلود آهنگ</a></h2>
            <div><span>15 آبان 1405</span></div>
          </header>
          <p>ما را همراهی کنید با دانلود اهنگ کجا گمت کردم با صدای وحید پورجمشید.</p>
          <p>Download New Music BY : Vahid Pourjamshid | Koja Gomet Kardam With Text And 2 Quality 320 And 128 On Music-fa</p>
          <img data-src="/cover.jpg">
          <span class="play" data-song="https://dls.musics-fa.com/Vahid%20Pourjamshid%20-%20Koja%20Gomet%20Kardam.mp3"></span>
        </article>
        """

        tracks = parse_tracks(html)

        self.assertEqual(len(tracks), 1)
        self.assertEqual(tracks[0]["artist"], "وحید پورجمشید")
        self.assertEqual(tracks[0]["title"], "کجا گمت کردم")
        self.assertEqual(tracks[0]["external_id"], "128456")
        self.assertEqual(tracks[0]["validation_status"], "matched")
        self.assertTrue(tracks[0]["audio_url"].endswith(".mp3"))

    def test_flags_audio_filename_mismatch(self):
        html = """
        <article class="mf_pst" data-id="123892">
          <header><h2><a href="/download-song/123892/">دانلود آهنگ</a></h2></header>
          <p>دانلود آهنگ بارون میاد نمه نمه با صدای هویار.</p>
          <p>Download Old Music BY : Hooyar | Baroon Miad With Text And 2 Quality 320 And 128 On Music-fa</p>
          <span class="play" data-song="https://dls.musics-fa.com/Hooyar%20-%20Cheshm%20Asali.mp3"></span>
        </article>
        """

        tracks = parse_tracks(html)

        self.assertEqual(len(tracks), 1)
        self.assertEqual(tracks[0]["artist"], "هویار")
        self.assertEqual(tracks[0]["title"], "بارون میاد نمه نمه")
        self.assertEqual(tracks[0]["validation_status"], "mismatch")

    def test_extracts_metadata_from_realistic_separate_paragraphs(self):
        html = """
        <article class="mf_pst" data-id="128453">
          <header><h2><a href="/download-song/128453/">دانلود آهنگ مهرواد بارون ببار</a></h2></header>
          <p>دانلود آهنگ جدید مهرواد بارون ببار</p>
          <p>در این ساعت دانلود اهنگ بارون ببار با صدای مهرواد به همراه تکست و بهترین کیفیت آماده کرده ایم</p>
          <p>Download New Music BY : Mehrvad | Baroon Bebar With Text And 2 Quality 320 And 128 On Music-fa</p>
          <span class="play" data-song="https://dls.musics-fa.com/Mehrvad%20-%20Baroon%20Bebar.mp3"></span>
        </article>
        """

        tracks = parse_tracks(html)

        self.assertEqual(tracks[0]["artist"], "مهرواد")
        self.assertEqual(tracks[0]["title"], "بارون ببار")
        self.assertEqual(tracks[0]["validation_status"], "matched")

    def test_ignores_spaces_and_punctuation_in_artist_filename(self):
        cases = [
            ("Sami Lone", "SamiLone", "Az Man Bekesh Biroon"),
            ("Mehdi Vazife Dan", "Mehdi Vazifedan", "Gorg"),
            ("Jamshid.Jam", "JamshidJam", "Toro Mikham"),
            ("DJ M.O", "DJ MO", "From Silence To Epic"),
        ]

        for index, (artist, filename_artist, title) in enumerate(cases):
            with self.subTest(artist=artist):
                html = f"""
                <article class="mf_pst" data-id="test{index}">
                  <header><h2><a href="/download-song/test{index}/">Track</a></h2></header>
                  <p>Download New Music BY : {artist} | {title} With Text And 2 Quality 320 And 128 On Music-fa</p>
                  <span class="play" data-song="https://example.com/{filename_artist}%20-%20{title.replace(' ', '%20')}.mp3"></span>
                </article>
                """

                tracks = parse_tracks(html)
                self.assertEqual(tracks[0]["validation_status"], "matched")

    def test_parses_song_detail_page_without_listing_link(self):
        html = """
        <article class="mf_pst">
          <header><h1>Download New Music</h1></header>
          <p>Download New Music BY : DJ M.O | From Silence To Epic With Text And 2 Quality 320 And 128 On Music-fa</p>
          <span class="play" data-song="https://dls.musics-fa.com/DJ%20MO%20-%20From%20Silence%20To%20Epic.mp3"></span>
        </article>
        """

        track = parse_track_detail(
            html,
            "https://musics-fa.com/download-song/128388/",
        )

        self.assertIsNotNone(track)
        self.assertEqual(track["external_id"], "128388")
        self.assertEqual(track["artist"], "DJ M.O")
        self.assertEqual(track["title"], "From Silence To Epic")
        self.assertEqual(track["validation_status"], "matched")

    def test_archive_breadcrumb_is_not_misidentified_as_artist(self):
        html = """
        <article class="mf_pst">
          <header><h1>دانلود آهنگ یکی نفسم بود گرفت نفسم ریمیکس</h1></header>
          <p>دانلود آهنگ یکی نفسم بود گرفت نفسم ریمیکس</p>
          <p>Download Old Music BY : Yeki Nafasem Bood With Text And 2 Quality 320 And 128 On Music-fa</p>
          <p>موزیکفا • رضا کرمی تارا • دانلود آهنگ یکی نفسم بود گرفت نفسم ریمیکس</p>
          <p>پخش آنلاین آهنگ دانلود آهنگ با کیفیت 320 آرشیو آهنگ های رضا کرمی تارا</p>
          <span class="play" data-song="https://dls.musics-fa.com/Unknown%20Artist%20-%20Yeki%20Nafasem%20Bood%20Remix.mp3"></span>
        </article>
        """

        track = parse_track_detail(
            html,
            "https://musics-fa.com/download-song/128468/",
        )

        self.assertIsNone(track["artist"])
        self.assertEqual(track["artist_source"], None)
        self.assertEqual(track["validation_status"], "needs_review")

    def test_ai_category_is_version_metadata_not_artist(self):
        html = """
        <article class="mf_pst">
          <header><h1>تو اولین عشق تو آخرین عشق تویی لایق پرستش هوش مصنوعی</h1></header>
          <a href="/category/ai/">هوش مصنوعی</a>
          <span class="play" data-song="https://dls.musics-fa.com/Iliya%20-%20Avalin%20Eshgh%20To%20Akharin%20Eshgh.mp3"></span>
        </article>
        """

        track = parse_track_detail(
            html,
            "https://musics-fa.com/download-song/126593/",
        )

        self.assertEqual(track["artist"], "Iliya")
        self.assertEqual(track["artist_source"], "audio_filename_candidate")
        self.assertEqual(track["artist_confidence"], "low")
        self.assertEqual(track["version_type"], "ai_generated")
        self.assertEqual(json.loads(track["source_categories_json"]), ["هوش مصنوعی"])

    def test_instagram_trend_is_separate_from_genre_and_artist(self):
        html = """
        <article class="mf_pst">
          <header><h1>داره باورم میشه میمونی تا همیشه</h1></header>
          <a href="/category/trend/">ترند اینستاگرام</a>
          <span class="play" data-song="https://dls.musics-fa.com/Kamyar%20-%20Dare%20Bavaram%20Mishe.mp3"></span>
        </article>
        """

        track = parse_track_detail(
            html,
            "https://musics-fa.com/download-song/127745/",
        )

        self.assertEqual(track["artist"], "Kamyar")
        self.assertEqual(json.loads(track["trend_tags_json"]), ["ترند اینستاگرام"])
        self.assertNotIn("ترند شبکه‌های اجتماعی", json.loads(track["genre_tags_json"]))

    def test_region_and_mood_categories_are_stored_separately(self):
        html = """
        <article class="mf_pst">
          <header><h1>آهنگ شاد لری</h1></header>
          <a href="/category/lori/">لری</a>
          <a href="/category/happy/">شاد</a>
          <span class="play" data-song="https://dls.musics-fa.com/Unknown%20Artist%20-%20Song.mp3"></span>
        </article>
        """

        track = parse_track_detail(
            html,
            "https://musics-fa.com/download-song/127820/",
        )

        self.assertEqual(json.loads(track["region_tags_json"]), ["لری"])
        self.assertEqual(json.loads(track["mood_tags_json"]), ["شاد"])
        self.assertIsNone(track["artist"])

    def test_detail_page_keeps_uncertain_transliteration_for_review(self):
        html = """
        <article class="mf_pst">
          <p>Download New Music BY : Janiar | Azize Ghalbam With Text And 2 Quality 320 And 128 On Music-fa</p>
          <span class="play" data-song="https://dls.musics-fa.com/Janyar%20-%20Azize%20Ghalbam.mp3"></span>
        </article>
        """

        track = parse_track_detail(
            html,
            "https://musics-fa.com/download-song/128394/",
        )

        self.assertEqual(track["external_id"], "128394")
        self.assertEqual(track["validation_status"], "needs_review")

    def test_uncertain_artist_transliteration_needs_review(self):
        html = """
        <article class="mf_pst" data-id="128394">
          <header><h2><a href="/download-song/128394/">Track</a></h2></header>
          <p>Download New Music BY : Janiar | Azize Ghalbam With Text And 2 Quality 320 And 128 On Music-fa</p>
          <span class="play" data-song="https://example.com/Janyar%20-%20Azize%20Ghalbam.mp3"></span>
        </article>
        """

        tracks = parse_tracks(html)
        self.assertEqual(tracks[0]["validation_status"], "needs_review")



    def test_known_foreign_artist_requires_exact_curated_match(self):
        self.assertEqual(
            classify_catalog_scope("Glass Animals"),
            {
                "catalog_scope": "foreign",
                "scope_confidence": "high",
                "scope_evidence": "curated_exact_foreign_artist_match",
            },
        )

    def test_unknown_artist_is_not_assumed_to_be_iranian(self):
        result = classify_catalog_scope("یک خواننده ناشناخته")
        self.assertEqual(result["catalog_scope"], "uncertain")
        self.assertEqual(result["scope_confidence"], "low")
        self.assertEqual(result["scope_evidence"], "no_verified_origin_evidence")



    def test_prefers_explicit_persian_artist_over_combined_data_artist(self):
        html = """
        <article class="mf_pst" data-id="129101"
                 data-artist="بچه تو که شده آهن دلت خجسته">
          <header><h1>دانلود آهنگ بچه تو که شده آهن دلت خجسته</h1></header>
          <p>دانلود آهنگ بچه تو که شده آهن دلت</p>
          <p>هم اکنون دانلود اهنگ بچه تو که شده آهن دلت منم خیلی وقته دلم خورده بهت
             با صدای خجسته به همراه تکست و بهترین کیفیت</p>
          <p>Download Old Music BY : Khojaste | Bache With Text And 2 Quality 320 And 128 On Music-fa</p>
          <span class="play" data-song="https://dls.musics-fa.com/Khojaste-Bache.mp3"></span>
        </article>
        """

        track = parse_track_detail(
            html,
            "https://musics-fa.com/download-song/129101/",
        )

        self.assertEqual(track["artist"], "خجسته")
        self.assertEqual(track["title"], "بچه تو که شده آهن دلت")
        self.assertEqual(track["artist_source"], "detail_text")

    def test_uses_english_artist_when_data_artist_contains_artist_and_title(self):
        html = """
        <article class="mf_pst" data-id="129102"
                 data-artist="تونکی تونجل farkında mısın">
          <header><h1>دانلود آهنگ تونکی تونجل farkında mısın</h1></header>
          <p>دانلود آهنگ تونکی تونجل farkında mısın</p>
          <p>Download New Music BY : Tuncay Tuncel | farkında mısın With Text And 2 Quality 320 And 128 On Music-fa</p>
          <span class="play" data-song="https://dls.musics-fa.com/Tuncay-Tuncel-farkinda-misin.mp3"></span>
        </article>
        """

        track = parse_track_detail(
            html,
            "https://musics-fa.com/download-song/129102/",
        )

        self.assertEqual(track["artist"], "Tuncay Tuncel")
        self.assertEqual(track["title"], "farkında mısın")
        self.assertEqual(track["artist_source"], "english_metadata")

    def test_uses_data_artist_and_cleans_fallback_heading(self):
        html = """
        <article class="mf_pst" data-id="129001" data-artist="وحید پورجمشید">
          <header>
            <h1>دانلود آهنگ جدید کجا گمت کردم | پخش آنلاین موزیکفا</h1>
          </header>
          <p>موزیکفا • پخش آنلاین آهنگ با کیفیت 320</p>
          <span class="play" data-song="https://dls.musics-fa.com/Vahid%20Pourjamshid%20-%20Koja%20Gomet%20Kardam.mp3"></span>
        </article>
        """

        track = parse_track_detail(
            html,
            "https://musics-fa.com/download-song/129001/",
        )

        self.assertEqual(track["artist"], "وحید پورجمشید")
        self.assertEqual(track["artist_source"], "detail_text")
        self.assertEqual(track["title"], "کجا گمت کردم")


    def test_generic_gender_label_is_not_saved_as_artist(self):
        html = """
        <article class="mf_pst">
          <header><h1>سلام ای روح خسته من</h1></header>
          <p>دانلود آهنگ سلام ای روح خسته من با صدای مرد</p>
          <span class="play" data-song="https://dls.musics-fa.com/Unknown-Artist-Salam.mp3"></span>
        </article>
        """
        track = parse_track_detail(html, "https://musics-fa.com/download-song/129201/")
        self.assertIsNone(track["artist"])
        self.assertIsNone(track["artist_source"])
        self.assertEqual(track["validation_status"], "needs_review")

    def test_title_words_do_not_create_language_or_region_tags(self):
        html = """
        <article class="mf_pst">
          <header><h1>آهنگ ترکی و کردی برای تو</h1></header>
          <p>دانلود آهنگ ترکی و کردی برای تو</p>
          <span class="play" data-song="https://dls.musics-fa.com/Unknown-Artist-Song.mp3"></span>
        </article>
        """
        track = parse_track_detail(html, "https://musics-fa.com/download-song/129202/")
        self.assertEqual(json.loads(track["language_tags_json"]), [])
        self.assertEqual(json.loads(track["region_tags_json"]), [])

    def test_combined_data_artist_similar_to_title_is_not_trusted(self):
        html = """
        <article class="mf_pst" data-artist="فکر منو نکن دورچی">
          <header><h1>دانلود آهنگ فکر منو نکن</h1></header>
          <p>دانلود آهنگ فکر منو نکن</p>
          <span class="play" data-song="https://dls.musics-fa.com/Unknown-Artist-Track.mp3"></span>
        </article>
        """
        track = parse_track_detail(html, "https://musics-fa.com/download-song/129203/")
        self.assertIsNone(track["artist"])
        self.assertEqual(track["validation_status"], "needs_review")

if __name__ == "__main__":
    unittest.main()
