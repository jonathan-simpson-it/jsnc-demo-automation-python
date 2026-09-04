"""Human-in-the-loop review endpoints."""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from src.core import database as db

router = APIRouter()


class ApproveBody(BaseModel):
    answer: str | None = None


@router.get("/queue")
async def review_queue(status: str = "pending") -> dict:
    """List review items, newest first (default: pending only)."""
    items = db.list_review_items(status=status)
    return {"items": items}


@router.post("/{review_id}/approve")
async def approve_review(review_id: int, body: ApproveBody) -> dict:
    """Approve a pending answer (optionally replacing it with an edited one).

    The final text is appended to the review item's conversation (when it has
    one) so approved answers show up in chat history.
    """
    item = db.get_review_item(review_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Review item not found")

    edited = bool(body.answer)
    status = "edited" if edited else "approved"
    db.set_review_status(review_id, status, edited_answer=body.answer)

    final_text = body.answer if edited else item["draft_answer"]
    if item.get("conversation_id"):
        db.add_message(
            item["conversation_id"],
            "assistant",
            final_text,
            agent_type=item.get("agent_type"),
            citations=item.get("citations") or [],
            trace=item.get("trace") or [],
            confidence=item.get("confidence"),
            is_error=False,
        )
    return {"id": review_id, "status": status}


@router.post("/{review_id}/reject")
async def reject_review(review_id: int) -> dict:
    """Reject a pending answer; nothing is added to the conversation."""
    item = db.get_review_item(review_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Review item not found")
    db.set_review_status(review_id, "rejected")
    return {"id": review_id, "status": "rejected"}
