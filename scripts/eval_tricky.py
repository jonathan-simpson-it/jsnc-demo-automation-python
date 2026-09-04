"""Adversarial QA check: 15 tricky questions across the knowledge base.

Deliberately includes failure-mode shapes that easy questions miss:
cross-document ambiguity, misrouting bait, negative numbers, unit and
acronym phrasing, genuine not-found cases, and free-form rescue answers.

Usage:
    python scripts/eval_tricky.py                # run all 15
    python scripts/eval_tricky.py --query-only   # print questions without LLM calls

Scoring reuses eval_qa.normalize / score_answer (| = alternatives, ; = all).
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.eval_qa import score_answer  # noqa: E402

TRICKY_QUESTIONS: list[dict] = [
    # Cross-document ambiguity: "Archbridge" exists in the memo AND the CV
    {"doc": "cv", "q": "What is the candidate's current role at Archbridge Capital Partners?",
     "a": "AI Engineer"},
    # Misrouting bait: "Hitachi" should win over all other documents
    {"doc": "cv", "q": "Which company hosted the candidate's software placement internship?",
     "a": "Hitachi Rail"},
    # Synonym / paraphrase phrasing
    {"doc": "cv", "q": "By what percentage was manual processing time reduced at Archbridge?",
     "a": "60%"},
    # Two CEOs in the corpus (Acme memo vs annual report) — must route correctly
    {"doc": "annual_report", "q": "Who is the Chief Executive Officer of the semiconductor company?",
     "a": "John K. Kibarian"},
    {"doc": "memo", "q": "Who is the CEO of Acme Corp?", "a": "Sarah Chen"},
    # Negative number + GAAP/non-GAAP ambiguity
    {"doc": "annual_report", "q": "What was the GAAP diluted EPS in 2025?", "a": "-0.02|(0.02)|$(0.02)"},
    # Unit and currency phrasing
    {"doc": "enosis", "q": "How much does the government subsidise each doctor per month?",
     "a": "500"},
    # Number with trailing "+"
    {"doc": "enosis", "q": "How many private clinics are in Enosis's Hong Kong target pool?",
     "a": "3000+"},
    # Acronym (PDPO) instead of the full ordinance name
    {"doc": "dr_yip", "q": "Which privacy ordinance does the proposal align with for PII?",
     "a": "PDPO|Personal Data (Privacy) Ordinance"},
    # Date phrasing swap (due → submit)
    {"doc": "syllabus", "q": "When must students submit the project proposal?", "a": "Oct 11|October 11"},
    # Grade band cross-reference
    {"doc": "syllabus", "q": "What letter grade corresponds to 96-100 points?", "a": "A+"},
    # Small number that search often buries
    {"doc": "lifexp", "q": "How many active skills does the LifeXP free tier allow?", "a": "3"},
    # Negative phrasing ("must never")
    {"doc": "lifexp", "q": "What must the LifeXP AI never do?", "a": "invent experiences|invent"},
    # Term sheet extraction agent routing
    {"doc": "term_sheet", "q": "What is the liquidation preference in the Acme term sheet?",
     "a": "1x Non-participating|Non-participating"},
    # Genuine not-found: the annual report actually states dividends —
    # the pipeline must surface that statement, not hallucinate a number
    {"doc": "annual_report", "q": "What is the dividend per share of the semiconductor company?",
     "a": "no cash dividends|not declared|none|not found"},
]


def main() -> int:
    parser = argparse.ArgumentParser(description="Adversarial QA check (15 tricky questions)")
    parser.add_argument("--query-only", action="store_true", help="print questions only")
    args = parser.parse_args()

    if args.query_only:
        for i, item in enumerate(TRICKY_QUESTIONS, 1):
            print(f"{i:>2}. [{item['doc']}] {item['q']}  ->  {item['a']}")
        return 0

    from src.agents.router import RouterAgent  # noqa: E402
    from src.vector_store.chroma import VectorStore  # noqa: E402

    router = RouterAgent(VectorStore())
    passed = 0
    total = len(TRICKY_QUESTIONS)
    run_start = time.monotonic()

    for idx, item in enumerate(TRICKY_QUESTIONS, 1):
        q = item["q"]
        q_start = time.monotonic()
        response = router.invoke(q)
        latency = round((time.monotonic() - q_start) * 1000)

        try:
            parsed = json.loads(response.result)
            if response.agent_type == "term_sheet":
                parts = [parsed.get("liquidation_preference", ""), parsed.get("company_name", "")]
            elif response.agent_type == "lp_report":
                parts = [parsed.get("quarter", "")] + parsed.get("portfolio_highlights", [])
            elif response.agent_type == "compliance":
                parts = [parsed.get("document_name", ""), str(parsed.get("compliant", ""))]
                parts += parsed.get("issues", [])
            else:
                parts = [parsed.get("summary", "")]
                parts.extend(parsed.get("risks", []))
                parts.extend(parsed.get("opportunities", []))
                parts.append(parsed.get("recommendation", ""))
            actual = "\n".join(parts)
        except json.JSONDecodeError:
            actual = response.result
        actual = f"{actual}\n{' '.join(response.citations)}"

        nodes = [t["node"] for t in response.metadata.get("trace", [])]
        ok = score_answer(item["a"], actual)
        passed += 1 if ok else 0
        print(f"[{idx:>2}/{total}] {'PASS' if ok else 'FAIL'} {item['doc']:>12} ({latency}ms) {q}")
        if not ok:
            print(f"    expected: {item['a']}")
            print(f"    actual:   {actual[:220]!r}")
            print(f"    nodes:    {nodes}")

    run_ms = round((time.monotonic() - run_start) * 1000)
    print(f"\n=== TRICKY RESULT: {passed}/{total} ({100.0 * passed / total:.0f}%) in {run_ms}ms ===")
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
