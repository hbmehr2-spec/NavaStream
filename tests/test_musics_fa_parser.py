import unittest

from app.parsers.musics_fa import parse_tracks


class MusicsFaParserTests(unittest.TestCase):
    def test_extracts_persian_metadata_and_matching_audio(self):
        html = """
        <article class="mf_pst" data-id="128456" data-cover="/cover.jpg">
          <header><h2><a href="/download-song/128456/">دانلود آهنگ</a></h2>
            <div><span>15 آبان 1405</span></div>
          </header>
          <p>ما را همراهی کنید با دانلود اهنگ کجا گمت کردم با صدای وحید پورجمشید.
          Download New Music BY : Vahid Pourjamshid | Koja Gomet Kardam</p>
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
          <p>دانلود آهنگ بارون میاد نمه نمه با صدای هویار.
          Download New Music BY : Hooyar | Baroon Miad</p>
          <span class="play" data-song="https://dls.musics-fa.com/Hooyar%20-%20Cheshm%20Asali.mp3"></span>
        </article>
        """

        tracks = parse_tracks(html)

        self.assertEqual(len(tracks), 1)
        self.assertEqual(tracks[0]["validation_status"], "mismatch")


if __name__ == "__main__":
    unittest.main()
