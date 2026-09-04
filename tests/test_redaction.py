"""Tests for PII/sensitive data redaction."""

from src.compliance.redaction import redact_pii, detect_pii


def test_redact_email():
    text = "Contact john.doe@acme.com for details"
    redacted, found = redact_pii(text)
    assert "john.doe@acme.com" not in redacted
    assert "[REDACTED_EMAIL]" in redacted
    assert len(found) == 1
    assert found[0]["type"] == "email"


def test_redact_phone():
    text = "Call +852-1234-5678 or (852) 9876-5432"
    redacted, found = redact_pii(text)
    assert "852-1234-5678" not in redacted
    assert len(found) >= 1


def test_redact_hkid():
    text = "HKID: A123456(7) for verification"
    redacted, found = redact_pii(text)
    assert "A123456(7)" not in redacted
    assert "[REDACTED_HKID]" in redacted


def test_redact_financial_account():
    text = "Transfer to account 123-456-789012"
    redacted, found = redact_pii(text)
    assert "123-456-789012" not in redacted
    assert len(found) >= 1


def test_no_false_positives():
    text = "Acme Corp raised $10M in Series A at $50M valuation"
    redacted, found = redact_pii(text)
    assert redacted == text  # No PII found
    assert len(found) == 0


def test_detect_pii_returns_matches():
    text = "Email: test@example.com, Phone: +852-1234-5678"
    matches = detect_pii(text)
    assert len(matches) >= 2
    types = {m["type"] for m in matches}
    assert "email" in types
