"""Tests for temporal recency weighting of regulatory results.

Sandbox note: requires the project venv/CI (pytest).
"""

from datetime import date, timedelta

from src.tools.search import _apply_recency

MAX_DISTANCE = 2.0


def _result(days_old: int, regulator="SFC"):
    issued = (date.today() - timedelta(days=days_old)).isoformat()
    return {
        "content": f"reg text {days_old}",
        "metadata": {
            "regulator": regulator,
            "issuance_date": issued,
            "filename": "reg-sfc-x.txt",
        },
        "score": 0.5,
    }


def test_recent_regulatory_item_ranks_first():
    old = _result(days_old=3000)
    recent = _result(days_old=5)
    results = _apply_recency([old, recent])
    assert results[0]["content"] == recent["content"]
    assert results[1]["content"] == old["content"]
    assert results[0]["hybrid_score"] > results[1]["hybrid_score"]


def test_non_regulatory_results_unaffected():
    plain = {
        "content": "memo",
        "metadata": {"filename": "memo.pdf"},
        "score": 0.5,
    }
    results = _apply_recency([plain])
    assert "_recency_decay" not in results[0]
    assert "hybrid_score" not in results[0]


def test_missing_date_no_decay():
    no_date = {
        "content": "reg",
        "metadata": {"regulator": "HKMA", "filename": "x.txt"},
        "score": 0.5,
    }
    results = _apply_recency([no_date])
    assert "_recency_decay" not in results[0]
