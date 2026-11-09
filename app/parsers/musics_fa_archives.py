import re
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup


def extract_artist_links(html, page_url):
    """Return real /artists/ archive links found on a Musics-fa page."""
    soup = BeautifulSoup(html, "html.parser")
    found = {}
    for link in soup.select("a[href]"):
        href = urljoin(page_url, link.get("href", ""))
        parsed = urlparse(href)
        if parsed.hostname not in {"musics-fa.com", "www.musics-fa.com"}:
            continue
        if not parsed.path.startswith("/artists/"):
            continue
        canonical_path = parsed.path.rstrip("/") + "/"
        canonical_url = f"https://musics-fa.com{canonical_path}"
        name = link.get_text(" ", strip=True)
        if name:
            found.setdefault(canonical_url, name)
    return [{"name": name, "source_url": url} for url, name in found.items()]


def parse_artist_archive(html, page_url):
    """Extract artist identity and track links from a verified artist archive."""
    from app.parsers.musics_fa import parse_tracks

    soup = BeautifulSoup(html, "html.parser")
    heading = soup.select_one("main h1, article h1, h1")
    title = heading.get_text(" ", strip=True) if heading else (
        soup.title.get_text(" ", strip=True) if soup.title else ""
    )
    title = re.sub(
        r"^(?:دانلود\\s*)?(?:تمام\\s*)?آهنگ(?:های| های)?\\s*",
        "",
        title,
    )
    title = re.sub(
        r"\\s*(?:جدید و کامل|جدید|MP3).*?$",
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
    image = soup.select_one("main img, article img, .artist img")
    artwork_url = None
    if image:
        image_src = image.get("data-src") or image.get("data-lazy-src") or image.get("src")
        if image_src:
            artwork_url = urljoin(page_url, image_src)

    tracks = parse_tracks(html, page_url)
    next_links = []
    for link in soup.select("a[href]"):
        label = link.get_text(" ", strip=True).lower()
        rel = link.get("rel") or []
        href = link.get("href", "")
        if "next" in rel or label in {"بعدی", "صفحه بعدی", "بعد"}:
            next_links.append(urljoin(page_url, href))

    return {
        "name": title or None,
        "source_url": canonical_url,
        "description": description,
        "artwork_url": artwork_url,
        "tracks": tracks,
        "next_pages": list(dict.fromkeys(next_links)),
    }
