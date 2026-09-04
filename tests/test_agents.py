"""Tests for LangGraph agents."""

import tempfile
from unittest.mock import MagicMock, patch

from src.agents.due_diligence import DueDiligenceAgent
from src.vector_store.chroma import VectorStore


def _setup_vector_store(tmpdir: str) -> VectorStore:
    """Set up a test vector store."""
    store = VectorStore(persist_directory=tmpdir, collection_name="test_agents")
    chunks = [
        {
            "content": "Acme Corp has strong growth but faces regulatory risk in Hong Kong.",
            "metadata": {"source": "memo.md", "chunk_index": 0},
            "doc_type": "investment_memo",
        },
    ]
    store.add_documents(chunks)
    return store


def test_due_diligence_agent_creation():
    """Test that DueDiligenceAgent can be created."""
    with tempfile.TemporaryDirectory() as tmpdir:
        store = _setup_vector_store(tmpdir)
        agent = DueDiligenceAgent(vector_store=store, api_key="test-key")
        assert agent is not None


def test_due_diligence_agent_returns_result():
    """Test that agent returns a DueDiligenceResult."""
    with tempfile.TemporaryDirectory() as tmpdir:
        store = _setup_vector_store(tmpdir)

        # Mock the graph invoke to return a pre-canned state
        mock_final_state = {
            "agent_type": "due_diligence",
            "answer": """SUMMARY: Strong growth with regulatory risks.
RISKS:
- Regulatory uncertainty
- Customer concentration
OPPORTUNITIES:
- Market expansion
- Strong IP
RECOMMENDATION: Proceed with caution""",
            "citations": ["memo.md, page 1, line 1"],
            "verified": True,
        }

        with patch("src.agents.due_diligence.get_agent_graph") as mock_get_graph:
            mock_graph = MagicMock()
            mock_graph.invoke.return_value = mock_final_state
            mock_get_graph.return_value = mock_graph

            agent = DueDiligenceAgent(vector_store=store, api_key="test-key")
            result = agent.invoke("Analyze Acme Corp for due diligence")
            assert result is not None
            assert hasattr(result, "summary")
            assert hasattr(result, "risks")


def test_term_sheet_extractor_creation():
    """Test that TermSheetExtractorAgent can be created."""
    from src.agents.term_sheet import TermSheetExtractorAgent

    with tempfile.TemporaryDirectory() as tmpdir:
        store = _setup_vector_store(tmpdir)
        agent = TermSheetExtractorAgent(vector_store=store, api_key="test-key")
        assert agent is not None


def test_term_sheet_extractor_extracts_data():
    """Test that extractor returns TermSheetData."""
    from src.agents.term_sheet import TermSheetExtractorAgent

    with tempfile.TemporaryDirectory() as tmpdir:
        store = _setup_vector_store(tmpdir)

        mock_final_state = {
            "agent_type": "term_sheet",
            "answer": """COMPANY_NAME: Acme Corp
ROUND_TYPE: Series A
PRE_MONEY_VALUATION: 50000000
INVESTMENT_AMOUNT: 10000000
LIQUIDATION_PREFERENCE: 1x non-participating
ANTI_DILUTION: Broad-based weighted average
BOARD_SEATS: 2 investor, 2 founder, 1 independent""",
            "citations": [],
            "verified": True,
        }

        with patch("src.agents.term_sheet.get_agent_graph") as mock_get_graph:
            mock_graph = MagicMock()
            mock_graph.invoke.return_value = mock_final_state
            mock_get_graph.return_value = mock_graph

            agent = TermSheetExtractorAgent(vector_store=store, api_key="test-key")
            result = agent.invoke("Extract term sheet data for Acme Corp")
            assert result is not None
            assert hasattr(result, "company_name")
            assert result.company_name == "Acme Corp"


def test_lp_report_agent_creation():
    """Test that LPReportAgent can be created."""
    from src.agents.lp_report import LPReportAgent

    with tempfile.TemporaryDirectory() as tmpdir:
        store = _setup_vector_store(tmpdir)
        agent = LPReportAgent(vector_store=store, api_key="test-key")
        assert agent is not None


def test_lp_report_agent_generates_report():
    """Test that agent generates LP report."""
    from src.agents.lp_report import LPReportAgent

    with tempfile.TemporaryDirectory() as tmpdir:
        store = _setup_vector_store(tmpdir)

        mock_final_state = {
            "agent_type": "lp_report",
            "answer": """QUARTER: Q1 2026
HIGHLIGHTS: Acme Corp achieved 120% YoY growth; Portfolio company Beta closed Series B
FINANCIAL_SUMMARY: total_aum: 150000000; realized_returns: 12000000
RISK_FACTORS: Market volatility; Interest rate uncertainty""",
            "citations": [],
            "verified": True,
        }

        with patch("src.agents.lp_report.get_agent_graph") as mock_get_graph:
            mock_graph = MagicMock()
            mock_graph.invoke.return_value = mock_final_state
            mock_get_graph.return_value = mock_graph

            agent = LPReportAgent(vector_store=store, api_key="test-key")
            result = agent.invoke("Generate Q1 2026 LP report")
            assert result is not None
            assert hasattr(result, "quarter")
            assert result.quarter == "Q1 2026"


def test_compliance_agent_creation():
    """Test that ComplianceAgent can be created."""
    from src.agents.compliance import ComplianceAgent

    with tempfile.TemporaryDirectory() as tmpdir:
        store = _setup_vector_store(tmpdir)
        agent = ComplianceAgent(vector_store=store, api_key="test-key")
        assert agent is not None


def test_compliance_agent_checks_document():
    """Test that compliance agent checks a document."""
    from src.agents.compliance import ComplianceAgent

    with tempfile.TemporaryDirectory() as tmpdir:
        store = _setup_vector_store(tmpdir)

        mock_final_state = {
            "agent_type": "compliance",
            "answer": """DOCUMENT_NAME: Term Sheet - Acme Corp
COMPLIANT: true
ISSUES: None
JURISDICTION: Hong Kong SAR
REGULATIONS_CHECKED: SFC Guidelines; AMLO""",
            "citations": [],
            "verified": True,
        }

        with patch("src.agents.compliance.get_agent_graph") as mock_get_graph:
            mock_graph = MagicMock()
            mock_graph.invoke.return_value = mock_final_state
            mock_get_graph.return_value = mock_graph

            agent = ComplianceAgent(vector_store=store, api_key="test-key")
            result = agent.invoke("Check compliance of Acme Corp term sheet")
            assert result is not None
            assert hasattr(result, "compliant")
            assert result.compliant is True


def test_router_agent_creation():
    """Test that RouterAgent can be created."""
    from src.agents.router import RouterAgent

    with tempfile.TemporaryDirectory() as tmpdir:
        store = _setup_vector_store(tmpdir)
        agent = RouterAgent(vector_store=store, api_key="test-key")
        assert agent is not None
        assert hasattr(agent, "graph")
        assert hasattr(agent, "vector_store")


def test_router_routes_to_correct_agent():
    """Test that router dispatches to the correct agent via graph."""
    from src.agents.router import RouterAgent

    with tempfile.TemporaryDirectory() as tmpdir:
        store = _setup_vector_store(tmpdir)

        mock_final_state = {
            "agent_type": "due_diligence",
            "answer": "SUMMARY: Analysis completed\nRECOMMENDATION: Further analysis needed",
            "citations": [],
            "verified": True,
        }

        with patch("src.agents.router.get_agent_graph") as mock_get_graph:
            mock_graph = MagicMock()
            mock_graph.invoke.return_value = mock_final_state
            mock_get_graph.return_value = mock_graph

            router = RouterAgent(vector_store=store, api_key="test-key")
            response = router.invoke("Analyze Acme Corp for investment")
            assert response.agent_type == "due_diligence"
            assert "summary" in response.result.lower() or "analysis" in response.result.lower()


def test_dd_parser_keeps_freeform_answers():
    """Regression: verify/wide_search rescue answers have no section headers.

    The parser previously returned its "Analysis completed" fallback for such
    answers, silently dropping the rescued content.
    """
    from src.agents.graph import _parse_due_diligence

    text = ("Based on the retrieved documents, the candidate's current role at "
            "Archbridge Capital Partners is **AI Engineer (Part-time)** "
            "[Source 5: cv-jonathandevano-hkma.pdf, page 1, line 14].")
    parsed = _parse_due_diligence(text)
    assert "AI Engineer (Part-time)" in parsed["summary"]
    assert "[Source" not in parsed["summary"]  # citations stripped
    assert "Analysis completed" != parsed["summary"]


def test_answer_content_validation():
    """Regression: empty and citation-only responses are not usable answers."""
    from src.agents.graph import _answer_ok, _has_content

    assert not _has_content("")
    assert not _has_content("   ")
    assert not _has_content("[Source 2: memo.md, page 1, line 3]")
    assert _has_content("Sarah Chen is the CEO [Source 2: memo.md, page 1, line 3]")
    assert _answer_ok("Sarah Chen is the CEO of Acme Corp.")
    assert not _answer_ok("[Source 2: memo.md, page 1, line 3]")
    assert not _answer_ok("The documents do not contain this information")
