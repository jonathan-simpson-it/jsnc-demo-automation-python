"""Tests for PE data models."""

from src.core.models import (
    PEDocument,
    DueDiligenceResult,
    TermSheetData,
    LPReport,
    ComplianceCheck,
)
from src.core.constants import DocumentType, RiskLevel


def test_pe_document_creation():
    """Test PEDocument model creation with required fields."""
    doc = PEDocument(
        content="Investment memo for Series A round",
        metadata={"source": "investment_memo.pdf", "page": 1},
        doc_type=DocumentType.INVESTMENT_MEMO,
    )
    assert doc.content == "Investment memo for Series A round"
    assert doc.doc_type == DocumentType.INVESTMENT_MEMO
    assert doc.metadata["source"] == "investment_memo.pdf"


def test_due_diligence_result_creation():
    """Test DueDiligenceResult model creation."""
    result = DueDiligenceResult(
        summary="Strong growth trajectory with 40% YoY revenue increase",
        risks=["High customer concentration", "Regulatory uncertainty"],
        opportunities=["Market expansion potential", "Strong IP portfolio"],
        recommendation="Proceed with investment",
    )
    assert len(result.risks) == 2
    assert result.recommendation == "Proceed with investment"


def test_term_sheet_data_extraction():
    """Test TermSheetData model for structured extraction."""
    term_sheet = TermSheetData(
        company_name="Acme Corp",
        round_type="Series A",
        pre_money_valuation=50_000_000,
        investment_amount=10_000_000,
        liquidation_preference="1x non-participating",
        anti_dilution="Broad-based weighted average",
        board_seats="2 investor, 2 founder, 1 independent",
    )
    assert term_sheet.pre_money_valuation == 50_000_000
    assert term_sheet.round_type == "Series A"


def test_lp_report_creation():
    """Test LPReport model for quarterly reporting."""
    report = LPReport(
        quarter="Q1 2026",
        portfolio_highlights=["Company A achieved $10M ARR", "Company B closed Series B"],
        financial_summary={"total_aum": 150_000_000, "realized_returns": 12_000_000},
        risk_factors=["Market volatility", "Interest rate uncertainty"],
    )
    assert report.quarter == "Q1 2026"
    assert report.financial_summary["total_aum"] == 150_000_000


def test_compliance_check_creation():
    """Test ComplianceCheck model for regulatory compliance."""
    check = ComplianceCheck(
        document_name="Term Sheet - Acme Corp",
        compliant=True,
        issues=[],
        jurisdiction="Hong Kong SAR",
        regulations_checked=["SFC Guidelines", "AMLO"],
    )
    assert check.compliant is True
    assert check.jurisdiction == "Hong Kong SAR"
