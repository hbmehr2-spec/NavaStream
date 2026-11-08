import re
from difflib import SequenceMatcher
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
PERSIAN_ARCHIVE_ARTIST_RE = re.compile(
    r"آرشیو\s+آهنگ\s+های\s+(?P<artist>.+?)"
    r"(?=\s+آرشیو\s+آهنگ\s+های|\s+کانال\s+رسمی|\s+پخش\s+آنلاین|\s+دانلود\s+آهنگ|$)",
    re.IGNORECASE,
)
PERSIAN_BREADCRUMB_ARTIST_RE = re.compile(
    r"موزیکفا\s*[•|]\s*(?P<artist>[^•|]+?)\s*[•|]",
    re.IGNORECASE,
)
AUDIO_EXTENSIONS = (".mp3", ".m4a", ".flac", ".wav", ".aac", ".ogg")

MADDahi_RE = re.compile(
    r"مداحی|مداح|نوحه(?:خوانی)?|روضه(?:خوانی)?|مرثیه(?:خوانی)?|سینه[\s‌_-]*زنی",
    re.IGNORECASE,
)


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


def _compact(value):
    return re.sub(r"[^a-z0-9]", "", _normalise_filename(value))


def _audio_matches(audio_url, english_artist, english_title):
    if not audio_url or not english_artist or not english_title:
        return None

    path = PurePosixPath(urlparse(audio_url).path)
    filename = _compact(path.name)
    artist = _compact(english_artist)
    title = _compact(english_title)

    if not filename or not artist or not title:
        return None

    # Ignore harmless differences in spaces and punctuation.
    if artist in filename and title in filename:
        return True

    # A close artist transliteration with an exact title is uncertain,
    # not a confirmed match and not a definite mismatch.
    if title in filename:
        artist_from_filename = filename.split(title, 1)[0].strip()
        if artist_from_filename:
            similarity = SequenceMatcher(
                None, artist, artist_from_filename
            ).ratio()
            if similarity >= 0.80:
                return None

    return False


def _extract_archive_artist(paragraphs):
    for paragraph in paragraphs:
        if not paragraph:
            continue

        match = PERSIAN_ARCHIVE_ARTIST_RE.search(paragraph)
        if match:
            artist = _clean(match.group("artist"))
            if artist:
                return artist

    for paragraph in paragraphs:
        if not paragraph:
            continue

        match = PERSIAN_BREADCRUMB_ARTIST_RE.search(paragraph)
        if match:
            artist = _clean(match.group("artist"))
            if artist:
                return artist

    return None


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
        artist = english_artist or _extract_archive_artist(paragraphs)
    if not title:
        title = english_title

    classification_text = " ".join(
        (
            article.get_text(" ", strip=True),
            audio_url or "",
            artist or "",
            title or "",
        )
    ).replace("\u200c", " ")

    if MADDahi_RE.search(classification_text):
        return (
            artist,
            title,
            "excluded",
            "Religious recitation/maddahi content is excluded from publishing.",
        )

    audio_match = _audio_matches(audio_url, english_artist, english_title)

    if audio_match is True:
        validation_status = "matched"
        validation_note = "Audio filename matches the English artist and title metadata."
    elif audio_match is False:
        validation_status = "mismatch"
        validation_note = "Audio filename does not match the English artist and title metadata."
    else:
        validation_status = "needs_review"
        validation_note = "Artist/title metadata is incomplete or has an uncertain transliteration."

    return artist, title, validation_status, validation_note


def _extract_artwork(article, page_url):
    image = article.select_one("img")
    if not image:
        return None

    artwork_url = (
        image.get("data-src")
        or image.get("data-lazy-src")
        or image.get("src")
    )
    return urljoin(page_url, artwork_url) if artwork_url else None


def parse_track_detail(html, page_url):
    """Parse one Musics-fa song detail page."""
    soup = BeautifulSoup(html, "html.parser")
    article = soup.select_one("article.mf_pst")
    if not article:
        return None

    player = article.select_one("span.play[data-song]")
    audio_url = (
        urljoin(page_url, player.get("data-song", ""))
        if player and player.get("data-song")
        else None
    )

    artist, title, validation_status, validation_note = _extract_track_identity(
        article,
        audio_url,
    )

    external_id = _clean(article.get("data-id"))
    if not external_id:
        match = re.search(r"/download-song/(\d+)/?", urlparse(page_url).path)
        external_id = match.group(1) if match else None

    heading_tag = article.select_one("header h1, header h2, h1, h2")
    heading = _clean(heading_tag.get_text(" ", strip=True)) if heading_tag else None
    if not title:
        title = re.sub(
            r"^دانلود\s*(?:آهنگ|اهنگ)\s*",
            "",
            heading or "",
            flags=re.IGNORECASE,
        ) or heading

    date_tag = article.select_one("header div span")
    release_date = (
        _clean(date_tag.get_text(" ", strip=True))
        if date_tag else None
    )

    if not external_id and not audio_url and not artist and not title:
        return None

    return {
        "external_id": external_id,
        "artist": artist,
        "title": title,
        "release_date": release_date,
        "source_url": page_url,
        "artwork_url": _extract_artwork(article, page_url),
        "audio_url": audio_url,
        "fingerprint": f"musics-fa:{external_id}" if external_id else page_url,
        "validation_status": validation_status,
        "validation_note": validation_note,
    }


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
        artwork_url = _extract_artwork(article, page_url)

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
