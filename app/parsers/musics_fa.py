import json
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
AUDIO_EXTENSIONS = (".mp3", ".m4a", ".flac", ".wav", ".aac", ".ogg")


PAGE_NOISE_RE = re.compile(
    r"موزیک\s*فا|music[- ]?fa|پخش\s+آنلاین|دانلود\s+(?:آهنگ|اهنگ)|"
    r"آرشیو\s+آهنگ(?:\s+های)?|با\s+کیفیت|بهترین\s+کیفیت|"
    r"تکست\s+و\s+ترجمه|متن\s+آهنگ",
    re.IGNORECASE,
)
IDENTITY_CUTOFF_RE = re.compile(
    r"\s*(?:به\s+همراه|همراه\s+با|با\s+کیفیت|پخش\s+آنلاین|"
    r"دانلود\s+(?:آهنگ|اهنگ)|موزیک\s*فا|music[- ]?fa|"
    r"آرشیو\s+آهنگ).*?$",
    re.IGNORECASE,
)


def _clean_identity_field(value, max_length=160):
    value = _clean(value)
    if not value:
        return None

    value = re.sub(r"^دانلود\s*(?:آهنگ|اهنگ)\s*(?:جدید\s*)?", "", value, flags=re.IGNORECASE)
    value = IDENTITY_CUTOFF_RE.sub("", value)
    value = re.sub(r"\s+", " ", value).strip(" \t\r\n-–—|،,؛;:.!؟")
    if not value or len(value) > max_length or PAGE_NOISE_RE.search(value):
        return None
    if re.fullmatch(r"(?:آهنگ|اهنگ|موزیک|دانلود|جدید|new music|download new music)", value, re.IGNORECASE):
        return None
    return value or None


def _fallback_heading_title(heading):
    value = _clean_identity_field(heading, max_length=180)
    if not value:
        return None
    value = re.sub(r"^(?:آهنگ|اهنگ|موزیک)\s+", "", value, flags=re.IGNORECASE).strip()
    return value or None

MADDAHI_RE = re.compile(
    r"مداحی|مداح|نوحه(?:خوانی)?|روضه(?:خوانی)?|مرثیه(?:خوانی)?|سینه[\s‌_-]*زنی",
    re.IGNORECASE,
)

GENERIC_ARTISTS = {
    "unknown artist",
    "unknwon artist",
    "unknown",
    "different artist",
    "ai",
    "a i",
    "ai nagh me",
    "ai nagh me",
    "هوش مصنوعی",
    "ترند اینستاگرام",
}

CATEGORY_RULES = {
    "mood": {
        "شاد": "شاد",
        "غمگین": "غمگین",
        "عاشقانه": "عاشقانه",
        "احساسی": "احساسی",
        "آرامش": "آرامش‌بخش",
        "آرامش‌بخش": "آرامش‌بخش",
        "دلتنگی": "دلتنگی",
        "انرژی": "انرژی‌بخش",
        "رقص": "رقص",
        "پارتی": "مهمانی",
        "مهمانی": "مهمانی",
        "لالایی": "لالایی",
        "تولد": "مناسبت",
    },
    "genre": {
        "پاپ": "پاپ",
        "رپ": "رپ",
        "هیپ هاپ": "هیپ‌هاپ",
        "هیپ‌هاپ": "هیپ‌هاپ",
        "راک": "راک",
        "سنتی": "سنتی",
        "کلاسیک": "کلاسیک",
        "فولکلور": "فولکلور",
        "محلی": "محلی",
        "تلفیقی": "تلفیقی",
        "الکترونیک": "الکترونیک",
        "ریمیکس": "ریمیکس",
        "بی کلام": "بی‌کلام",
        "بی‌کلام": "بی‌کلام",
    },
    "region": {
        "بندری": "بندری",
        "لری": "لری",
        "لکی": "لکی",
        "کردی": "کردی",
        "کرمانجی": "کرمانجی",
        "ترکی": "ترکی",
        "آذری": "آذری",
        "مازندرانی": "مازندرانی",
        "شمالی": "شمالی",
        "گیلکی": "گیلکی",
        "خراسانی": "خراسانی",
        "بلوچی": "بلوچی",
        "افغانی": "افغانستان",
        "افغان": "افغانستان",
        "عربی": "عربی",
    },
    "language": {
        "فارسی": "فارسی",
        "پارسی": "فارسی",
        "ترکی": "ترکی",
        "آذری": "ترکی",
        "کردی": "کردی",
        "عربی": "عربی",
        "لری": "لری",
        "گیلکی": "گیلکی",
        "مازندرانی": "مازندرانی",
        "بلوچی": "بلوچی",
        "انگلیسی": "انگلیسی",
        "اسپانیایی": "اسپانیایی",
        "هندی": "هندی",
        "کره‌ای": "کره‌ای",
        "روسی": "روسی",
    },
}


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


def _normalise_fa(value):
    value = _clean(value) or ""
    value = value.replace("ي", "ی").replace("ك", "ک")
    value = value.replace("\u200c", " ")
    return re.sub(r"\s+", " ", value).strip().lower()



KNOWN_FOREIGN_ARTISTS = {
    "bts",
    "glass animals",
    "bring me the horizon",
    "empire of the sun",
    "hugel",
    "solto",
    "flo rida",
    "sia",
    "imagine dragons",
    "cansever",
    "mustafa sandal",
    "burak bulut",
    "serdar ortac",
    "ahmed kaya",
}


def classify_catalog_scope(artist):
    """Only label exact, curated foreign-artist matches; never infer Iranian origin."""
    normalized = _normalise_filename(artist or "")
    if normalized in KNOWN_FOREIGN_ARTISTS:
        return {
            "catalog_scope": "foreign",
            "scope_confidence": "high",
            "scope_evidence": "curated_exact_foreign_artist_match",
        }
    return {
        "catalog_scope": "uncertain",
        "scope_confidence": "low",
        "scope_evidence": "no_verified_origin_evidence",
    }


def _is_generic_artist(value):
    if not value:
        return True
    normalized = _normalise_fa(value)
    compact = re.sub(r"[^a-z0-9آ-ی]", "", normalized)
    if normalized in GENERIC_ARTISTS:
        return True
    if compact in {"هوشمصنوعی", "ترنداینستاگرام", "unknownartist", "unknwonartist"}:
        return True
    if re.fullmatch(r"ai(?:\s+naghme?)?", normalized, re.IGNORECASE):
        return True
    return False


def _audio_matches(audio_url, english_artist, english_title):
    if not audio_url or not english_artist or not english_title:
        return None

    path = PurePosixPath(urlparse(audio_url).path)
    filename = _compact(path.name)
    artist = _compact(english_artist)
    title = _compact(english_title)

    if not filename or not artist or not title:
        return None

    if artist in filename and title in filename:
        return True

    if title in filename:
        artist_from_filename = filename.split(title, 1)[0].strip()
        if artist_from_filename:
            similarity = SequenceMatcher(None, artist, artist_from_filename).ratio()
            if similarity >= 0.80:
                return None

    return False


def _filename_artist_candidate(audio_url):
    if not audio_url:
        return None
    filename = unquote(PurePosixPath(urlparse(audio_url).path).name)
    filename = re.sub(
        r"\.(mp3|m4a|flac|wav|aac|ogg)$", "", filename, flags=re.IGNORECASE
    )
    filename = re.sub(r"\s*\([^)]*\)\s*$", "", filename)
    filename = re.sub(r"\s+Musics[- ]?Fa.*$", "", filename, flags=re.IGNORECASE)
    if " - " not in filename:
        return None
    candidate = _clean(filename.split(" - ", 1)[0])
    if not candidate or _is_generic_artist(candidate):
        return None
    if len(candidate) > 100 or re.search(r"https?://", candidate, re.IGNORECASE):
        return None
    return candidate


def _extract_source_categories(article):
    categories = []
    seen = set()
    for link in article.select("a[href]"):
        label = _clean(link.get_text(" ", strip=True))
        href = (link.get("href") or "").lower()
        if not label:
            continue
        is_taxonomy_link = any(
            marker in href
            for marker in ("/category/", "/tag/", "/genre/", "/music-category/")
        )
        known_label = any(
            _normalise_fa(label) == _normalise_fa(term)
            for group in CATEGORY_RULES.values()
            for term in group
        ) or _normalise_fa(label) in {
            "هوش مصنوعی", "ترند اینستاگرام", "مداحی", "ترند اینستا"
        }
        if not (is_taxonomy_link or known_label):
            continue
        key = _normalise_fa(label)
        if key and key not in seen:
            seen.add(key)
            categories.append(label)
    return categories


def _classify_categories(article, title, audio_url, artist):
    source_categories = _extract_source_categories(article)
    evidence_text = " ".join([title or "", *source_categories])
    normalized = _normalise_fa(evidence_text)
    mood_tags = set()
    genre_tags = set()
    language_tags = set()
    region_tags = set()
    trend_tags = set()

    for group_name, rules in CATEGORY_RULES.items():
        for term, tag in rules.items():
            if _normalise_fa(term) in normalized:
                if group_name == "mood":
                    mood_tags.add(tag)
                elif group_name == "genre":
                    genre_tags.add(tag)
                elif group_name == "language":
                    language_tags.add(tag)
                elif group_name == "region":
                    region_tags.add(tag)

    source_text = " ".join(source_categories)
    if any(
        _normalise_fa(item) in {"ترند اینستاگرام", "ترند اینستا"}
        for item in source_categories
    ):
        trend_tags.add("ترند اینستاگرام")

    version_type = None
    if re.search(r"هوش\s*مصنوعی|(?<![a-z])ai(?![a-z])|ai\s+naghme", source_text + " " + (title or "") + " " + (audio_url or ""), re.IGNORECASE):
        version_type = "ai_generated"
    elif re.search(r"ریمیکس|remix", normalized, re.IGNORECASE):
        version_type = "remix"
    elif re.search(r"اجرای\s*زنده|\blive\b", normalized, re.IGNORECASE):
        version_type = "live"
    elif re.search(r"بی\s*کلام|instrumental", normalized, re.IGNORECASE):
        version_type = "instrumental"
    elif re.search(r"کاور|cover", normalized, re.IGNORECASE):
        version_type = "cover"

    return {
        "source_categories": source_categories,
        "mood_tags": sorted(mood_tags),
        "genre_tags": sorted(genre_tags),
        "language_tags": sorted(language_tags),
        "region_tags": sorted(region_tags),
        "trend_tags": sorted(trend_tags),
        "version_type": version_type,
    }


def _extract_track_identity(article, audio_url):
    paragraphs = [
        _clean(item.get_text(" ", strip=True))
        for item in article.select("p")
    ]

    persian_match = None
    english_match = None
    lead_title = None

    for paragraph in paragraphs:
        if not paragraph:
            continue
        if lead_title is None and re.match(
            r"^دانلود\\s*(?:آهنگ|اهنگ)\\s*", paragraph, re.IGNORECASE
        ):
            candidate = _clean_identity_field(
                re.sub(
                    r"^دانلود\\s*(?:آهنگ|اهنگ)\\s*(?:جدید\\s*)?",
                    "",
                    paragraph,
                    flags=re.IGNORECASE,
                )
            )
            if candidate:
                lead_title = candidate
        if persian_match is None:
            persian_match = PERSIAN_TRACK_RE.search(paragraph)
        if english_match is None:
            english_match = ENGLISH_TRACK_RE.search(paragraph)
        if persian_match and english_match and lead_title:
            break

    explicit_artist = (
        _clean_identity_field(persian_match.group("artist")) if persian_match else None
    )
    persian_match_title = (
        _clean_identity_field(persian_match.group("title")) if persian_match else None
    )
    english_artist = _clean_identity_field(english_match.group("artist")) if english_match else None
    english_title = _clean_identity_field(english_match.group("title")) if english_match else None
    data_artist = _clean_identity_field(article.get("data-artist"), max_length=120)

    if lead_title and explicit_artist:
        lead_title = re.sub(
            rf"^{re.escape(explicit_artist)}\\s+|\\s+{re.escape(explicit_artist)}$",
            "",
            lead_title,
            flags=re.IGNORECASE,
        ).strip(" \\t-–—|،,؛;:.!؟") or None

    if lead_title and english_title:
        if _normalise_filename(english_title) in _normalise_filename(lead_title):
            title = english_title
        else:
            title = lead_title
    else:
        title = lead_title or persian_match_title or english_title

    data_artist_is_ambiguous = bool(
        data_artist
        and lead_title
        and _normalise_fa(data_artist) == _normalise_fa(lead_title)
    )
    artist = explicit_artist or english_artist or (
        data_artist if not data_artist_is_ambiguous else None
    )
    artist_source = (
        "detail_text" if explicit_artist else
        "english_metadata" if english_artist else
        "detail_text" if artist else None
    )
    artist_confidence = "high" if artist and not _is_generic_artist(artist) else None

    if _is_generic_artist(artist):
        artist = None
        artist_source = None
        artist_confidence = None

    if not artist:
        candidate = _filename_artist_candidate(audio_url)
        if candidate:
            artist = candidate
            artist_source = "audio_filename_candidate"
            artist_confidence = "low"

    scope = classify_catalog_scope(artist)
    classification = _classify_categories(article, title, audio_url, artist)
    classification_text = " ".join(
        (
            article.get_text(" ", strip=True),
            audio_url or "",
            artist or "",
            title or "",
            " ".join(classification["source_categories"]),
        )
    ).replace("\u200c", " ")

    if MADDAHI_RE.search(classification_text):
        return {
            "artist": artist,
            "title": title,
            "validation_status": "excluded",
            "validation_note": "Religious recitation/maddahi content is excluded from the music catalog.",
            "artist_source": artist_source,
            "artist_confidence": artist_confidence,
            **scope,
            **classification,
        }

    audio_match = _audio_matches(audio_url, english_artist, english_title)
    if audio_match is True:
        validation_status = "matched"
        validation_note = "Audio filename matches the English artist and title metadata."
    elif audio_match is False:
        validation_status = "mismatch"
        validation_note = "Audio filename does not match the English artist and title metadata."
    else:
        validation_status = "needs_review"
        if artist_source == "audio_filename_candidate":
            validation_note = "Artist is a candidate extracted from the audio filename and requires confirmation."
        else:
            validation_note = "Artist/title metadata is incomplete or has an uncertain transliteration."

    return {
        "artist": artist,
        "title": title,
        "validation_status": validation_status,
        "validation_note": validation_note,
        "artist_source": artist_source,
        "artist_confidence": artist_confidence,
        **scope,
        **classification,
    }


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


def _metadata_fields(identity):
    return {
        "source_categories_json": json.dumps(
            identity.get("source_categories", []), ensure_ascii=False
        ),
        "mood_tags_json": json.dumps(identity.get("mood_tags", []), ensure_ascii=False),
        "genre_tags_json": json.dumps(identity.get("genre_tags", []), ensure_ascii=False),
        "language_tags_json": json.dumps(identity.get("language_tags", []), ensure_ascii=False),
        "region_tags_json": json.dumps(identity.get("region_tags", []), ensure_ascii=False),
        "trend_tags_json": json.dumps(identity.get("trend_tags", []), ensure_ascii=False),
        "version_type": identity.get("version_type"),
        "artist_source": identity.get("artist_source"),
        "artist_confidence": identity.get("artist_confidence"),
        "catalog_scope": identity.get("catalog_scope", "uncertain"),
        "scope_confidence": identity.get("scope_confidence", "low"),
        "scope_evidence": identity.get("scope_evidence", "no_verified_origin_evidence"),
    }


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

    identity = _extract_track_identity(article, audio_url)

    external_id = _clean(article.get("data-id"))
    if not external_id:
        match = re.search(r"/download-song/(\d+)/?", urlparse(page_url).path)
        external_id = match.group(1) if match else None

    heading_tag = article.select_one("header h1, header h2, h1, h2")
    heading = _clean(heading_tag.get_text(" ", strip=True)) if heading_tag else None
    if not identity["title"]:
        identity["title"] = _fallback_heading_title(heading)

    date_tag = article.select_one("header div span")
    release_date = _clean(date_tag.get_text(" ", strip=True)) if date_tag else None

    if not external_id and not audio_url and not identity["artist"] and not identity["title"]:
        return None

    result = {
        "external_id": external_id,
        "artist": identity["artist"],
        "title": identity["title"],
        "release_date": release_date,
        "source_url": page_url,
        "artwork_url": _extract_artwork(article, page_url),
        "audio_url": audio_url,
        "fingerprint": f"musics-fa:{external_id}" if external_id else page_url,
        "validation_status": identity["validation_status"],
        "validation_note": identity["validation_note"],
    }
    result.update(_metadata_fields(identity))
    return result


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
        audio_url = (
            urljoin(page_url, player.get("data-song", ""))
            if player and player.get("data-song")
            else None
        )

        date_tag = article.select_one("header div span")
        release_date = _clean(date_tag.get_text(" ", strip=True)) if date_tag else None
        artwork_url = _extract_artwork(article, page_url)

        identity = _extract_track_identity(article, audio_url)
        heading = _clean(link.get_text(" ", strip=True))
        if not identity["title"]:
            identity["title"] = _fallback_heading_title(heading)

        track = {
            "external_id": external_id,
            "artist": identity["artist"],
            "title": identity["title"],
            "release_date": release_date,
            "source_url": source_url,
            "artwork_url": artwork_url,
            "audio_url": audio_url,
            "fingerprint": f"musics-fa:{external_id}" if external_id else source_url,
            "validation_status": identity["validation_status"],
            "validation_note": identity["validation_note"],
        }
        track.update(_metadata_fields(identity))
        tracks.append(track)

    return tracks
