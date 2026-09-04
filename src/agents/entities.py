"""Cross-document entity detection and linking."""

from __future__ import annotations

import re
from collections import defaultdict

_STOP_TERMS = frozenset({
    "the", "this", "that", "these", "those", "series", "round",
    "funding", "investor", "capital", "fund", "portfolio", "company",
    "group", "partners", "limited", "inc", "corp", "ltd", "llc",
    "asia", "pacific", "hong", "kong", "china", "global", "international",
})

_KNOWN_ENTITIES = {
    "archbridge": "company",
    "deepseek": "company",
    "chromadb": "company",
    "langgraph": "technology",
}


def detect_entities(text: str) -> list[dict]:
    """Detect named entities in text using pattern matching."""
    if not text or not text.strip():
        return []

    entities: dict[str, dict] = defaultdict(
        lambda: {"name": "", "type": "unknown", "mentions": 0}
    )

    for match in re.finditer(
        r"\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,2})\b", text
    ):
        name = match.group(1).strip()
        words = name.split()
        if all(w.lower() in _STOP_TERMS for w in words):
            continue
        key = name.lower()
        if key not in entities:
            entities[key]["name"] = name
            entities[key]["type"] = _classify_entity(name)
        entities[key]["mentions"] += 1

    for match in re.finditer(
        r"\b([A-Z][a-zA-Z]*(?:\s+[A-Z][a-zA-Z]*)*)\s+"
        r"(Corp|Inc|Ltd|LLC|Partners|Group|Company|Co\.|PLC)\b",
        text,
    ):
        name = f"{match.group(1)} {match.group(2)}"
        key = name.lower()
        if key not in entities:
            entities[key]["name"] = name
            entities[key]["type"] = "company"
        entities[key]["mentions"] += 1

    text_lower = text.lower()
    for entity, etype in _KNOWN_ENTITIES.items():
        if entity in text_lower:
            key = entity.lower()
            if key not in entities:
                entities[key]["name"] = entity.title()
                entities[key]["type"] = etype
            entities[key]["mentions"] += 1

    return list(entities.values())


def _classify_entity(name: str) -> str:
    words = name.split()
    if len(words) == 2 and all(w[0].isupper() for w in words):
        if all(w.isalpha() for w in words):
            return "person"
    if len(words) >= 3:
        return "organization"
    return "other"


def link_entities_across_docs(
    documents: dict[str, str],
) -> dict[str, dict]:
    """Find entities that appear across multiple documents."""
    entity_docs: dict[str, dict] = defaultdict(
        lambda: {"type": "unknown", "documents": [], "total_mentions": 0}
    )

    for filename, content in documents.items():
        entities = detect_entities(content)
        for entity in entities:
            key = entity["name"].lower()
            entry = entity_docs[key]
            entry["type"] = entity["type"]
            if filename not in entry["documents"]:
                entry["documents"].append(filename)
            entry["total_mentions"] += entity["mentions"]

    return {
        name: info
        for name, info in entity_docs.items()
        if len(info["documents"]) >= 2
    }
