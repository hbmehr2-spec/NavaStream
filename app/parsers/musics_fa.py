import re
from html import unescape
from pathlib import PurePosixPath
from urllib.parse import unquote, urljoin, urlparse

from bs4 import BeautifulSoup


BASE_URL = "https://musics-fa.com"

PERSIAN_TRACK_RE = re.compile(
    r"دانلود\s*(?:آهنگ|اهنگ)\s*(?P<title>.+?)\s+با\s*صدای\s*(?P<artist>.+?)"
    r"(?=(?:\s+به\s+همراه|\s+با\s+کیفیت|\s+دانلود|\s*[♫♪]|[،,.!؟]|$))",
    re.IGNORECASE,
)
ENGLISH_TRACK_RE = re.compile(
    r"BY\s*:\s*(?P<artist>[^|\n]+?)\s*\|\s*(?P<title>[^|\n]+?)"
    r"(?=\s+With\s+(?:Text|Lyrics)\b|\s+And\s+\d+\s+Quality\b|\s+On\s+Music-fa\b|$)",
    re.IGNORECASE,
)
AUDIO_EXTENSIONS = (".mp3", ".m4a", ".flac", ".wav", ".aac", ".ogg")


def _clean(value):
    if not value:
        return None
    value = unescape(str(value))
    value = re.sub(r"<[^>]+>", " ", value)
    value = re.sub(r"\s+", " ", value).strip(" \t\r\n-–—|،,؛;")
    return value or None


def _normalise_filename(value):
    value = unquote(value or "").lower()
    value = re.sub(r"\.(mp3|m4a|flac|wav|aac|ogg)(?:\?.*)?$", "", value)
    value = re.sub(r"[^a-z0-9]+", " ", value)
    return " ".join(value.split())


def _audio_matches(audio_url, english_artist, english_title):
    if not audio_url or not english_artist or not english_title:
        return None

    path = PurePosixPath(urlparse(audio_url).path)
    filename = _normalise_filename(path.name)
    artist = _normalise_filename(english_artist)
    title = _normalise_filename(english_title)

    if not filename or not artist or not title:
        return None

    return artist in filename and title in filename


def _extract_track_identity(article, audio_url):
    paragraphs = [
        _clean(item.get_text(" ", strip=True))
        for item in article.select("p")
    ]

    persian_match = None
    english_match = None

    for paragraph in paragraphs:
        if not paragraph:
            continue
        if persian_match is None:
            persian_match = PERSIAN_TRACK_RE.search(paragraph)
        if english_match is None:
            english_match = ENGLISH_TRACK_RE.search(paragraph)
        if persian_match and english_match:
            break

    artist = _clean(persian_match.group("artist")) if persian_match else None
    title = _clean(persian_match.group("title")) if persian_match else None

    english_artist = _clean(english_match.group("artist")) if english_match else None
    english_title = _clean(english_match.group("title")) if english_match else None

    if not artist:
        artist = english_artist
    if not title:
        title = english_title

    audio_match = _audio_matches(audio_url, english_artist, english_title)

    if audio_match is True:
        validation_status = "matched"
        validation_note = "Audio filename matches the English artist and title metadata."
    elif audio_match is False:
        validation_status = "mismatch"
        validation_note = "Audio filename does not match the English artist and title metadata."
    else:
        validation_status = "needs_review"
        validation_note = "Not enough metadata to verify the audio filename."

    return artist, title, validation_status, validation_note


def parse_tracks(html, page_url=BASE_URL):
    soup = BeautifulSoup(html, "html.parser")
    articles = soup.select("article.mf_pst")
    tracks = []

    for article in articles:
        link = article.select_one("header h2 a")
        if not link:
            continue

        external_id = _clean(article.get("data-id"))
        source_url = urljoin(page_url, link.get("href", ""))
        player = article.select_one("span.play[data-song]")
        audio_url = urljoin(page_url, player.get("data-song", "")) if player else None

        date_tag = article.select_one("header div span")
        release_date = _clean(date_tag.get_text(" ", strip=True)) if date_tag else None

        image = article.select_one("img")
        artwork_url = None
        if image:
            artwork_url = image.get("data-src") or image.get("data-lazy-src") or image.get("src")
            if artwork_url:
                artwork_url = urljoin(page_url, artwork_url)

        artist, title, validation_status, validation_note = _extract_track_identity(
            article,
            audio_url,
        )

        heading = _clean(link.get_text(" ", strip=True))
        if not title:
            title = re.sub(r"^دانلود\s*(?:آهنگ|اهنگ)\s*", "", heading or "", flags=re.IGNORECASE) or heading

        fingerprint = f"musics-fa:{external_id}" if external_id else source_url

        tracks.append({
            "external_id": external_id,
            "artist": artist,
            "title": title,
            "release_date": release_date,
            "source_url": source_url,
            "artwork_url": artwork_url,
            "audio_url": audio_url,
            "fingerprint": fingerprint,
            "validation_status": validation_status,
            "validation_note": validation_note,
        })

    return tracks
