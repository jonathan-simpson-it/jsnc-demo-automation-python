"""Tests for the radar feed aggregation (per-section, dedupe)."""

from src.api.routes.regulatory import (
    SFC_SECTIONS,
    _dedupe,
    _newest,
    _sfc_by_section,
)


def _item(regulator, external_id, kind, issued_at):
    return {
        "regulator": regulator,
        "external_id": external_id,
        "kind": kind,
        "issued_at": issued_at,
        "title": f"{regulator}-{external_id}",
    }


def test_sfc_sections_each_keep_newest_items():
    rows = [
        _item("SFC", "e1", "event", "2020-01-01"),
        _item("SFC", "e2", "event", "2025-06-01"),
        _item("SFC", "h1", "high shareholding", "2026-09-01"),
        _item("SFC", "n1", "news", "2026-07-23"),
    ]
    result = _sfc_by_section(rows)
    # Section order: news, policy statement, high shareholding, event
    kinds = [r["kind"] for r in result]
    assert kinds == ["news", "high shareholding", "event", "event"]
    # Slower sections are not crowded out by newer news items
    assert any(r["kind"] == "event" for r in result)
    assert any(r["kind"] == "high shareholding" for r in result)


def test_sfc_section_cap():
    rows = [
        _item("SFC", f"n{i:03d}", "news", f"2026-01-{(i % 28) + 1:02d}")
        for i in range(25)
    ]
    news = [r for r in _sfc_by_section(rows) if r["kind"] == "news"]
    assert len(news) == 10


def test_dedupe_prefers_specific_section_over_news():
    rows = [
        _item("SFC", "26PR99", "news", "2026-07-01"),
        _item("SFC", "26PR99", "event", "2026-07-01"),
    ]
    result = _sfc_by_section(rows)
    assert len(result) == 1
    assert result[0]["kind"] == "event"


def test_newest_first_with_missing_dates_last():
    rows = [
        _item("HKMA", "old", "press release", "2026-01-05"),
        _item("HKMA", "none", "press release", None),
        _item("HKMA", "new", "press release", "2026-09-01"),
    ]
    top = _newest(_dedupe(rows))
    assert [t["external_id"] for t in top] == ["new", "old", "none"]


def test_legacy_text_dates_are_sorted():
    rows = [
        _item("HKMA", "a", "press release", "20 Oct 2026"),
        _item("HKMA", "b", "press release", "01 Oct 2026"),
    ]
    top = _newest(_dedupe(rows))
    assert [t["external_id"] for t in top] == ["a", "b"]
