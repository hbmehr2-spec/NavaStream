import re
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup


ALBUM_EN_RE = re.compile(
    r"Download\s+(?:New\s+)?Album\s+BY\s*:\s*(?P<artist>[^|]+?)\s*\|\s*(?P<album>.+?)(?=\s+With\s+(?:Text|Lyrics)\b|\s+And\s+\d+\s+Quality\b|\s+On\s+Music-fa\b|$)",
    re.IGNORECASE,
)


NON_ARTIST_ARCHIVE_NAMES = {
    "هوش مصنوعی",
    "ترکی",
    "کردی",
    "موسیقی ترکی",
    "آهنگ ترکی",
    "آهنگ های ترکی",
    "موسیقی کردی",
    "آهنگ کردی",
    "آهنگ های کردی",
    "artificial intelligence",
    "ai music",
    "turkish",
    "turkish music",
    "kurdish",
    "kurdish music",
}


def _is_non_artist_archive_name(name):
    normalized = re.sub(r"\\s+", " ", (name or "").strip().lower())
    return normalized in NON_ARTIST_ARCHIVE_NAMES


def extract_artist_links(html, page_url):
    """Return person/group archive links, excluding category and pagination URLs."""
    soup = BeautifulSoup(html, "html.parser")
    found = {}
    for link in soup.select("a[href]"):
        href = urljoin(page_url, link.get("href", ""))
        parsed = urlparse(href)
        if parsed.hostname not in {"musics-fa.com", "www.musics-fa.com"}:
            continue
        if not parsed.path.startswith("/artists/"):
            continue
        path_parts = [part for part in parsed.path.strip("/").split("/") if part]
        if len(path_parts) != 2:
            continue
        canonical_path = f"/artists/{path_parts[1]}/"
        canonical_url = f"https://musics-fa.com{canonical_path}"
        name = link.get_text(" ", strip=True)
        if name and not _is_non_artist_archive_name(name):
            found.setdefault(canonical_url, name)
    return [{"name": name, "source_url": url} for url, name in found.items()]


def _is_album_article(article):
    text = article.get_text(" ", strip=True)
    return bool(
        re.search(r"دانلود\s*آلبوم|Download\s+(?:New\s+)?Album\s+BY", text, re.IGNORECASE)
    )


def _parse_album_article(article, page_url, artist_name):
    heading = article.select_one("header h2 a, header h1 a, h2 a, h1 a")
    if not heading:
        return None
    source_url = urljoin(page_url, heading.get("href", ""))
    heading_text = heading.get_text(" ", strip=True)
    paragraphs = " ".join(
        item.get_text(" ", strip=True) for item in article.select("p")
    )
    combined = " ".join((heading_text, paragraphs, article.get_text(" ", strip=True)))
    english = ALBUM_EN_RE.search(combined)
    album_name = english.group("album").strip() if english else None
    artist_candidate = english.group("artist").strip() if english else artist_name
    if not album_name:
        album_name = re.sub(r"^دانلود\s*آلبوم(?:\s*جدید)?\s*", "", heading_text, flags=re.IGNORECASE)
        if artist_name and album_name.startswith(artist_name):
            album_name = album_name[len(artist_name):].strip(" -–—")
    album_name = re.sub(r"\s+", " ", album_name or "").strip(" -–—|")
    if not album_name or not source_url:
        return None

    date_tag = article.select_one("header div span")
    release_date = date_tag.get_text(" ", strip=True) if date_tag else None
    image = article.select_one("img")
    artwork_url = None
    if image:
        image_src = image.get("data-src") or image.get("data-lazy-src") or image.get("src")
        if image_src:
            artwork_url = urljoin(page_url, image_src)
    return {
        "name": album_name,
        "artist_name": artist_candidate or artist_name,
        "source_url": source_url,
        "release_date": release_date,
        "artwork_url": artwork_url,
    }


def parse_artist_archive(html, page_url):
    """Extract artist identity, album cards, and song links from an artist archive."""
    from app.parsers.musics_fa import classify_catalog_scope, parse_tracks

    soup = BeautifulSoup(html, "html.parser")
    heading = soup.select_one("main h1, article h1, h1")
    title = heading.get_text(" ", strip=True) if heading else (
        soup.title.get_text(" ", strip=True) if soup.title else ""
    )
    title = re.sub(
        r"^(?:دانلود\s*)?(?:تمام\s*)?(?:آهنگ(?:های| های)?|نوحه(?:های| های)?|مداحی(?:های| های)?)\s*",
        "",
        title,
    )
    title = re.sub(
        r"\s*(?:جدید و کامل|جدید|MP3).*?$",
        "",
        title,
        flags=re.IGNORECASE,
    ).strip(" -|")
    description_tag = soup.find("meta", attrs={"name": "description"})
    description = (
        description_tag.get("content", "").strip()
        if description_tag else None
    )
    canonical_tag = soup.find("link", rel=lambda value: value and "canonical" in value)
    canonical_url = (
        urljoin(page_url, canonical_tag.get("href"))
        if canonical_tag and canonical_tag.get("href") else page_url
    )
    image = soup.select_one(".artist img, .artist-avatar img, [itemprop='image']")
    artwork_url = None
    if image:
        image_src = image.get("data-src") or image.get("data-lazy-src") or image.get("src")
        if image_src:
            artwork_url = urljoin(page_url, image_src)

    albums = []
    for article in soup.select("article.mf_pst"):
        if _is_album_article(article):
            album = _parse_album_article(article, page_url, title)
            if album:
                albums.append(album)
            article.decompose()

    tracks = parse_tracks(str(soup), page_url)
    next_pages = []
    for link in soup.select("a[href]"):
        label = link.get_text(" ", strip=True).lower()
        rel = link.get("rel") or []
        href = link.get("href", "")
        if "next" in rel or label in {"بعدی", "صفحه بعدی", "بعد"}:
            next_pages.append(urljoin(page_url, href))

    return {
        "name": title or None,
        "source_url": canonical_url,
        "description": description,
        "artwork_url": artwork_url,
        **classify_catalog_scope(title),
        "tracks": tracks,
        "albums": albums,
        "next_pages": list(dict.fromkeys(next_pages)),
    }
