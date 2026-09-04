"""Regulatory Radar: daily polling + manual cycle.

State is module-level (single process). The loop never raises: network or
parse failures are recorded in _state and the cycle continues.
"""

import asyncio
import logging

from config.settings import settings
from src.core import database as db
from src.regulatory import client
from src.regulatory.ingest import ingest_regulatory_item
from src.regulatory.sources import SOURCES

logger = logging.getLogger(__name__)

_state = {"last_run": None, "last_status": "idle", "last_error": None, "running": False}


def get_state() -> dict:
    return dict(_state)


def _get_store():
    """Resolve the live vector store lazily (monkeypatched in tests)."""
    from src.api.deps import get_vector_store

    return get_vector_store()


def _try_ingest(item, source, store=None):
    """Fetch + ingest one item; returns status + summary. Never raises."""
    text = client.fetch_item_text(item["url"], source)
    result = ingest_regulatory_item(
        item, source, text, vector_store=store
    )
    feed = db.upsert_regulatory_item(
        source_key=source.key,
        external_id=item["external_id"],
        regulator=source.regulator,
        kind=item.get("kind") or source.kind,
        title=item["title"],
        url=item["url"],
        issued_at=item.get("issued_at"),
    )
    db.update_regulatory_item_status(
        feed["id"],
        "ingested",
        chunks=result["chunks"],
        summary=result["summary"],
    )
    return result


def poll_cycle(store=None) -> dict:
    """One full pass over every source. Idempotent per (source, external_id)."""
    _state["running"] = True
    _state["last_error"] = None
    if store is None:
        try:
            store = _get_store()
        except Exception:
            store = None  # ingest metadata/feed only; vectors optional offline
    try:
        for source in SOURCES:
            if source.fixture_only:
                continue  # never inject fixture data into the live feed
            items = client.fetch_listing(source)
            for item in items:
                if db.get_regulatory_item(source.key, item["external_id"]):
                    continue  # already ingested
                try:
                    _try_ingest(item, source, store)
                except Exception as exc:  # per-item failure -> error row
                    logger.warning("regulatory ingest failed for %s: %s",
                                   item.get("title"), exc)
                    feed = db.upsert_regulatory_item(
                        source_key=source.key,
                        external_id=item["external_id"],
                        regulator=source.regulator,
                        kind=item.get("kind") or source.kind,
                        title=item["title"],
                        url=item["url"],
                        issued_at=item.get("issued_at"),
                    )
                    db.update_regulatory_item_status(feed["id"], "error")
                    _state["last_error"] = str(exc)
        _state["last_status"] = "ok"
    except Exception as exc:  # whole-cycle failure (e.g. all listings down)
        _state["last_status"] = "error"
        _state["last_error"] = str(exc)
    finally:
        _state["running"] = False
        _state["last_run"] = __import__("datetime").datetime.now().isoformat()
    return get_state()


async def poll_loop() -> None:
    """Background loop: one pass immediately, then sleep(regulatory_poll_hours)."""
    while True:
        try:
            poll_cycle()
        except Exception as exc:  # belt & braces — never kill the task
            _state["last_status"] = "error"
            _state["last_error"] = str(exc)
        await asyncio.sleep(settings.regulatory_poll_hours * 3600)
