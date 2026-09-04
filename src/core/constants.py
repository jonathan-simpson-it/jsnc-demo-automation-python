"""Enums and constants for PE domain."""

from enum import Enum


class DocumentType(str, Enum):
    """Types of documents in the PE knowledge base."""

    INVESTMENT_MEMO = "investment_memo"
    TERM_SHEET = "term_sheet"
    FINANCIAL_MODEL = "financial_model"
    PORTFOLIO_REPORT = "portfolio_report"
    COMPLIANCE_DOC = "compliance_doc"
    LEGAL_AGREEMENT = "legal_agreement"


class RiskLevel(str, Enum):
    """Risk severity levels for compliance and due diligence."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class AgentType(str, Enum):
    """Types of specialist agents."""

    DUE_DILIGENCE = "due_diligence"
    TERM_SHEET = "term_sheet"
    LP_REPORT = "lp_report"
    COMPLIANCE = "compliance"
    CROSS_DOC = "cross_doc"


class Currency(str, Enum):
    """Supported currencies for multi-currency handling."""

    HKD = "HKD"
    USD = "USD"
    CNY = "CNY"
    EUR = "EUR"
    GBP = "GBP"
    JPY = "JPY"
    SGD = "SGD"

    @property
    def symbol(self) -> str:
        symbols = {"HKD": "HK$", "USD": "$", "CNY": "¥", "EUR": "€", "GBP": "£", "JPY": "¥", "SGD": "S$"}
        return symbols.get(self.value, self.value)


class Jurisdiction(str, Enum):
    """Supported jurisdictions for regulatory mapping."""

    HONG_KONG = "hong_kong"
    SINGAPORE = "singapore"
    MAINLAND_CHINA = "mainland_china"
    UNITED_STATES = "united_states"
    UNITED_KINGDOM = "united_kingdom"


# Jurisdiction → applicable regulations
_JURISDICTION_REGULATIONS: dict[Jurisdiction, list[str]] = {
    Jurisdiction.HONG_KONG: ["SFC", "AMLO", "HKMA", "Companies Ordinance"],
    Jurisdiction.SINGAPORE: ["MAS", "SFA", "PDPA"],
    Jurisdiction.MAINLAND_CHINA: ["CSRC", "SAFE", "PBOC"],
    Jurisdiction.UNITED_STATES: ["SEC", "FINRA", "BSA"],
    Jurisdiction.UNITED_KINGDOM: ["FCA", "PRA", "MLR"],
}


def get_jurisdiction_regulations(jurisdiction: Jurisdiction) -> list[str]:
    """Get applicable regulations for a jurisdiction."""
    return _JURISDICTION_REGULATIONS.get(jurisdiction, [])
