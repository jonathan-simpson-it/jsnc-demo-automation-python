"""Pydantic models for Private Equity domain entities."""

from pydantic import BaseModel, Field

from src.core.constants import DocumentType, RiskLevel


class PEDocument(BaseModel):
    """A document in the PE knowledge base."""

    content: str
    metadata: dict = Field(default_factory=dict)
    doc_type: DocumentType


class DueDiligenceResult(BaseModel):
    """Result from due diligence analysis."""

    summary: str
    risks: list[str] = Field(default_factory=list)
    opportunities: list[str] = Field(default_factory=list)
    recommendation: str
    confidence_score: float = Field(ge=0.0, le=1.0, default=0.8)


class TermSheetData(BaseModel):
    """Structured data extracted from a term sheet."""

    company_name: str
    round_type: str
    pre_money_valuation: float
    investment_amount: float
    liquidation_preference: str
    anti_dilution: str
    board_seats: str
    price_per_share: str = Field(default="Not specified")
    shares_issued: str = Field(default="Not specified")
    esop_pool: str = Field(default="Not specified")
    esop_refresh: str = Field(default="Not specified")
    founder_ownership_post: str = Field(default="Not specified")
    protective_provisions: list[str] = Field(default_factory=list)
    information_rights: list[str] = Field(default_factory=list)
    exclusivity: str = Field(default="Not specified")
    governing_law: str = Field(default="Not specified")
    dispute_resolution: str = Field(default="Not specified")
    key_person_insurance: str = Field(default="Not specified")
    lead_investor: str = Field(default="Not specified")
    key_terms: dict = Field(default_factory=dict)


class LPReport(BaseModel):
    """Quarterly LP report data."""

    quarter: str
    portfolio_highlights: list[str] = Field(default_factory=list)
    financial_summary: dict = Field(default_factory=dict)
    risk_factors: list[str] = Field(default_factory=list)


class ComplianceCheck(BaseModel):
    """Compliance check result for a document."""

    document_name: str
    compliant: bool
    issues: list[str] = Field(default_factory=list)
    jurisdiction: str
    regulations_checked: list[str] = Field(default_factory=list)


class CrossDocComparison(BaseModel):
    """Cross-document comparison result."""

    query: str = Field(default="")
    synthesis: str
    documents_compared: list[str] = Field(default_factory=list)
    key_differences: list[str] = Field(default_factory=list)
    key_similarities: list[str] = Field(default_factory=list)


class AgentQuery(BaseModel):
    """Input query for agent execution."""

    query: str
    agent_type: str | None = Field(
        default=None, description="Force agent (None = auto-route)"
    )
    document_ids: list[str] = Field(default_factory=list)
    tagged_filenames: list[str] = Field(
        default_factory=list,
        description="Exact document filenames (resolved from @-mentions) to "
        "restrict retrieval to. Intersected with the conversation's project "
        "scope so tagging can never cross project boundaries.",
    )
    project_id: int | None = Field(
        default=None,
        description="Requested project scope; must match the conversation's "
        "project when conversation_id is set",
    )
    conversation_id: int | None = Field(
        default=None,
        description="Persist this turn into the conversation and scope retrieval "
        "to the conversation's project",
    )


class AgentResponse(BaseModel):
    """Response from agent execution."""

    agent_type: str
    result: str
    metadata: dict = Field(default_factory=dict)
    citations: list[str] = Field(default_factory=list)
    confidence_score: float = Field(ge=0.0, le=1.0, default=0.8)


class ConversationCreate(BaseModel):
    """Create a chat conversation (project_id None = Global workspace)."""

    project_id: int | None = None
    title: str | None = None


class ConversationOut(BaseModel):
    """A chat conversation summary."""

    id: int
    project_id: int | None
    title: str
    message_count: int = 0
    last_message: str | None = None
    created_at: str | None = None
    updated_at: str | None = None


class ConversationMessageOut(BaseModel):
    """A persisted chat message."""

    id: int
    conversation_id: int
    role: str
    content: str
    agent_type: str | None = None
    citations: list[str] = Field(default_factory=list)
    trace: list = Field(default_factory=list)
    confidence: float | None = None
    is_error: bool = False
    created_at: str | None = None
