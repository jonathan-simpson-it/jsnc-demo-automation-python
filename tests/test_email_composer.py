"""Tests for the deterministic email composer."""

from src.email_composer import TONES, compose_draft


def _summary(queries=47, agents=None):
    return {
        "total_queries": queries,
        "avg_confidence": 0.84,
        "agent_breakdown": agents
        or [
            {"agent": "due_diligence", "count": 18, "pct": 38.0},
            {"agent": "term_sheet", "count": 12, "pct": 26.0},
        ],
        "top_queries": [
            {
                "query": "What are the key risks?",
                "agent": "due_diligence",
                "confidence": 0.91,
                "timestamp": "2026-09-01T14:32:00",
            },
        ],
        "user_activity": [{"user": "local", "queries": 47}],
    }


def test_compose_digest_without_llm_returns_template():
    out = compose_draft(_summary())
    assert out["generated_by"] == "template"
    assert "47" in out["body"]
    assert "due_diligence" in out["body"]
    assert out["subject"]


def test_zero_activity_still_builds_body():
    out = compose_draft(_summary(queries=0))
    assert "No activity" in out["body"]


def test_all_templates_and_tones_build():
    for key in ("digest", "monthly", "client", "alert"):
        for tone in TONES:
            out = compose_draft(_summary(), template_key=key, tone=tone)
            assert out["subject"] and len(out["body"]) > 40


def test_instructions_are_appended():
    out = compose_draft(_summary(), instructions="Mention the Enosis review.")
    assert "Enosis review" in out["body"]


def test_unknown_template_falls_back_to_digest():
    out = compose_draft(_summary(), template_key="nope")
    assert out["generated_by"] == "template"
    assert out["body"]


class _FakeLLM:
    def __init__(self, reply: str):
        self.reply = reply

    def invoke(self, messages):
        class R:
            content = self.reply
        return R()


def test_ai_refines_when_llm_provided():
    reply = '{"subject": "AI subject", "body": "## AI body\\n\\nRefined text."}'
    out = compose_draft(_summary(), llm=_FakeLLM(reply))
    assert out["generated_by"] == "ai"
    assert out["subject"] == "AI subject"
    assert "Refined text." in out["body"]


def test_bad_llm_json_falls_back_to_template():
    out = compose_draft(_summary(), llm=_FakeLLM("not json at all"))
    assert out["generated_by"] == "template"
    assert out["body"]


def test_llm_exception_falls_back_to_template():
    class Boom:
        def invoke(self, messages):
            raise RuntimeError("key missing")
    out = compose_draft(_summary(), llm=Boom())
    assert out["generated_by"] == "template"
