"""Tests for regulatory ingestion chunking/metadata.

Sandbox note: requires the project venv/CI (pytest; langchain imports).
"""

from src.regulatory.ingest import build_chunks, ingest_regulatory_item
from src.regulatory.sources import SOURCES

SFC = next(s for s in SOURCES if s.key == "sfc_circulars")

ITEM = {
    "external_id": "licensing-of-virtual-asset-trading-platforms",
    "title": "Licensing of Virtual Asset Trading Platforms",
    "url": "https://www.sfc.hk/en/circulars/licensing-vasp-2026",
    "issued_at": "16 Oct 2026",
}

TEXT = ("Licensed corporations must conduct customer due diligence. " * 40) + "End."


class _FakeStore:
    def __init__(self):
        self.added = []

    def add_documents(self, chunks, filename=None):
        self.added.append((chunks, filename))


def test_build_chunks_metadata():
    chunks = build_chunks(ITEM, SFC, TEXT)
    assert chunks
    first = chunks[0]["metadata"]
    assert first["filename"] == f"reg-sfc-{ITEM['external_id']}.txt"
    assert first["regulator"] == "SFC"
    assert first["issuance_date"] == "16 Oct 2026"
    assert first["circular_id"] == ITEM["external_id"]
    assert first["category"] == "circular"
    import json as _json

    assert "sfc" in _json.loads(first["auto_positive_signals"])


def test_ingest_regulatory_item_stores_collection():
    store = _FakeStore()
    result = ingest_regulatory_item(ITEM, SFC, TEXT, vector_store=store)
    assert result["chunks"] >= 1
    assert store.added and store.added[0][1] == result["filename"]


def test_summarizer_hook_and_failure_tolerance():
    store = _FakeStore()
    ok = ingest_regulatory_item(
        ITEM, SFC, TEXT, vector_store=store, summarize_with=lambda t: "Impact."
    )
    assert ok["summary"] == "Impact."

    def boom(_t):
        raise RuntimeError("llm offline")

    safe = ingest_regulatory_item(
        ITEM, SFC, TEXT, vector_store=store, summarize_with=boom
    )
    assert safe["summary"] == ""
    assert safe["chunks"] >= 1
