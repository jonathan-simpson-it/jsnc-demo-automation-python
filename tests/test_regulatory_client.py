"""Tests for the fixture-driven regulatory client.

Sandbox note: requires the project venv/CI (pytest); runs fully offline by
forcing the fixture fallback through a raising _http_get stub.
"""

from src.regulatory.client import FetchError, fetch_item_text, fetch_listing
from src.regulatory.sources import SOURCES

BASE = "tests/fixtures/regulatory"


def _offline(url: str) -> str:
    raise FetchError("network disabled in tests")


def test_fetch_listing_sfc():
    source = next(s for s in SOURCES if s.key == "sfc_circulars")
    items = fetch_listing(source, BASE, _http_get=_offline)
    titles = [i["title"] for i in items]
    assert any("Virtual Asset Trading Platforms" in t for t in titles)
    assert any("AML/CFT screening" in t for t in titles)
    item = items[0]
    assert item["external_id"]
    assert item["url"].startswith("https://www.sfc.hk")
    assert item["issued_at"] == "2026-10-16"


def test_fetch_listing_hkma():
    source = next(s for s in SOURCES if s.key == "hkma_circulars")
    items = fetch_listing(source, BASE, _http_get=_offline)
    assert len(items) == 2
    assert items[0]["issued_at"] == "2026-10-20"


def test_fetch_item_text_from_fixture():
    source = next(s for s in SOURCES if s.key == "sfc_circulars")
    text = fetch_item_text(
        "https://www.sfc.hk/en/circulars/licensing-vasp-2026",
        source,
        BASE,
        _http_get=_offline,
    )
    assert "customer due diligence" in text.lower()
    assert "Anti-Money Laundering" in text


def test_sfc_api_listing_mapping():
    """SFC news categories map through the site's JSON search API."""
    from src.regulatory.sources import source_by_key

    source = source_by_key("sfc_news")
    assert source is not None and source.mode == "sfc_api"

    def fake_post(url, body):
        assert url.endswith("/api/news/search")
        assert body["category"] == "all"
        return {
            "items": [
                {
                    "newsRefNo": "26PR111",
                    "title": "Court sentences former broker",
                    "newsType": "PR",
                    "issueDate": "2026-09-01T09:00:00",
                },
                {"newsRefNo": "26PR222", "title": "", "issueDate": "2026-09-02T09:00:00"},
            ],
            "total": 1,
        }

    items = fetch_listing(source, BASE, _http_post=fake_post)
    assert len(items) == 1
    assert items[0]["external_id"] == "26PR111"
    assert items[0]["title"] == "Court sentences former broker"
    assert items[0]["issued_at"] == "2026-09-01"
    assert items[0]["url"].endswith("news/doc?refNo=26PR111")


def test_sfc_api_offline_returns_empty():
    """API-mode sources have no fixture: offline => empty, not a crash."""
    from src.regulatory.sources import source_by_key

    source = source_by_key("sfc_news")

    def offline_post(url, body):
        raise FetchError("network disabled in tests")

    assert fetch_listing(source, BASE, _http_get=_offline, _http_post=offline_post) == []


def test_hkma_hub_scraping():
    """The HKMA news hub is expanded into its subsection list pages."""
    from src.regulatory.sources import source_by_key

    source = source_by_key("hkma_news")
    assert source is not None and source.mode == "hkma_html"

    hub_html = (
        '<a href="/eng/news-and-media/">hub</a>'
        '<a href="/eng/news-and-media/press-releases/">Press Releases</a>'
        '<a href="/eng/news-and-media/speeches/">Speeches</a>'
    )
    list_html = (
        '<div class="press-release-result">'
        "<ul><li>03 Sep 2026</li><li>"
        '<a href="/eng/news-and-media/press-releases/2026/09/20260903-3/" '
        'title="Scam alert related to banks">Scam alert related to banks</a>'
        "</li></ul>"
    )
    calls = {"n": 0}

    def fake_get(url):
        calls["n"] += 1
        if url.endswith("/eng/news-and-media/"):
            return hub_html
        return list_html

    items = fetch_listing(source, BASE, _http_get=fake_get)
    assert calls["n"] == 3  # hub + press-releases + speeches
    assert items[0]["title"] == "Scam alert related to banks"
    assert items[0]["external_id"] == "20260903-3"
    assert items[0]["issued_at"] == "2026-09-03"
    assert items[0]["kind"] == "press release"
    assert items[0]["url"].startswith("https://www.hkma.gov.hk")


def test_sfc_api_item_text_parses_json_html():
    from src.regulatory.sources import source_by_key

    source = source_by_key("sfc_news")
    url = "https://apps.sfc.hk/edistributionWeb/api/news/content?refNo=26PR1&lang=EN"

    def fake_get(u):
        return '{"newsRefNo":"26PR1","html":"<p>Licensing <b>action</b> taken.</p>"}'

    text = fetch_item_text(url, source, BASE, _http_get=fake_get)
    assert "Licensing action taken." == text


def test_sfc_website_article_url_resolves_to_content_api():
    """Feed rows point at the SFC website; content comes from the API."""
    from src.regulatory.sources import source_by_key

    source = source_by_key("sfc_news")
    url = (
        "https://apps.sfc.hk/edistributionWeb/gateway/EN/"
        "news-and-announcements/news/doc?refNo=26PR2"
    )
    seen = []

    def fake_get(u):
        seen.append(u)
        return '{"newsRefNo":"26PR2","html":"<p>Website article body.</p>"}'

    text = fetch_item_text(url, source, BASE, _http_get=fake_get)
    assert text == "Website article body."
    assert seen and seen[0].endswith("/api/news/content?refNo=26PR2&lang=EN")
