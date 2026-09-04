"""Tests for cost tracking."""

from src.utils.cost_tracker import CostTracker


def test_record_and_get_total():
    tracker = CostTracker()
    tracker.record_call("answer", input_tokens=500, output_tokens=200)
    tracker.record_call("classify", input_tokens=100, output_tokens=10)
    assert tracker.total_tokens > 0
    assert tracker.total_cost > 0


def test_cost_per_node():
    tracker = CostTracker()
    tracker.record_call("answer", input_tokens=1000, output_tokens=500)
    tracker.record_call("answer", input_tokens=200, output_tokens=50)
    summary = tracker.get_summary()
    assert summary["calls"] == 2
    assert summary["total_input_tokens"] == 1200


def test_reset():
    tracker = CostTracker()
    tracker.record_call("answer", input_tokens=100, output_tokens=50)
    tracker.reset()
    assert tracker.total_tokens == 0
