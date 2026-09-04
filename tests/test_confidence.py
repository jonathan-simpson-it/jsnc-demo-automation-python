"""Tests for confidence scoring and pipeline trace utilities."""

from src.utils.confidence import (
    classify_routing_method,
    compute_confidence,
    trace_summary,
)

# ---------------------------------------------------------------------------
# compute_confidence
# ---------------------------------------------------------------------------

def test_clean_path_high_confidence():
    """A clean classify→search→narrow→answer path with citations = high confidence."""
    trace = [
        {"node": "classify", "ms": 5},
        {"node": "search", "ms": 120},
        {"node": "narrow", "ms": 10},
        {"node": "answer", "ms": 800},
    ]
    citations = [
        "memo.md, page 1, line 5",
        "memo.md, page 2, line 1",
        "memo.md, page 3, line 10",
    ]
    score = compute_confidence(trace, citations)
    assert score >= 0.9, f"Expected >= 0.9 for clean path, got {score}"


def test_rescue_path_lower_confidence():
    """When verify fires, confidence drops."""
    trace_clean = [
        {"node": "classify", "ms": 5},
        {"node": "search", "ms": 120},
        {"node": "narrow", "ms": 10},
        {"node": "answer", "ms": 800},
    ]
    trace_rescue = [
        {"node": "classify", "ms": 5},
        {"node": "search", "ms": 120},
        {"node": "narrow", "ms": 10},
        {"node": "answer", "ms": 800},
        {"node": "verify", "ms": 600},
    ]
    citations = ["memo.md, page 1, line 5"]
    score_clean = compute_confidence(trace_clean, citations)
    score_rescue = compute_confidence(trace_rescue, citations)
    assert score_rescue < score_clean, (
        f"Rescue path should lower confidence: {score_rescue} >= {score_clean}"
    )


def test_wide_search_double_penalty():
    """wide_search after verify adds a second penalty."""
    trace_double = [
        {"node": "search", "ms": 120},
        {"node": "narrow", "ms": 10},
        {"node": "answer", "ms": 800},
        {"node": "verify", "ms": 600},
        {"node": "wide_search", "ms": 900},
    ]
    trace_single = [
        {"node": "search", "ms": 120},
        {"node": "narrow", "ms": 10},
        {"node": "answer", "ms": 800},
        {"node": "verify", "ms": 600},
    ]
    score_double = compute_confidence(trace_double, ["memo.md, p1, l1"])
    score_single = compute_confidence(trace_single, ["memo.md, p1, l1"])
    assert score_double < score_single, (
        f"Double rescue should score lower: {score_double} >= {score_single}"
    )
    assert score_double <= 0.65, (
        f"Expected <= 0.65 for double rescue with citation, got {score_double}"
    )


def test_no_citations_penalty():
    """No citations lowers confidence."""
    trace = [
        {"node": "search", "ms": 120},
        {"node": "answer", "ms": 800},
    ]
    score_no_cite = compute_confidence(trace, [])
    score_with_cite = compute_confidence(trace, ["memo.md, page 1, line 5"])
    assert score_no_cite < score_with_cite, (
        f"No citations should lower confidence: {score_no_cite} >= {score_with_cite}"
    )


def test_clamped_to_range():
    """Score never drops below 0.05 or exceeds 1.0."""
    worst_trace = [
        {"node": "search", "ms": 100},
        {"node": "answer", "ms": 500},
        {"node": "verify", "ms": 500},
        {"node": "wide_search", "ms": 500},
    ]
    score = compute_confidence(worst_trace, [])
    assert 0.05 <= score <= 1.0, f"Score {score} outside [0.05, 1.0]"

    best_trace = [
        {"node": "classify", "ms": 5},
        {"node": "search", "ms": 50},
        {"node": "narrow", "ms": 5},
        {"node": "answer", "ms": 200},
    ]
    citations = ["a.md, p1, l1", "a.md, p2, l1", "a.md, p3, l1"]
    score = compute_confidence(best_trace, citations)
    assert 0.05 <= score <= 1.0, f"Score {score} outside [0.05, 1.0]"


def test_source_filter_bonus():
    """Scoped search gets a small confidence bonus."""
    trace = [
        {"node": "search", "ms": 100},
        {"node": "answer", "ms": 500},
    ]
    citations = ["memo.md, page 1, line 5"]
    score_global = compute_confidence(trace, citations)
    score_scoped = compute_confidence(trace, citations, source_filter="memo.md")
    assert score_scoped > score_global, (
        f"Scoped should boost confidence: {score_scoped} <= {score_global}"
    )


def test_mixed_doc_penalty():
    """Citations from many different docs slightly lowers confidence."""
    trace = [
        {"node": "search", "ms": 100},
        {"node": "answer", "ms": 500},
    ]
    single_doc = ["a.md, p1, l1", "a.md, p2, l1", "a.md, p3, l1"]
    multi_doc = ["a.md, p1, l1", "b.md, p1, l1", "c.md, p1, l1"]
    score_single = compute_confidence(trace, single_doc)
    score_multi = compute_confidence(trace, multi_doc)
    assert score_multi <= score_single, (
        f"Mixed docs should not boost: {score_multi} > {score_single}"
    )


# ---------------------------------------------------------------------------
# classify_routing_method
# ---------------------------------------------------------------------------

def test_forced_routing():
    """When agent_type is provided, routing is 'forced'."""
    trace = [{"node": "search", "ms": 100}]
    assert classify_routing_method(trace, agent_type_forced=True) == "forced"


def test_auto_routing_with_classify():
    """When classify node fired, routing is 'auto'."""
    trace = [
        {"node": "classify", "ms": 50},
        {"node": "search", "ms": 100},
    ]
    assert classify_routing_method(trace, agent_type_forced=False) == "auto"


def test_auto_routing_skip_classify():
    """When classify node is absent and not forced, still returns 'forced'
    because the conditional entry skipped it."""
    trace = [
        {"node": "search", "ms": 100},
        {"node": "answer", "ms": 500},
    ]
    assert classify_routing_method(trace, agent_type_forced=False) == "forced"


# ---------------------------------------------------------------------------
# trace_summary
# ---------------------------------------------------------------------------

def test_trace_summary_basic():
    """Trace summary extracts correct fields."""
    trace = [
        {"node": "classify", "ms": 5},
        {"node": "search", "ms": 120},
        {"node": "answer", "ms": 800},
    ]
    summary = trace_summary(trace)
    assert summary["path"] == ["classify", "search", "answer"]
    assert summary["total_ms"] == 925
    assert summary["llm_calls"] == 2  # classify + answer
    assert summary["rescue_fired"] is False
    assert summary["bottleneck"] == "answer"


def test_trace_summary_rescue():
    """Rescue path detected in summary."""
    trace = [
        {"node": "search", "ms": 100},
        {"node": "answer", "ms": 500},
        {"node": "verify", "ms": 400},
        {"node": "wide_search", "ms": 300},
    ]
    summary = trace_summary(trace)
    assert summary["rescue_fired"] is True
    assert summary["llm_calls"] == 3  # answer + verify + wide_search


def test_empty_trace():
    """Empty trace produces safe defaults."""
    summary = trace_summary([])
    assert summary["path"] == []
    assert summary["total_ms"] == 0
    assert summary["llm_calls"] == 0
    assert summary["rescue_fired"] is False
    assert summary["bottleneck"] is None
