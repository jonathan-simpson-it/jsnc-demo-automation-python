"""PII and sensitive data detection and redaction.

SME FIs handling client documents (KYC files, financial statements)
must ensure the system doesn't leak PII in logs, cache, or exports.
This module detects and redacts common PII patterns.
"""

from __future__ import annotations

import re


# PII detection patterns
_PATTERNS = {
    "email": re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}"),
    "phone_hk": re.compile(r"(?:\+852[\s-]?)?\d{4}[\s-]?\d{4}"),
    "phone_intl": re.compile(r"(?:\+?\d{1,3}[\s-]?)?\(?\d{2,4}\)?[\s-]?\d{3,4}[\s-]?\d{3,4}"),
    "hkid": re.compile(r"[A-Z]\d{6}\(\d\)"),
    "bank_account": re.compile(r"\b\d{3}[\s-]?\d{3}[\s-]?\d{6,12}\b"),
    "credit_card": re.compile(r"\b\d{4}[\s-]?\d{4}[\s-]?\d{4}[\s-]?\d{4}\b"),
    "national_id": re.compile(r"\b\d{6,12}\b"),
    "address_hk": re.compile(
        r"\d+[A-Za-z]?\s+(?:Street|Road|Avenue|Drive|Lane|Terrace|Place|Block|Flat|Room)\s+\d*",
        re.IGNORECASE,
    ),
}

# Replacement tokens
_REPLACEMENTS = {
    "email": "[REDACTED_EMAIL]",
    "phone_hk": "[REDACTED_PHONE]",
    "phone_intl": "[REDACTED_PHONE]",
    "hkid": "[REDACTED_HKID]",
    "bank_account": "[REDACTED_ACCOUNT]",
    "credit_card": "[REDACTED_CARD]",
    "national_id": "[REDACTED_ID]",
    "address_hk": "[REDACTED_ADDRESS]",
}

# Priority order — more specific patterns first to avoid partial matches
_PRIORITY = ["hkid", "credit_card", "bank_account", "email", "phone_hk", "phone_intl", "address_hk", "national_id"]


def detect_pii(text: str) -> list[dict]:
    """Detect PII patterns in text without redacting.

    Returns list of dicts with keys: type, start, end, matched_text.
    """
    matches = []
    for pii_type in _PRIORITY:
        pattern = _PATTERNS[pii_type]
        for m in pattern.finditer(text):
            # Skip if this span overlaps an existing match
            if any(m.start() < e["end"] and m.end() > e["start"] for e in matches):
                continue
            matches.append({
                "type": pii_type,
                "start": m.start(),
                "end": m.end(),
                "matched_text": m.group(),
            })
    matches.sort(key=lambda x: x["start"])
    return matches


def redact_pii(text: str) -> tuple[str, list[dict]]:
    """Detect and redact PII from text.

    Returns:
        Tuple of (redacted_text, list_of_redactions_found).
    """
    matches = detect_pii(text)

    if not matches:
        return text, []

    # Apply redactions in reverse order to preserve indices
    redacted = text
    for match in reversed(matches):
        replacement = _REPLACEMENTS.get(match["type"], "[REDACTED]")
        redacted = redacted[:match["start"]] + replacement + redacted[match["end"]:]

    return redacted, matches
