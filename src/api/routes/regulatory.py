"""Regulatory Radar API endpoints."""

from datetime import datetime

from fastapi import APIRouter

from src.core import database as db
from src.regulatory import scheduler

router = APIRouter()

# Per-section limit. The SFC hub sections (News / Policy statements / High
# shareholding / Events) each keep their own newest items so slower-moving
# sections stay visible; the radar shows SFC grouped by section.
FEED_PER_SECTION = 10

# SFC hub sections in display order. When the same refNo appears under several
# kinds (SFC posts most things into "all news" too), prefer the specific one.
SFC_SECTIONS = [
    "news",
    "policy statement",
    "high shareholding",
    "event",
]
_KIND_PRIORITY = {
    "high shareholding": 6,
    "policy statement": 5,
    "event": 4,
    "decision": 4,
    "corporate news": 3,
    "enforcement news": 3,
    "news": 2,
    "press release": 1,
    "speech": 1,
    "insight": 1,
    "circular": 0,
}


def _date_sort_key(issued_at: str | None):
    if not issued_at:
        return datetime.min
    value = issued_at.strip()
    for fmt in ("%Y-%m-%d", "%d %b %Y", "%d %B %Y"):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    return datetime.min


def _dedupe(items: list[dict]) -> list[dict]:
    """Collapse the same (regulator, external id) into the most specific kind."""
    best: dict[tuple[str, str], dict] = {}
    for item in items:
        key = (item.get("regulator") or "", item.get("external_id") or "")
        if not key[0] or not key[1]:
            continue
        priority = _KIND_PRIORITY.get((item.get("kind") or "").lower(), 0)
        existing = best.get(key)
        if existing is None or priority > _KIND_PRIORITY.get(
            (existing.get("kind") or "").lower(), 0
        ):
            best[key] = item
    return list(best.values())


def _newest(items: list[dict], limit: int = FEED_PER_SECTION) -> list[dict]:
    return sorted(
        items, key=lambda it: _date_sort_key(it.get("issued_at")), reverse=True
    )[:limit]


def _sfc_by_section(items: list[dict]) -> list[dict]:
    """SFC feed grouped by hub section, each section newest-first."""
    deduped = _dedupe(items)
    by_kind: dict[str, list[dict]] = {}
    for item in deduped:
        kind = (item.get("kind") or "").lower()
        by_kind.setdefault(kind, []).append(item)
    result: list[dict] = []
    for kind in SFC_SECTIONS:
        if kind in by_kind:
            result.extend(_newest(by_kind[kind]))
    leftovers = [
        item for item in deduped
        if (item.get("kind") or "").lower() not in SFC_SECTIONS
    ]
    result.extend(_newest(leftovers))
    return result


@router.post("/poll")
async def poll_now() -> dict:
    """Run one fetch + ingest cycle on demand."""
    return scheduler.poll_cycle()


@router.get("/status")
async def radar_status() -> dict:
    return scheduler.get_state()


@router.get("/feed")
async def radar_feed() -> dict:
    """Feed: newest items per regulator (SFC grouped by hub section)."""
    items = db.list_regulatory_items(limit=2000)
    by_regulator: dict[str, list[dict]] = {}
    for item in items:
        by_regulator.setdefault(item.get("regulator") or "Other", []).append(item)
    result: list[dict] = []
    for regulator, regulator_items in by_regulator.items():
        if regulator == "SFC":
            result.extend(_sfc_by_section(regulator_items))
        else:
            result.extend(_newest(_dedupe(regulator_items)))
    return {"items": result}
