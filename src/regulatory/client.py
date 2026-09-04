"""Fetchers for SFC/HKMA regulatory listings.

Three fetch strategies, all best-effort with offline-safe fallbacks:

- "html": server-rendered <article> listing pages (fixture-backed).
- "hkma_html": the HKMA news hub (https://www.hkma.gov.hk/eng/news-and-media/).
  The hub page itself only carries navigation; the configured subsections
  (press releases, speeches) are scraped from the hub, then each list page is
  parsed for "<li>date</li><li><a>title</a>" entries.
- "sfc_api": the SFC News site is a client-side app; listings come from the
  same JSON search API the site uses
  (https://apps.sfc.hk/edistributionWeb/api/news/search). Content pages are
  fetched from the matching /api/news/content endpoint.

Live fetches never crash the app: on any failure the parser falls back to a
saved fixture when one exists, otherwise returns an empty list.
"""

import json
import re
from html import unescape
from pathlib import Path
from urllib.parse import urljoin, urlparse

from src.regulatory.sources import (
    HKMA_SUBSECTION_KINDS,
    RegulatorySource,
)

DEFAULT_FIXTURE_DIR = "tests/fixtures/regulatory"

# SFC API base discovered from the site's own bundle.
SFC_API_BASE = "https://apps.sfc.hk/edistributionWeb"
# Canonical SFC website page for a news item (the SPA article route the site
# itself links to); the API is used only to fetch content for ingestion.
SFC_NEWS_PAGE = (
    "https://apps.sfc.hk/edistributionWeb/gateway/EN/news-and-announcements/news/doc"
)
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
)


class FetchError(Exception):
    pass


def _read_fixture(filename: str, base_dir: str) -> str:
    path = Path(base_dir) / filename
    if not path.exists():
        raise FetchError(f"fixture not found: {path}")
    return path.read_text(encoding="utf-8")


def _clean_html(raw: str) -> str:
    return re.sub(r"\s+", " ", unescape(re.sub(r"<[^>]+>", " ", raw))).strip()


# Each poll run keeps only the newest items per source (recency matters for
# the Radar feed; old announcements belong in archives, not the feed).
MAX_ITEMS_PER_SOURCE = 10

_MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}


def _hkma_date_to_iso(date_raw: str) -> str | None:
    """Normalize '03 Sep 2026' -> '2026-09-03' (returns None when unknown)."""
    m = re.match(
        r"^\s*(\d{1,2})\s+([A-Za-z]{3,9})\.?\s+(\d{4})\s*$", date_raw.strip()
    )
    if not m:
        return None
    day, month_name, year = m.group(1), m.group(2).lower()[:3], m.group(3)
    month = _MONTHS.get(month_name)
    if month is None:
        return None
    return f"{year}-{month:02d}-{int(day):02d}"


def _sort_recent(items: list[dict], limit: int = MAX_ITEMS_PER_SOURCE) -> list[dict]:
    """Return the `limit` newest items by issued_at (missing dates last),
    keeping the source order stable within the same date."""
    def key(item: dict):
        date = item.get("issued_at") or ""
        return (date[:10] if date else "0000-00-00")
    ordered = sorted(items, key=key, reverse=True)
    return ordered[:limit]


# Boilerplate markers that terminate a page's main region (HKMA detail pages
# carry the site chrome above and below the actual article).
_REGION_END_MARKERS = (
    "class=\"footer",
    "id=\"footer",
    "related information",
    "back to top",
    "what do you want to do",
    "privacy policy",
)


def _main_region_html(html: str) -> str:
    """Extract the article region of a content page when a recognizable
    container exists; otherwise return the page unchanged."""
    m = re.search(r'<div[^>]*class="[^"]*template-content-area[^"]*"[^>]*>', html, re.I)
    if not m:
        # SFC content pages render the body right after the headline div.
        m = re.search(r'<div[^>]*class="[^"]*headline[^"]*"[^>]*>.*?</div>', html, re.I | re.S)
    if not m:
        return html
    region = html[m.end():]
    low = region.lower()
    cut = len(region)
    for marker in _REGION_END_MARKERS:
        idx = low.find(marker)
        if idx > 0 and idx < cut:
            cut = idx
    return region[:cut]


def _http_get_text(url: str, timeout: int = 20) -> str:
    import httpx

    try:
        with httpx.Client(timeout=timeout, follow_redirects=True) as client:
            resp = client.get(url, headers={"User-Agent": USER_AGENT})
            resp.raise_for_status()
            return resp.text
    except Exception as exc:
        raise FetchError(str(exc)) from exc


def _http_post_json(url: str, body: dict, timeout: int = 20) -> dict:
    import httpx

    try:
        with httpx.Client(timeout=timeout, follow_redirects=True) as client:
            resp = client.post(
                url,
                json=body,
                headers={
                    "User-Agent": USER_AGENT,
                    "Referer": "https://www.sfc.hk/en/News-and-announcements",
                },
            )
            resp.raise_for_status()
            return resp.json()
    except Exception as exc:
        raise FetchError(str(exc)) from exc


# ---------------------------------------------------------------------------
# Legacy server-rendered HTML (<article> blocks)
# ---------------------------------------------------------------------------

def _parse_article_listing(html: str, source: RegulatorySource) -> list[dict]:
    """Parse <article> blocks with a .title link and a .date element."""
    items = []
    for article in re.findall(r"<article>(.*?)</article>", html, re.S | re.I):
        link = re.search(
            r'<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>', article, re.S | re.I
        )
        if not link:
            continue
        href, raw_title = link.group(1), link.group(2)
        title = unescape(re.sub(r"<[^>]+>", "", raw_title)).strip()
        if not title:
            continue
        date_match = re.search(
            r'class="date"[^>]*>(.*?)<', article, re.S | re.I
        )
        date = unescape(date_match.group(1)).strip() if date_match else ""
        external_id = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:80]
        url = urljoin(source.url, href)
        items.append(
            {
                "external_id": external_id,
                "title": title,
                "url": url,
                "issued_at": _hkma_date_to_iso(date) or date or None,
            }
        )
    return items


def _fetch_html_listing(source: RegulatorySource, http_get) -> list[dict]:
    html = http_get(source.url)
    return _parse_article_listing(html, source)


# ---------------------------------------------------------------------------
# HKMA news hub: discover subsection lists from the hub, then scrape each.
# ---------------------------------------------------------------------------

_HKMA_ITEM_RE = re.compile(
    r"<ul>\s*<li>([^<]*)</li>\s*<li>\s*"
    r'<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>',
    re.S | re.I,
)


def _parse_hkma_list(html: str, list_url: str, kind: str) -> list[dict]:
    items = []
    for date_raw, href, raw_title in _HKMA_ITEM_RE.findall(html):
        title = _clean_html(raw_title)
        if not title or title in {"繁", "简"}:
            continue
        url = urljoin(list_url, href)
        slug = urlparse(url).path.rstrip("/").split("/")[-1] or None
        external_id = slug or re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:80]
        items.append(
            {
                "external_id": external_id,
                "title": title,
                "url": url,
                "issued_at": _hkma_date_to_iso(date_raw) or date_raw.strip() or None,
                "kind": kind,
            }
        )
    return items


def _fetch_hkma_hub(source: RegulatorySource, http_get) -> list[dict]:
    """Scrape the HKMA news hub by following its subsection list pages."""
    hub_html = http_get(source.url)
    hub_base = f"{urlparse(source.url).scheme}://{urlparse(source.url).netloc}"
    # Discover which configured subsections actually exist on the hub (the
    # menu links point at /eng/news-and-media/<subsection>/).
    configured = set(source.subsections)
    discovered: list[str] = []
    for href in re.findall(r'<a[^>]+href="([^"]+)"', hub_html, re.I):
        path = urlparse(urljoin(source.url, href)).path.rstrip("/")
        for sub in configured:
            if path.endswith(f"/news-and-media/{sub}"):
                if sub not in discovered:
                    discovered.append(sub)
    if not discovered:
        discovered = list(configured)

    items: list[dict] = []
    seen_urls: set[str] = set()
    for sub in discovered:
        kind = HKMA_SUBSECTION_KINDS.get(sub, source.kind)
        try:
            html = http_get(f"{hub_base}/eng/news-and-media/{sub}/")
            for item in _parse_hkma_list(html, f"{hub_base}/eng/news-and-media/{sub}/", kind):
                if item["url"] not in seen_urls:
                    seen_urls.add(item["url"])
                    items.append(item)
        except Exception:
            continue  # one dead subsection must not kill the hub pass
    return items


# ---------------------------------------------------------------------------
# SFC JSON search API (client-rendered news site)
# ---------------------------------------------------------------------------

_SFC_SEARCH_BODY = {
    "lang": "EN",
    "year": "all",
    "month": "all",
    "pageNo": 0,
    # Ask for a little more than the cap so recency sorting has slack.
    "pageSize": 20,
}


def _fetch_sfc_api(source: RegulatorySource, http_post) -> list[dict]:
    """Merge a few result pages, then keep the newest items.

    The site's search ordering is not strictly newest-first, so paging past
    the first page is required to actually find the most recent items.
    NOTE: page numbers are zero-based — pageNo 0 is the newest page.
    """
    items = []
    seen: set[str] = set()
    for page_no in range(0, 3):  # up to 60 candidates; enough for a 10-cap
        body = dict(_SFC_SEARCH_BODY)
        body["category"] = source.category or "all"
        body["pageNo"] = page_no
        data = http_post(f"{SFC_API_BASE}/api/news/search", body)
        rows = data.get("items", [])
        if not rows:
            break
        for row in rows:
            ref_no = row.get("newsRefNo")
            title = (row.get("title") or "").strip()
            if not ref_no or not title or ref_no in seen:
                continue
            seen.add(ref_no)
            date = (row.get("issueDate") or "")[:10]
            items.append(
                {
                    "external_id": ref_no,
                    "title": title,
                    "url": f"{SFC_NEWS_PAGE}?refNo={ref_no}",
                    "issued_at": date or None,
                }
            )
        if len(rows) < _SFC_SEARCH_BODY["pageSize"]:
            break
    return _sort_recent(items)


# ---------------------------------------------------------------------------
# SFC server-rendered section tables (Policy statements / High shareholding /
# Events): <table> rows with a date cell and an anchor.
# ---------------------------------------------------------------------------

_DATE_CELL_RE = re.compile(
    r"\b(\d{1,2} [A-Z][a-z]{2} \d{4})\b|\b(\d{4}-\d{2}-\d{2})\b"
)


def _row_date(cells_text: str) -> str | None:
    m = _DATE_CELL_RE.search(cells_text)
    if not m:
        return None
    raw = m.group(0)
    return _hkma_date_to_iso(raw) or raw


def _parse_sfc_section_table(
    html: str, list_url: str, kind: str
) -> list[dict]:
    """Parse a documents-on-display table: one item per data row."""
    items: list[dict] = []
    seen_urls: set[str] = set()
    for row in re.findall(r"<tr[^>]*>(.*?)</tr>", html, re.S | re.I):
        cells = re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", row, re.S | re.I)
        if not cells or any("<th" in c for c in row.split("<t")[1:] if c.startswith("h")):
            continue
        cell_texts = [_clean_html(c) for c in cells]
        date = _row_date(" ".join(cell_texts))
        anchors = re.findall(r'<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>', row, re.S | re.I)
        picks = []
        for href, raw in anchors:
            title = _clean_html(raw)
            if len(title) >= 10 and not re.match(r"^\d{1,2} [A-Z][a-z]{2} \d{4}$", title):
                picks.append((len(title), href, title))
        if not date or not picks:
            continue
        picks.sort(key=lambda t: t[0], reverse=True)
        _, href, title = picks[0]
        url = urljoin(list_url, href)
        if url in seen_urls:
            continue
        seen_urls.add(url)
        slug = urlparse(url).path.rstrip("/").split("/")[-1] or None
        external_id = (
            re.sub(r"[^a-z0-9]+", "-", (slug or title).lower()).strip("-")[:80]
        )
        items.append(
            {
                "external_id": external_id,
                "title": title,
                "url": url,
                "issued_at": date,
                "kind": kind,
            }
        )
    return items


def _fetch_sfc_section(source: RegulatorySource, http_get) -> list[dict]:
    return _parse_sfc_section_table(http_get(source.url), source.url, source.kind)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def fetch_listing(
    source: RegulatorySource,
    base_dir: str = DEFAULT_FIXTURE_DIR,
    _http_get=None,
    _http_post=None,
) -> list[dict]:
    """Return listing items for a source.

    Live fetch first (strategy depends on source.mode). Fixtures are used only
    when the live fetch itself fails (network/parse error) — a live page that
    legitimately returns no items must NOT be replaced with fixture data, or
    fictional demo rows would leak into the real feed.
    """
    http_get = _http_get or _http_get_text
    http_post = _http_post or _http_post_json
    try:
        if source.mode == "sfc_api":
            items = _fetch_sfc_api(source, http_post)
        elif source.mode == "hkma_html":
            items = _sort_recent(_fetch_hkma_hub(source, http_get))
        elif source.mode == "sfc_section_html":
            items = _sort_recent(_fetch_sfc_section(source, http_get))
        else:
            items = _sort_recent(_fetch_html_listing(source, http_get))
        return items
    except Exception:
        pass
    if source.html_fixture:
        try:
            html = _read_fixture(source.html_fixture, base_dir)
            if source.mode == "hkma_html":
                base = urlparse(source.url).scheme + "://" + urlparse(source.url).netloc
                return _sort_recent(_parse_hkma_list(html, f"{base}/eng/news-and-media/press-releases/", source.kind))
            return _sort_recent(_parse_article_listing(html, source))
        except Exception:
            pass
    return []


def _http_get_bytes(url: str, timeout: int = 20) -> bytes:
    import httpx

    try:
        with httpx.Client(timeout=timeout, follow_redirects=True) as client:
            resp = client.get(url, headers={"User-Agent": USER_AGENT})
            resp.raise_for_status()
            return resp.content
    except Exception as exc:
        raise FetchError(str(exc)) from exc


def _pdf_text(raw: bytes, max_chars: int = 6000) -> str:
    """Best-effort text extraction from a PDF (first pages only)."""
    try:
        from io import BytesIO

        from pypdf import PdfReader

        reader = PdfReader(BytesIO(raw))
        parts = []
        for page in reader.pages[:3]:
            parts.append(page.extract_text() or "")
            if sum(len(x) for x in parts) >= max_chars:
                break
        return " ".join(parts)[:max_chars]
    except Exception:
        return ""


def fetch_item_text(
    url: str,
    source: RegulatorySource,
    base_dir: str = DEFAULT_FIXTURE_DIR,
    _http_get=None,
) -> str:
    """Return cleaned article text for an item URL.

    Feed rows link to the human SFC website page (…/news/doc?refNo=…) but the
    body is server-rendered by the SPA only, so content is fetched from the
    content API behind the scenes. Direct API URLs, media PDFs (pypdf) and
    plain HTML pages are handled too. Offline => fixture by slug, else the
    bare title so ingest still records the item.
    """
    ref_match = re.search(r"[?&]refNo=([A-Z0-9]+)", url)
    api_content_url = None
    if ref_match and "/news/doc" in url:
        api_content_url = (
            f"{SFC_API_BASE}/api/news/content?refNo={ref_match.group(1)}&lang=EN"
        )
    http_get = _http_get or _http_get_text
    try:
        if api_content_url is not None and _http_get is None:
            data = json.loads(_http_get_text(api_content_url))
            text = _clean_html(data.get("html") or "")
        else:
            target = api_content_url if api_content_url is not None else url
            if _http_get is None and ("/-/media/" in target or target.lower().endswith(".pdf")):
                raw_bytes = _http_get_bytes(target)
                if raw_bytes[:5] == b"%PDF-":
                    pdf_text = _pdf_text(raw_bytes)
                    if pdf_text:
                        return _clean_html(pdf_text)
                raw = raw_bytes.decode("utf-8", errors="ignore")
            else:
                raw = http_get(target)
            text = ""
            if "/edistributionWeb/api/" in target:
                try:
                    data = json.loads(raw)
                    text = _clean_html(data.get("html") or "")
                except Exception:
                    text = _clean_html(raw)
            else:
                text = _clean_html(_main_region_html(raw))
        if text:
            return text
    except Exception:
        pass
    slug = url.rstrip("/").split("/")[-1] or source.key
    path = Path(base_dir) / f"{slug}.html"
    if path.exists():
        try:
            html = path.read_text(encoding="utf-8")
            return _clean_html(html)
        except Exception:
            pass
    return f"{source.regulator} {source.kind}: {slug}"
