"""Tests for regulatory explainability export."""

from src.compliance.explain import ExplainabilityReport


def test_generate_basic_report():
    report = ExplainabilityReport(
        query="What is the liquidation preference?",
        response="1x non-participating preferred",
        agent_type="term_sheet",
        trace=[
            {"node": "classify", "ms": 5},
            {"node": "search", "ms": 120},
            {"node": "narrow", "ms": 10},
            {"node": "answer", "ms": 500},
        ],
        citations=["sample_term_sheet.md, page 1, line 5"],
        confidence=0.92,
        model_version="deepseek-chat",
        user_id="analyst_001",
    )
    output = report.generate()
    assert "liquidation preference" in output
    assert "term_sheet" in output
    assert "92.0%" in output
    assert "classify" in output
    assert "deepseek-chat" in output


def test_report_includes_sources():
    report = ExplainabilityReport(
        query="test",
        response="answer",
        agent_type="dd",
        trace=[],
        citations=["doc.md, page 1, line 1", "doc.md, page 2, line 3"],
        confidence=0.85,
        model_version="v1",
        user_id="u1",
    )
    output = report.generate()
    assert "doc.md" in output
    assert "2" in output  # source count


def test_report_rescue_path():
    report = ExplainabilityReport(
        query="test",
        response="answer",
        agent_type="dd",
        trace=[
            {"node": "classify", "ms": 5},
            {"node": "search", "ms": 100},
            {"node": "answer", "ms": 500},
            {"node": "verify", "ms": 200},
            {"node": "wide_search", "ms": 300},
        ],
        citations=["doc.md"],
        confidence=0.45,
        model_version="v1",
        user_id="u1",
    )
    output = report.generate()
    assert "rescue" in output.lower() or "re-examination" in output.lower()
    assert "verify" in output
