"""Summary endpoint — email-ready reports from audit trail."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from src.compliance.summary import SummaryGenerator

router = APIRouter()


class SummaryRequest(BaseModel):
    period: str = "week"  # "week" or "month"


@router.post("")
async def generate_summary(req: SummaryRequest):
    """Generate an email-ready summary of system activity.

    Args:
        period: "week" (last 7 days) or "month" (last 30 days).

    Returns:
        Summary with metrics, breakdowns, top queries, and email markdown.
    """
    if req.period not in ("week", "month"):
        raise HTTPException(
            status_code=400,
            detail="period must be 'week' or 'month'",
        )

    try:
        gen = SummaryGenerator()
        return gen.generate(period=req.period)
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Summary generation failed: {str(e)}",
        )
