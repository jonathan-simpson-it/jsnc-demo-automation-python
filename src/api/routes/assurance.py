"""Compliance assurance pack: one downloadable export for the due-diligence file.

Bundles the artifacts a licensed client's compliance team needs as evidence
of oversight (see docs/regulatory-positioning.md, section 4):

- Audit-chain integrity verification plus the regulator-ready audit export
- Model-version records (freeze/rollback evidence) and a configuration hash
- An explainability report for the most recent audited query

Every section is isolated: a failing store degrades to an explicit notice
instead of failing the export.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

from fastapi import APIRouter
from fastapi.responses import Response

router = APIRouter()

PACK_TITLE = "# Compliance Assurance Pack"


def _audit_section(audit) -> list[str]:
    """Audit-chain integrity verdict + regulator-ready export."""
    lines: list[str] = ["## 1. Audit Chain Integrity", ""]
    try:
        verified = audit.verify_integrity()
        entries = audit.query_history(limit=1_000_000)
        verdict = "VERIFIED - chain unbroken, no tamper detected" if verified else (
            "FAILED - hash-chain mismatch detected; treat the trail as compromised"
        )
        lines += [
            f"**Integrity check:** {verdict}",
            f"**Entries in trail:** {len(entries)}",
            "",
            "### Regulator export",
            "",
            "```",
            audit.export_for_regulator(),
            "```",
        ]
    except Exception as exc:  # noqa: BLE001 - degrade, never fail the pack
        lines.append(f"**Unavailable:** audit store could not be read ({exc}).")
    return lines


def _version_section(tracker) -> list[str]:
    """Model-version history + current configuration hash."""
    lines: list[str] = ["", "## 2. Model Versions", ""]
    try:
        current = tracker.get_current()
        if current:
            lines += [
                "**Current deployment:** "
                f"{current['model_name']} v{current['version']} "
                f"(config `{current['config_hash']}`, registered {current['timestamp']})",
                "",
            ]
        history = tracker.get_history(limit=50)
        if history:
            lines += [
                "| Registered | Model | Version | Config hash | Notes |",
                "|---|---|---|---|---|",
            ]
            for r in history:
                lines.append(
                    f"| {r['timestamp']} | {r['model_name']} | {r['version']} "
                    f"| `{r['config_hash']}` | {r['notes'] or '-'} |"
                )
        else:
            lines.append(
                "No model versions registered yet. Register each deployment "
                "via the model-version tracker to build freeze/rollback evidence."
            )
        lines += ["", "### Configuration hash at export time", ""]
        try:
            from config.settings import settings

            config = settings.model_dump()
            config["deepseek_api_key"] = "***" if config.get("deepseek_api_key") else ""
            lines.append(f"`{tracker.compute_config_hash(config)}`")
        except Exception as exc:  # noqa: BLE001
            lines.append(f"Unavailable ({exc}).")
    except Exception as exc:  # noqa: BLE001
        lines.append(f"**Unavailable:** version store could not be read ({exc}).")
    return lines


def _explainability_section(audit, tracker) -> list[str]:
    """Explainability report for the most recent audited query."""
    lines: list[str] = ["", "## 3. Explainability Report (latest audited query)", ""]
    try:
        latest = audit.query_history(limit=1)
        if not latest:
            lines.append(
                "No audited queries yet. Once the system answers queries, the "
                "most recent one is exported here with its full pipeline provenance."
            )
            return lines
        entry = latest[0]
        current = None
        try:
            current = tracker.get_current()
        except Exception:  # noqa: BLE001 - model line is cosmetic
            pass
        model_version = (
            f"{current['model_name']} v{current['version']}"
            if current
            else "unregistered"
        )
        from src.compliance.explain import ExplainabilityReport

        report = ExplainabilityReport(
            query=entry["query"],
            response=entry["response"],
            agent_type=entry["agent_type"],
            trace=entry["trace"] or [],
            citations=[],
            confidence=entry["confidence"] or 0.0,
            model_version=model_version,
            user_id=entry["user_id"],
        )
        lines.append(report.generate())
    except Exception as exc:  # noqa: BLE001
        lines.append(f"**Unavailable:** explainability report failed ({exc}).")
    return lines


def build_assurance_pack(audit=None, tracker=None) -> str:
    """Assemble the full pack as a Markdown document.

    ``audit`` and ``tracker`` are injectable for tests; production callers
    use the default SQLite stores.
    """
    if audit is None:
        from src.compliance.audit import AuditLog

        audit = AuditLog()
    if tracker is None:
        from src.compliance.versioning import ModelVersionTracker

        tracker = ModelVersionTracker()

    now = datetime.now(timezone.utc).isoformat()
    lines: list[str] = [
        PACK_TITLE,
        "",
        f"**Generated:** {now}",
        "**Purpose:** Evidence bundle for a licensed firm's vendor due-diligence "
        "and oversight file. Covers audit-trail integrity, model-version "
        "governance, and answer explainability.",
        "",
        "---",
        "",
    ]
    lines += _audit_section(audit)
    lines += _version_section(tracker)
    lines += _explainability_section(audit, tracker)
    lines += [
        "",
        "---",
        "",
        "*This pack was generated live from the system's compliance stores. "
        "Jonathan Simpson & Co. is a technology provider; regulatory sign-off "
        "remains with the licensed firm.*",
        "",
    ]
    return "\n".join(lines)


@router.get("/pack")
async def get_assurance_pack():
    """Download the compliance assurance pack as Markdown."""
    content = build_assurance_pack()
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    return Response(
        content=content,
        media_type="text/markdown; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="assurance-pack-{stamp}.md"',
            "Cache-Control": "no-store",
        },
    )
