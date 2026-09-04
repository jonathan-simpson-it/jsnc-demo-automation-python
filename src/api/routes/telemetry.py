"""Telemetry endpoints: recent pipeline runs + LLM cost analytics."""

from fastapi import APIRouter

from src.utils.cost_tracker import cost_tracker
from src.utils.telemetry import run_log

router = APIRouter()


@router.get("/runs")
async def get_runs() -> dict:
    """Most recent completed agent runs (newest last)."""
    return {"runs": run_log.all()}


@router.get("/cost")
async def get_cost() -> dict:
    """Token/cost summary across all recorded LLM calls."""
    return cost_tracker.get_summary()


@router.post("/reset")
async def reset_telemetry() -> dict:
    """Reset cost totals and the run log."""
    cost_tracker.reset()
    run_log.reset()
    return {"reset": True}
