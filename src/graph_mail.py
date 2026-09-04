"""Microsoft Graph mail integration (read mailbox + create drafts).

Uses the OAuth 2.0 client-credentials flow with application permissions
(Mail.Read, Mail.ReadWrite). Requires GRAPH_TENANT_ID / GRAPH_CLIENT_ID /
GRAPH_CLIENT_SECRET and, optionally, GRAPH_MAILBOX (a userPrincipalName).
When GRAPH_MAILBOX is empty, the mailbox of the OneDrive-connected user is
used if known.

Everything degrades gracefully: unconfigured credentials, missing scopes, or
network errors surface as structured state instead of exceptions.
"""

from __future__ import annotations

import time
from typing import Any

import httpx

from config.settings import settings

_GRAPH_BASE = "https://graph.microsoft.com/v1.0"
_TOKEN_URL = "https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token"

_token_cache: dict[str, Any] = {"token": None, "expires_at": 0.0}


DEMO_DB_PATH = "./data/graph_drafts.db"
_ALLOWED_CONTENT_TYPES = ("text", "html")


def _demo_db(db_path: str | None) -> str:
    return db_path or DEMO_DB_PATH


def configured() -> bool:
    return bool(
        settings.graph_tenant_id
        and settings.graph_client_id
        and settings.graph_client_secret
    )


def _acquire_token() -> str:
    """Return a valid access token (client credentials), cached until expiry."""
    if _token_cache["token"] and time.time() < _token_cache["expires_at"] - 60:
        return _token_cache["token"]
    resp = httpx.post(
        _TOKEN_URL.format(tenant=settings.graph_tenant_id),
        data={
            "client_id": settings.graph_client_id,
            "client_secret": settings.graph_client_secret,
            "scope": "https://graph.microsoft.com/.default",
            "grant_type": "client_credentials",
        },
        timeout=20,
    )
    resp.raise_for_status()
    data = resp.json()
    token = data["access_token"]
    _token_cache["token"] = token
    _token_cache["expires_at"] = time.time() + int(data.get("expires_in", 3600))
    return token


def _mailbox() -> str:
    """Resolve the target mailbox (userPrincipalName)."""
    if settings.graph_mailbox:
        return settings.graph_mailbox
    try:
        from src.core import database as db

        conn = db.get_db()
        row = conn.execute(
            "SELECT user_email FROM onedrive_tokens WHERE id = 1"
        ).fetchone()
        conn.close()
        if row and row[0]:
            return row[0]
    except Exception:
        pass
    raise RuntimeError("GRAPH_MAILBOX is not set and no OneDrive user is connected")


def _get(path: str, params: dict | None = None) -> dict:
    headers = {"Authorization": f"Bearer {_acquire_token()}"}
    resp = httpx.get(
        f"{_GRAPH_BASE}{path}", headers=headers, params=params, timeout=25
    )
    resp.raise_for_status()
    return resp.json()


def _post(path: str, payload: dict) -> dict:
    headers = {"Authorization": f"Bearer {_acquire_token()}"}
    resp = httpx.post(
        f"{_GRAPH_BASE}{path}", headers=headers, json=payload, timeout=25
    )
    resp.raise_for_status()
    return resp.json()


def status() -> dict:
    """Describe whether the mail integration can work right now."""
    if not configured():
        return {
            "configured": False,
            "demo": True,
            "mailbox": "demo@firm.local",
            "reason": (
                "Demo mailbox active — set GRAPH_TENANT_ID, GRAPH_CLIENT_ID "
                "and GRAPH_CLIENT_SECRET in .env to connect a real Outlook "
                "mailbox."
            ),
        }
    try:
        mailbox = _mailbox()
    except RuntimeError as exc:
        return {"configured": False, "demo": False, "reason": str(exc)}
    return {"configured": True, "demo": False, "mailbox": mailbox}


# (sender, subject, days_ago, hour, minute)
_DEMO_ROWS = [
    ("SFC News Alerts <enquiry@sfc.hk>", "SFC enhances guidance for authorised funds with exposure to private market assets", 1, 9, 30),
    ("HKMA Press Office <enquiry@hkma.gov.hk>", "Scam alert related to banks", 1, 8, 12),
    ("Jonathan Simpson <jonathan@jsco.hk>", "Q3 portfolio review: schedule", 3, 16, 40),
    ("SFC News Alerts <enquiry@sfc.hk>", "First cohort of GenA.I. Sandbox++", 4, 11, 5),
    ("HKMA Press Office <enquiry@hkma.gov.hk>", "Exchange Fund Abridged Balance Sheet and Currency Board Account", 4, 9, 0),
    ("Deal Desk <deals@jsco.hk>", "Enosis term sheet: redline comments", 5, 18, 22),
    ("SFC News Alerts <enquiry@sfc.hk>", "Stronger Mainland connectivity reinforces Hong Kong's leading role as China assets gateway", 5, 14, 45),
    ("Compliance <compliance@jsco.hk>", "AML training completion reminder", 6, 12, 10),
    ("HKMA Press Office <enquiry@hkma.gov.hk>", "Monetary Statistics for July 2026", 7, 9, 15),
    ("Investor Relations <ir@jsco.hk>", "LP report draft for Q3 2026", 8, 17, 55),
]


def _demo_emails(limit: int = 50) -> list[dict]:
    """Deterministic demo mailbox used until Graph credentials are set."""
    from datetime import datetime, timedelta

    emails = []
    now = datetime.utcnow()
    for idx, (sender, subject, days_ago, hour, minute) in enumerate(_DEMO_ROWS[:limit]):
        ts = (now - timedelta(days=days_ago)).replace(hour=hour, minute=minute, second=0)
        name, address = sender.rsplit(" <", 1)
        address = address[:-1]
        emails.append(
            {
                "id": f"demo-{idx + 1}",
                "subject": subject,
                "from": name,
                "from_email": address,
                "received_at": ts.isoformat() + "Z",
                "body_preview": (
                    "Dear team,\n\n"
                    "This is a demo message shown while the Microsoft Graph "
                    "mailbox is not configured. Messages like this would list "
                    "real mail from the connected Outlook mailbox once "
                    "GRAPH_TENANT_ID / GRAPH_CLIENT_ID / GRAPH_CLIENT_SECRET "
                    "are set in .env.\n\n"
                    f"-- {subject}"
                )[:500],
                "web_link": "",
            }
        )
    return emails


def _save_demo_draft(
    subject: str, body: str, to: list[str] | None, db_path: str | None = None
) -> dict:
    """Keep demo drafts locally so the flow is visible end to end."""
    import sqlite3
    from datetime import datetime, timezone

    conn = sqlite3.connect(_demo_db(db_path), timeout=5)
    conn.execute(
        """CREATE TABLE IF NOT EXISTS graph_drafts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            subject TEXT NOT NULL,
            body TEXT NOT NULL,
            to_recipients TEXT DEFAULT '',
            created_at TEXT DEFAULT (datetime('now'))
        )"""
    )
    cur = conn.execute(
        "INSERT INTO graph_drafts (subject, body, to_recipients) VALUES (?, ?, ?)",
        (subject, body, ", ".join(to or [])),
    )
    conn.commit()
    draft_id = cur.lastrowid
    conn.close()
    return {
        "id": f"demo-draft-{draft_id}",
        "subject": subject,
        "draft_link": "",
        "demo": True,
    }


def list_messages(limit: int = 50) -> list[dict]:
    """Return the newest messages from the target mailbox (or demo data)."""
    if not configured():
        return _demo_emails(limit)
    mailbox = _mailbox()
    params = {
        "$top": max(1, min(int(limit), 200)),
        "$select": "id,subject,from,receivedDateTime,bodyPreview,webLink",
        "$orderby": "receivedDateTime desc",
    }
    data = _get(f"/users/{mailbox}/messages", params=params)
    emails = []
    for msg in data.get("value", []):
        sender = (msg.get("from") or {}).get("emailAddress") or {}
        emails.append(
            {
                "id": msg.get("id"),
                "subject": msg.get("subject") or "",
                "from": sender.get("name") or sender.get("address") or "",
                "from_email": sender.get("address") or "",
                "received_at": msg.get("receivedDateTime"),
                "body_preview": (msg.get("bodyPreview") or "").strip()[:500],
                "web_link": msg.get("webLink") or "",
            }
        )
    return emails


def create_draft(
    subject: str,
    body: str,
    to: list[str] | None = None,
    content_type: str = "text",
    db_path: str | None = None,
) -> dict:
    """Create a draft message in the mailbox's Drafts folder (demo locally)."""
    if content_type not in _ALLOWED_CONTENT_TYPES:
        raise ValueError(f"content_type must be one of {_ALLOWED_CONTENT_TYPES}")
    if not configured():
        return _save_demo_draft(subject, body, to, db_path)
    mailbox = _mailbox()
    payload: dict[str, Any] = {
        "subject": subject,
        "body": {"contentType": content_type, "content": body},
        "importance": "normal",
    }
    if to:
        payload["toRecipients"] = [
            {"emailAddress": {"address": address}} for address in to
        ]
    created = _post(f"/users/{mailbox}/messages", payload)
    return {
        "id": created.get("id"),
        "subject": created.get("subject") or subject,
        "draft_link": created.get("webLink") or "",
    }


def list_drafts(limit: int = 20, db_path: str | None = None) -> list[dict]:
    """Return saved drafts — local demo store or the Graph Drafts folder."""
    if not configured():
        import sqlite3

        conn = sqlite3.connect(_demo_db(db_path), timeout=5)
        try:
            rows = conn.execute(
                "SELECT id, subject, to_recipients, created_at FROM graph_drafts "
                "ORDER BY id DESC LIMIT ?",
                (max(1, min(int(limit), 100)),),
            ).fetchall()
        finally:
            conn.close()
        return [
            {
                "id": f"demo-draft-{r[0]}",
                "subject": r[1],
                "to": r[2] or "",
                "created_at": r[3],
                "demo": True,
            }
            for r in rows
        ]
    mailbox = _mailbox()
    params = {
        "$top": max(1, min(int(limit), 100)),
        "$select": "id,subject,toRecipients,lastModifiedDateTime,webLink",
    }
    data = _get(f"/users/{mailbox}/mailFolders/Drafts/messages", params=params)
    drafts = []
    for msg in data.get("value", []):
        to = ", ".join(
            r.get("emailAddress", {}).get("address", "")
            for r in (msg.get("toRecipients") or [])
        )
        drafts.append(
            {
                "id": msg.get("id"),
                "subject": msg.get("subject") or "",
                "to": to,
                "created_at": msg.get("lastModifiedDateTime"),
                "demo": False,
                "draft_link": msg.get("webLink") or "",
            }
        )
    return drafts
