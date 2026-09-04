"""Tests for LLM cost instrumentation in the agent graph.

Sandbox note: requires the project venv/CI (pytest, fastapi, langchain imports).
"""

from src.agents import graph
from src.utils.cost_tracker import cost_tracker


class _FakeLLM:
    """LLM stand-in returning a fixed non-empty text response."""

    def __init__(self, text: str = "Fake answer text. " * 10):
        self._text = text

    def invoke(self, messages):
        class _Msg:
            content = self._text
        return _Msg()


def test_invoke_text_records_cost_by_node():
    cost_tracker.reset()
    fake = _FakeLLM()
    out = graph._invoke_text(
        fake,
        [type("M", (), {"content": "Some prompt words here."})(), type("M", (), {"content": "Second message."})()],
        node="answer",
    )
    assert out.startswith("Fake answer text")
    summary = cost_tracker.get_summary()
    assert summary["by_node"]["answer"]["calls"] == 1
    assert summary["total_cost"] > 0
    assert summary["total_input_tokens"] >= 1
    assert summary["total_output_tokens"] >= 1


def test_reset_clears_totals():
    cost_tracker.reset()
    graph._invoke_text(_FakeLLM(), [], node="classify")
    assert cost_tracker.total_tokens > 0
    cost_tracker.reset()
    assert cost_tracker.total_tokens == 0
    assert cost_tracker.total_cost == 0.0
