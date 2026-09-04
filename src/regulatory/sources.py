"""Regulatory Radar: SFC/HKMA source configuration.

Sources cover the news hubs the Radar page cares about:

- SFC "News and announcements" family (https://www.sfc.hk/en/News-and-announcements):
  the site renders its lists client-side, so these are fetched through the
  same JSON search API the site uses (mode="sfc_api", one source per category:
  all / corporate / enforcement).
- SFC circulars page: server-rendered HTML (mode="html", fixture-backed).
- HKMA news hub (https://www.hkma.gov.hk/eng/news-and-media/): server-rendered
  HTML; the hub's subsections (press releases, speeches) are scraped as
  "hkma_html" list pages discovered from the hub itself.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class RegulatorySource:
    key: str
    regulator: str
    kind: str
    url: str
    # Fetch strategy: "html" (parse <article> markup), "hkma_html" (new HKMA
    # news lists, hub + subsections), "sfc_api" (SFC JSON news search API),
    # or "sfc_section_html" (server-rendered SFC section tables).
    mode: str = "html"
    # SFC search category used by the news API (mode="sfc_api").
    category: str = ""
    # HKMA hub subsection path fragments to scrape (mode="hkma_html").
    subsections: tuple[str, ...] = ()
    html_fixture: str = ""
    # Legacy/fixture-backed sources: still usable by offline tests, but the
    # live poller must never run them (their pages are JS shells or gone, and
    # fixture fallback would inject fictional demo rows into the real feed).
    fixture_only: bool = False


SOURCES = [
    # --- SFC: News and announcements (multiple sections, JSON API) ---
    RegulatorySource(
        key="sfc_news",
        regulator="SFC",
        kind="news",
        url="https://www.sfc.hk/en/News-and-announcements/News/All-news",
        mode="sfc_api",
        category="all",
    ),
    # SFC "News and announcements" hub sections are server-rendered tables
    # (no public JSON API exists for them), scraped as section sources.
    RegulatorySource(
        key="sfc_policy_statements",
        regulator="SFC",
        kind="policy statement",
        url="https://www.sfc.hk/en/News-and-announcements/Policy-statements-and-announcements",
        mode="sfc_section_html",
    ),
    RegulatorySource(
        key="sfc_high_shareholding",
        regulator="SFC",
        kind="high shareholding",
        url="https://www.sfc.hk/en/News-and-announcements/High-shareholding-concentration-announcements",
        mode="sfc_section_html",
    ),
    RegulatorySource(
        key="sfc_events",
        regulator="SFC",
        kind="event",
        url="https://www.sfc.hk/en/News-and-announcements/Events",
        mode="sfc_section_html",
    ),
    # --- SFC: circulars (legacy server-rendered page; now a JS shell, so this
    # source is fixture-only and used by offline tests, never polled live) ---
    RegulatorySource(
        key="sfc_circulars",
        regulator="SFC",
        kind="circular",
        url="https://www.sfc.hk/en/Regulatory-functions/Intermediaries/Circulars-to-licensed-corporations",
        mode="html",
        html_fixture="sfc_circulars_list.html",
        fixture_only=True,
    ),
    # --- HKMA: news hub (server-rendered HTML lists) ---
    RegulatorySource(
        key="hkma_news",
        regulator="HKMA",
        kind="press release",
        url="https://www.hkma.gov.hk/eng/news-and-media/",
        mode="hkma_html",
        subsections=("press-releases", "speeches", "insight"),
        html_fixture="hkma_press_list.html",
    ),
    # --- HKMA: legacy press-release page (fixture-only, used by offline
    # tests; the real HKMA news comes from the hkma_news hub source) ---
    RegulatorySource(
        key="hkma_circulars",
        regulator="HKMA",
        kind="press release",
        url="https://www.hkma.gov.hk/eng/key-information/press-releases/",
        mode="html",
        html_fixture="hkma_press_list.html",
        fixture_only=True,
    ),
]

# HKMA subsection -> human category label (drives feed `kind` per item).
HKMA_SUBSECTION_KINDS = {
    "press-releases": "press release",
    "speeches": "speech",
    "insight": "insight",
}


def source_by_key(key: str) -> RegulatorySource | None:
    return next((s for s in SOURCES if s.key == key), None)
