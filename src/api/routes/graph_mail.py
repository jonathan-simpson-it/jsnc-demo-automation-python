"""Microsoft Graph mail endpoints (read mailbox, create drafts)."""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from src import graph_mail
from src.compliance.summary import SummaryGenerator
from src.email_composer import REPLY_INTENTS, compose_draft, compose_reply

router = APIRouter()

_CONTENT_TYPES = ("text", "html")


class DraftRequest(BaseModel):
    subject: str
    body: str
    to: list[str] = []
    content_type: str = "text"


class DraftGenerateRequest(BaseModel):
    period: str = "week"
    template: str = "digest"
    tone: str = "professional"
    instructions: str = ""
    to: list[str] = []


class ReplyGenerateRequest(BaseModel):
    sender_name: str = ""
    sender_email: str = ""
    subject: str = ""
    body: str = ""
    intent: str = "acknowledge"
    instructions: str = ""


@router.get("/status")
async def mail_status() -> dict:
    """Whether mailbox access is configured and resolvable."""
    return graph_mail.status()


@router.get("/messages")
async def list_messages(limit: int = 50) -> dict:
    """List the newest messages from the target mailbox (demo when unset)."""
    try:
        return {"emails": graph_mail.list_messages(limit=limit)}
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Graph mail error: {exc}")


@router.get("/drafts")
async def list_drafts(limit: int = 20) -> dict:
    """List drafts saved through this workspace (demo store or Graph)."""
    try:
        return {"drafts": graph_mail.list_drafts(limit=limit)}
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Graph mail error: {exc}")


@router.post("/drafts")
async def create_draft(req: DraftRequest) -> dict:
    """Create a draft message from the current report."""
    if not req.subject.strip():
        raise HTTPException(status_code=400, detail="subject is required")
    if req.content_type not in _CONTENT_TYPES:
        raise HTTPException(
            status_code=400, detail="content_type must be 'text' or 'html'"
        )
    try:
        return graph_mail.create_draft(
            req.subject, req.body, to=req.to, content_type=req.content_type
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Graph mail error: {exc}")


@router.post("/reply/generate")
async def generate_reply(req: ReplyGenerateRequest) -> dict:
    """Generate an AI reply to an incoming email (template fallback)."""
    if req.intent not in REPLY_INTENTS:
        raise HTTPException(
            status_code=400,
            detail=f"intent must be one of {', '.join(REPLY_INTENTS)}",
        )
    try:
        draft = compose_reply(
            sender_name=req.sender_name,
            sender_email=req.sender_email,
            subject=req.subject,
            body=req.body,
            intent=req.intent,
            instructions=req.instructions,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"compose failed: {exc}")
    return {
        **draft,
        "to": [req.sender_email] if req.sender_email else [],
    }


@router.post("/draft/generate")
async def generate_draft(req: DraftGenerateRequest) -> dict:
    """Generate an email draft from the platform report (AI or template)."""
    if req.period not in ("week", "month"):
        raise HTTPException(status_code=400, detail="period must be week or month")
    try:
        summary = SummaryGenerator().generate(period=req.period)
        draft = compose_draft(
            summary,
            template_key=req.template,
            tone=req.tone,
            instructions=req.instructions,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"compose failed: {exc}")
    return {
        "subject": draft["subject"],
        "body": draft["body"],
        "to": req.to,
        "generated_by": draft["generated_by"],
        "period": req.period,
    }
