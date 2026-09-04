"""Tests for human-in-the-loop review node."""

from src.agents.graph import review_node


def test_review_node_passes_on_approve():
    state = {
        "answer": "Good answer with facts",
        "agent_type": "due_diligence",
        "human_review_decision": "approve",
        "trace": [],
    }
    result = review_node(state)
    assert result["reviewed"] is True
    # _traced adds trace, reviewed node doesn't modify answer
    assert "answer" not in result or result.get("answer") == state["answer"]


def test_review_node_edits_on_reject():
    state = {
        "answer": "Bad answer",
        "agent_type": "due_diligence",
        "human_review_decision": "edit",
        "human_edited_answer": "Corrected answer with facts",
        "trace": [],
    }
    result = review_node(state)
    assert result["reviewed"] is True
    assert result["answer"] == "Corrected answer with facts"


def test_review_node_pending_when_no_decision():
    state = {
        "answer": "Answer awaiting review",
        "agent_type": "due_diligence",
        "trace": [],
    }
    result = review_node(state)
    assert result.get("review_pending") is True
