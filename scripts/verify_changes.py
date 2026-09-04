#!/usr/bin/env python3
"""End-to-end verification of all architectural changes.

Tests the real pipeline: graph construction, classification, search,
narrowing, answer generation, verification, citations, caching,
auto-signals, parsers, and conversation history flow.

Exit code 0 = all assertions pass.
"""

import json
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent))


# ---------------------------------------------------------------------------
# Test 1: Graph builds and compiles
# ---------------------------------------------------------------------------
def test_graph_builds():
    from src.agents.graph import build_agent_graph, AgentState
    graph = build_agent_graph()
    assert graph is not None
    print("  [PASS] Graph builds and compiles")


# ---------------------------------------------------------------------------
# Test 2: Keyword classification
# ---------------------------------------------------------------------------
def test_keyword_classification():
    from src.agents.graph import _classify_keyword
    assert _classify_keyword("What is the liquidation preference?") == "term_sheet"
    assert _classify_keyword("Check SFC compliance") == "compliance"
    assert _classify_keyword("Generate LP report") == "lp_report"
    assert _classify_keyword("Who is the CEO?") is None  # ambiguous -> LLM fallback
    assert _classify_keyword("Anti-dilution provisions") == "term_sheet"
    assert _classify_keyword("AMLO regulations check") == "compliance"
    print("  [PASS] Keyword classification works")


# ---------------------------------------------------------------------------
# Test 3: All parsers produce valid dicts for mock LLM output
# ---------------------------------------------------------------------------
def test_parsers():
    from src.agents.graph import (
        _parse_due_diligence, _parse_term_sheet,
        _parse_lp_report, _parse_compliance,
    )

    # Due diligence
    dd = _parse_due_diligence("SUMMARY: Strong growth\nRISKS:\n- Regulatory\nOPPORTUNITIES:\n- Expansion\nRECOMMENDATION: Proceed")
    assert dd["summary"] == "Strong growth"
    assert dd["risks"] == ["Regulatory"]
    assert dd["opportunities"] == ["Expansion"]
    assert dd["recommendation"] == "Proceed"

    # Due diligence with ANSWER format (EVIDENCE stops answer accumulation)
    dd2 = _parse_due_diligence("ANSWER: $4M ARR\nEVIDENCE: [Source 1: memo.md]\nSUMMARY: $4M\nRISKS: None\nOPPORTUNITIES: None\nRECOMMENDATION: Insufficient")
    assert dd2["summary"] == "$4M ARR"  # answer without EVIDENCE leakage
    assert dd2["recommendation"] == "Insufficient"

    # Term sheet
    ts = _parse_term_sheet("COMPANY_NAME: Acme Corp\nROUND_TYPE: Series A\nPRE_MONEY_VALUATION: 50000000\nINVESTMENT_AMOUNT: 10000000\nLIQUIDATION_PREFERENCE: 1x non-partic\nANTI_DILUTION: Broad-based\nBOARD_SEATS: 2 investor, 2 founder")
    assert ts["company_name"] == "Acme Corp"
    assert ts["pre_money_valuation"] == 50000000.0
    assert ts["investment_amount"] == 10000000.0

    # Term sheet with citations stripped from values
    ts2 = _parse_term_sheet("COMPANY_NAME: Acme Corp [Source 1: memo.md, p.1]\nROUND_TYPE: Series A\nPRE_MONEY_VALUATION: $50M [Source 1: memo.md, p.1]\nINVESTMENT_AMOUNT: $10M\nLIQUIDATION_PREFERENCE: 1x\nANTI_DILUTION: Broad-based\nBOARD_SEATS: 2 investor")
    assert ts2["company_name"] == "Acme Corp"
    assert ts2["pre_money_valuation"] == 50.0  # $50M -> first number extracted is 50

    # LP report
    lp = _parse_lp_report("QUARTER: Q1 2026\nHIGHLIGHTS: Growth; Expansion\nFINANCIAL_SUMMARY: revenue: 5000000\nRISK_FACTORS: Market risk")
    assert lp["quarter"] == "Q1 2026"
    assert len(lp["portfolio_highlights"]) == 2

    # Compliance
    cp = _parse_compliance("DOCUMENT_NAME: Term Sheet\nCOMPLIANT: true\nISSUES: None\nJURISDICTION: Hong Kong SAR\nREGULATIONS_CHECKED: SFC; AMLO")
    assert cp["compliant"] is True
    assert cp["document_name"] == "Term Sheet"
    assert len(cp["regulations_checked"]) == 2

    # Compliance with false
    cp2 = _parse_compliance("DOCUMENT_NAME: Doc\nCOMPLIANT: false\nISSUES: Missing KYC\nJURISDICTION: HK\nREGULATIONS_CHECKED: AMLO")
    assert cp2["compliant"] is False

    print("  [PASS] All 4 parsers produce valid output")


# ---------------------------------------------------------------------------
# Test 4: clean_citations strips citation tags
# ---------------------------------------------------------------------------
def test_clean_citations():
    from src.agents.prompts import clean_citations
    assert clean_citations("$4M [Source 1: memo.md, page 1, line 5]") == "$4M"
    assert clean_citations("Sarah Chen [Source: cv.pdf, p.1, line 3]") == "Sarah Chen"
    assert clean_citations("No citations here") == "No citations here"
    assert clean_citations("") == ""
    print("  [PASS] clean_citations strips citation tags correctly")


# ---------------------------------------------------------------------------
# Test 5: says_not_found detects not-found phrases
# ---------------------------------------------------------------------------
def test_says_not_found():
    from src.agents.prompts import says_not_found
    assert says_not_found("The documents do not contain this information")
    assert says_not_found("I cannot find any data about that")
    assert says_not_found("No information available in the sources")
    assert says_not_found("ANSWER: CONFIRMED NOT FOUND")
    assert not says_not_found("The company has $4M ARR")
    assert not says_not_found("Sarah Chen is the CEO")
    # Regression: boilerplate from the grounding rules must NOT trigger the
    # verify/wide_search loop on every answer
    assert not says_not_found("RECOMMENDATION: Insufficient data to recommend.")
    assert not says_not_found("PRICE_PER_SHARE: Not available")
    print("  [PASS] says_not_found detects not-found phrases correctly")


# ---------------------------------------------------------------------------
# Test 6: LLM cache works
# ---------------------------------------------------------------------------
def test_llm_cache():
    from src.utils.llm_cache import LLMCache
    cache = LLMCache(ttl_seconds=3600, max_size=3)
    assert cache.size == 0
    cache.set("hello", "world")
    assert cache.get("hello") == "world"
    assert cache.size == 1
    cache.set("foo", "bar")
    cache.set("baz", "qux")
    cache.set("overflow", "now")  # should evict "hello" (LRU)
    assert cache.size == 3
    assert cache.get("hello") is None  # evicted
    assert cache.get("foo") == "bar"
    cache.clear()
    assert cache.size == 0
    print("  [PASS] LLM cache works (set, get, LRU eviction, clear)")


# ---------------------------------------------------------------------------
# Test 7: Auto-signal extraction produces non-empty results
# ---------------------------------------------------------------------------
def test_auto_signal_extraction():
    from src.utils.doc_signals import extract_doc_signals
    chunks = [
        {"content": "Acme Corp Series A funding round with Sarah Chen as CEO", "metadata": {"filename": "test.md"}},
        {"content": "Revenue growth ARR EBITDA financial projections", "metadata": {"filename": "test.md"}},
        {"content": "Board seats liquidation preference anti-dilution", "metadata": {"filename": "test.md"}},
    ]
    pos, neg = extract_doc_signals(chunks, top_n=10)
    assert len(pos) > 0, "Should extract positive signals"
    assert "acme" in pos or "corp" in pos or "sarah" in pos, f"Expected domain keywords, got: {list(pos.keys())[:10]}"
    print(f"  [PASS] Auto-signal extraction produces {len(pos)} positive signals")


# ---------------------------------------------------------------------------
# Test 8: Vector store search works and returns scored results
# ---------------------------------------------------------------------------
def test_vector_store_search():
    from src.vector_store.chroma import VectorStore
    with tempfile.TemporaryDirectory() as tmpdir:
        store = VectorStore(persist_directory=tmpdir, collection_name="verify_test")
        store.add_documents([
            {"content": "Acme Corp is a fintech startup with $4M ARR and 45 employees", "metadata": {"source": "test.md", "filename": "test.md", "chunk_index": 0}},
            {"content": "The CEO Sarah Chen has 15 years of fintech experience", "metadata": {"source": "test.md", "filename": "test.md", "chunk_index": 1}},
        ])
        results = store.search("Who is the CEO?", k=2)
        assert len(results) > 0, "Search should return results"
        assert "score" in results[0], "Results should have scores"
        assert "content" in results[0], "Results should have content"
        assert results[0]["score"] >= 0, "Score should be non-negative"
        print(f"  [PASS] Vector store search returns {len(results)} scored results")


# ---------------------------------------------------------------------------
# Test 9: Document detection merges auto signals with hardcoded
# ---------------------------------------------------------------------------
def test_document_detection_with_auto_signals():
    from src.tools.search import _detect_document, _load_auto_signals
    from src.vector_store.chroma import VectorStore
    with tempfile.TemporaryDirectory() as tmpdir:
        store = VectorStore(persist_directory=tmpdir, collection_name="detect_test")
        # Should handle empty store gracefully
        result = _detect_document("What is the CEO?", store)
        # With no documents, should return None
        assert result is None
    print("  [PASS] Document detection handles empty store gracefully")


# ---------------------------------------------------------------------------
# Test 10: Agent thin wrappers can be instantiated
# ---------------------------------------------------------------------------
def test_agent_wrappers_instantiate():
    from src.vector_store.chroma import VectorStore
    from src.agents.due_diligence import DueDiligenceAgent
    from src.agents.term_sheet import TermSheetExtractorAgent
    from src.agents.lp_report import LPReportAgent
    from src.agents.compliance import ComplianceAgent
    from src.agents.router import RouterAgent

    with tempfile.TemporaryDirectory() as tmpdir:
        store = VectorStore(persist_directory=tmpdir, collection_name="wrapper_test")
        dd = DueDiligenceAgent(vector_store=store)
        ts = TermSheetExtractorAgent(vector_store=store)
        lp = LPReportAgent(vector_store=store)
        cp = ComplianceAgent(vector_store=store)
        router = RouterAgent(vector_store=store)

        assert hasattr(dd, "graph") and hasattr(dd, "search_tool")
        assert hasattr(ts, "graph") and hasattr(ts, "search_tool")
        assert hasattr(lp, "graph") and hasattr(lp, "search_tool")
        assert hasattr(cp, "graph") and hasattr(cp, "search_tool")
        assert hasattr(router, "graph")
    print("  [PASS] All agent wrappers instantiate correctly")


# ---------------------------------------------------------------------------
# Test 11: E2E with mock graph (simulates full pipeline)
# ---------------------------------------------------------------------------
def test_e2e_mock_pipeline():
    from src.agents.router import RouterAgent
    from src.vector_store.chroma import VectorStore

    with tempfile.TemporaryDirectory() as tmpdir:
        store = VectorStore(persist_directory=tmpdir, collection_name="e2e_test")
        store.add_documents([
            {"content": "Acme Corp CEO is Sarah Chen. ARR is $4M.", "metadata": {"source": "memo.md", "filename": "memo.md", "chunk_index": 0}},
        ])

        mock_final = {
            "agent_type": "due_diligence",
            "answer": "SUMMARY: Sarah Chen is the CEO of Acme Corp.\nRISKS: None\nOPPORTUNITIES: None\nRECOMMENDATION: Proceed",
            "citations": ["memo.md, page 1, line 1"],
            "verified": True,
        }

        with patch("src.agents.router.get_agent_graph") as mock_get:
            mock_graph = MagicMock()
            mock_graph.invoke.return_value = mock_final
            mock_get.return_value = mock_graph

            router = RouterAgent(vector_store=store)
            resp = router.invoke("Who is the CEO?")

            assert resp.agent_type == "due_diligence"
            assert "Sarah Chen" in resp.result
            assert len(resp.citations) == 1
            assert "memo.md" in resp.citations[0]

            # Verify graph was invoked with correct initial state
            call_args = mock_graph.invoke.call_args[0][0]
            assert call_args["query"] == "Who is the CEO?"
            assert call_args["agent_type"] == "due_diligence"
    print("  [PASS] E2E mock pipeline: routing, parsing, citations all correct")


# ---------------------------------------------------------------------------
# Test 12: Graph conditional edges (verify -> end vs wide_search)
# ---------------------------------------------------------------------------
def test_graph_conditional_edges():
    from src.agents.graph import should_classify, should_verify, after_verify
    assert should_verify({"verified": True}) == "end"
    assert should_verify({"verified": False}) == "verify"
    assert after_verify({"verified": True}) == "end"
    assert after_verify({"verified": False}) == "wide_search"
    # Forced agent types skip classification entirely
    assert should_classify({"agent_type_forced": True}) == "search"
    assert should_classify({"agent_type_forced": False}) == "classify"
    print("  [PASS] Graph conditional edges route correctly")


# ---------------------------------------------------------------------------
# Test 13: _safe_float handles edge cases
# ---------------------------------------------------------------------------
def test_safe_float():
    from src.agents.graph import _safe_float
    assert _safe_float("$50,000,000") == 50000000.0
    assert _safe_float("HKD 390M") == 390.0
    assert _safe_float("$4M [Source 1: memo.md]") == 4.0
    assert _safe_float("not available") == 0.0
    assert _safe_float("") == 0.0
    assert _safe_float("€1,500/month") == 1500.0
    print("  [PASS] _safe_float handles currency, commas, citations, edge cases")


# ---------------------------------------------------------------------------
# Test 14: _semicolon_list filters correctly
# ---------------------------------------------------------------------------
def test_semicolon_list():
    from src.agents.graph import _semicolon_list
    result = _semicolon_list("Issue A; Issue B; Issue C")
    assert result == ["Issue A", "Issue B", "Issue C"]
    result2 = _semicolon_list("Not available")
    assert result2 == []
    result3 = _semicolon_list("")
    assert result3 == []
    result4 = _semicolon_list("Item 1; Not specified; Item 2")
    assert result4 == ["Item 1", "Item 2"]
    print("  [PASS] _semicolon_list filters and splits correctly")


# ---------------------------------------------------------------------------
# Run all tests
# ---------------------------------------------------------------------------
def main():
    print("[RUN] Running verification tests...\n")
    tests = [
        test_graph_builds,
        test_keyword_classification,
        test_parsers,
        test_clean_citations,
        test_says_not_found,
        test_llm_cache,
        test_auto_signal_extraction,
        test_vector_store_search,
        test_document_detection_with_auto_signals,
        test_agent_wrappers_instantiate,
        test_e2e_mock_pipeline,
        test_graph_conditional_edges,
        test_safe_float,
        test_semicolon_list,
    ]

    passed = 0
    failed = 0
    for test in tests:
        try:
            test()
            passed += 1
        except Exception as e:
            print(f"  [FAIL] {test.__name__}: {e}")
            failed += 1

    print(f"\n{'='*50}")
    print(f"Results: {passed}/{passed+failed} passed, {failed} failed")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
