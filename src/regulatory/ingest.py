"""Regulatory Radar: ingest scraped regulation text into the vector store.

Items are chunked with the standard chunker and added under a per-item
collection (reg-<regulator>-<external_id>.txt) carrying regulator / date /
category metadata plus auto-signals — consistent with the existing per-document
collection machinery so retrieval, scoping and wide-search keep working.
"""

import json

from src.ingestion.chunker import chunk_documents
from src.regulatory.sources import RegulatorySource


def _keywords(title: str, regulator: str, kind: str) -> list[str]:
    tokens = [regulator.lower(), kind.lower()]
    tokens += [w.lower() for w in title.replace("-", " ").split() if len(w) > 4]
    return tokens


def build_chunks(item: dict, source: RegulatorySource, text: str) -> list[dict]:
    """Chunk regulation text with temporal/regulator metadata + auto signals."""
    external_id = item["external_id"]
    filename = f"reg-{source.regulator.lower()}-{external_id}.txt"
    doc = {
        "content": text,
        "metadata": {
            "source": item["url"],
            "filename": filename,
            "regulator": source.regulator,
            "issuance_date": item.get("issued_at") or "",
            "category": source.kind,
            "circular_id": external_id,
        },
        "doc_type": "regulatory",
    }
    chunks = chunk_documents([doc])
    if chunks:
        keywords = _keywords(item.get("title", ""), source.regulator, source.kind)
        chunks[0]["metadata"]["auto_positive_signals"] = json.dumps(keywords)
    return chunks


def ingest_regulatory_item(
    item: dict,
    source: RegulatorySource,
    text: str,
    vector_store=None,
    summarize_with=None,
) -> dict:
    """Chunk + store one regulation item.

    vector_store must expose add_documents(chunks, filename=...). When absent,
    only chunking happens (used by unit tests). Returns
    {filename, chunks, signals}.
    """
    chunks = build_chunks(item, source, text)
    external_id = item["external_id"]
    filename = f"reg-{source.regulator.lower()}-{external_id}.txt"
    summary = ""
    if summarize_with is not None and text:
        try:
            summary = summarize_with(text)
        except Exception:
            summary = ""
    if vector_store is not None and chunks:
        vector_store.add_documents(chunks, filename=filename)
    signal_count = 0
    if chunks:
        raw = chunks[0]["metadata"].get("auto_positive_signals", "[]")
        try:
            signal_count = len(json.loads(raw))
        except Exception:
            signal_count = 0
    return {
        "filename": filename,
        "chunks": len(chunks),
        "signals": signal_count,
        "summary": summary,
    }
