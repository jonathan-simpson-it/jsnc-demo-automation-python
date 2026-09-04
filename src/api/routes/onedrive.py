"""OneDrive integration endpoints."""

import time
from base64 import urlsafe_b64encode
from pathlib import Path
from secrets import token_urlsafe

import httpx
from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel

from src.core.database import get_db
from config.settings import settings

router = APIRouter()

GRAPH_BASE = "https://graph.microsoft.com/v1.0"
AUTH_URL = "https://login.microsoftonline.com/common/oauth2/v2.0/authorize"
TOKEN_URL = "https://login.microsoftonline.com/common/oauth2/v2.0/token"

SCOPES = "Files.Read.All offline_access User.Read"
REDIRECT_PATH = "/api/onedrive/callback"


def _get_client_id() -> str:
    cid = getattr(settings, "onedrive_client_id", None)
    if not cid:
        import os
        cid = os.getenv("ONEDRIVE_CLIENT_ID", "")
    return cid or ""


def _get_client_secret() -> str:
    cs = getattr(settings, "onedrive_client_secret", None)
    if not cs:
        import os
        cs = os.getenv("ONEDRIVE_CLIENT_SECRET", "")
    return cs or ""


def _get_redirect_uri(request: Request) -> str:
    base = str(request.base_url).rstrip("/")
    return f"{base}{REDIRECT_PATH}"


def _store_token(access_token: str, refresh_token: str | None, user_email: str = ""):
    db = get_db()
    try:
        expires_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() + 3600))
        db.execute(
            """INSERT OR REPLACE INTO onedrive_tokens
               (id, access_token, refresh_token, expires_at, user_email, connected_at)
               VALUES (1, ?, ?, ?, ?, datetime('now'))""",
            (access_token, refresh_token, expires_at, user_email),
        )
        db.commit()
    finally:
        db.close()


def _get_token() -> str | None:
    db = get_db()
    try:
        row = db.execute(
            "SELECT access_token, refresh_token, expires_at FROM onedrive_tokens WHERE id = 1"
        ).fetchone()
        if not row:
            return None
        return row["access_token"]
    finally:
        db.close()


def _refresh_token_if_needed():
    """Try to refresh the token if expired."""
    db = get_db()
    try:
        row = db.execute(
            "SELECT refresh_token, expires_at FROM onedrive_tokens WHERE id = 1"
        ).fetchone()
        if not row or not row["refresh_token"]:
            return
        # Check if expired (with 5 min buffer)
        expires = row["expires_at"]
        if expires:
            from datetime import datetime, timezone
            exp_time = datetime.fromisoformat(expires.replace("Z", "+00:00"))
            if exp_time.timestamp() > time.time() + 300:
                return  # Still valid

        # Refresh
        client_id = _get_client_id()
        client_secret = _get_client_secret()
        if not client_id or not client_secret:
            return

        resp = httpx.post(TOKEN_URL, data={
            "client_id": client_id,
            "client_secret": client_secret,
            "grant_type": "refresh_token",
            "refresh_token": row["refresh_token"],
        })
        if resp.status_code == 200:
            data = resp.json()
            _store_token(
                data["access_token"],
                data.get("refresh_token", row["refresh_token"]),
            )
    finally:
        db.close()


# ---- Endpoints ----


class OneDriveStatus(BaseModel):
    connected: bool
    user_email: str | None = None


@router.get("/status")
async def onedrive_status():
    """Check if OneDrive is connected."""
    db = get_db()
    try:
        row = db.execute(
            "SELECT user_email, access_token FROM onedrive_tokens WHERE id = 1"
        ).fetchone()
        connected = bool(row and row["access_token"])
        return OneDriveStatus(
            connected=connected,
            user_email=row["user_email"] if row else None,
        )
    finally:
        db.close()


@router.get("/connect")
async def onedrive_connect(request: Request):
    """Start OneDrive OAuth flow. Redirects to Microsoft login."""
    client_id = _get_client_id()
    if not client_id:
        raise HTTPException(
            status_code=400,
            detail="OneDrive not configured. Set ONEDRIVE_CLIENT_ID in .env",
        )

    redirect_uri = _get_redirect_uri(request)
    state = token_urlsafe(32)

    auth_params = {
        "client_id": client_id,
        "scope": SCOPES,
        "response_type": "code",
        "redirect_uri": redirect_uri,
        "state": state,
        "response_mode": "query",
    }
    qs = "&".join(f"{k}={v}" for k, v in auth_params.items())
    return RedirectResponse(url=f"{AUTH_URL}?{qs}")


@router.get("/callback")
async def onedrive_callback(
    request: Request,
    code: str = Query(default=""),
    error: str = Query(default=""),
):
    """Handle OneDrive OAuth callback."""
    if error:
        return RedirectResponse(url=f"/documents?onedrive_error={error}")

    client_id = _get_client_id()
    client_secret = _get_client_secret()
    if not client_id or not client_secret:
        return RedirectResponse(url="/documents?onedrive_error=config_missing")

    redirect_uri = _get_redirect_uri(request)

    # Exchange code for token
    resp = httpx.post(TOKEN_URL, data={
        "client_id": client_id,
        "client_secret": client_secret,
        "code": code,
        "grant_type": "authorization_code",
        "redirect_uri": redirect_uri,
    })

    if resp.status_code != 200:
        return RedirectResponse(url="/documents?onedrive_error=token_exchange_failed")

    data = resp.json()
    access_token = data.get("access_token")
    refresh_token = data.get("refresh_token")

    # Get user email
    user_resp = httpx.get(
        f"{GRAPH_BASE}/me",
        headers={"Authorization": f"Bearer {access_token}"},
    )
    user_email = ""
    if user_resp.status_code == 200:
        user_email = user_resp.json().get("mail", "") or user_resp.json().get("userPrincipalName", "")

    _store_token(access_token, refresh_token, user_email)
    return RedirectResponse(url="/documents?onedrive_connected=1")


@router.get("/files")
async def list_onedrive_files(path: str = "/"):
    """List files/folders from OneDrive."""
    _refresh_token_if_needed()
    token = _get_token()
    if not token:
        raise HTTPException(status_code=401, detail="OneDrive not connected")

    encoded_path = path.replace("'", "''").replace("/", "%2F") if path != "/" else "root"
    url = f"{GRAPH_BASE}/me/drive/root:/{path}:/children" if path != "/" else f"{GRAPH_BASE}/me/drive/root/children"

    resp = httpx.get(
        url,
        headers={"Authorization": f"Bearer {token}"},
        params={"$top": 100, "$orderby": "name"},
    )

    if resp.status_code == 401:
        raise HTTPException(status_code=401, detail="OneDrive token expired. Reconnect.")
    if resp.status_code != 200:
        raise HTTPException(status_code=resp.status_code, detail=resp.text)

    items = resp.json().get("value", [])
    files = []
    for item in items:
        is_folder = "folder" in item
        files.append({
            "id": item["id"],
            "name": item["name"],
            "is_folder": is_folder,
            "size": item.get("size", 0),
            "path": item.get("parentReference", {}).get("path", ""),
            "last_modified": item.get("lastModifiedDateTime", ""),
            "mime_type": item.get("file", {}).get("mimeType", ""),
        })

    return {"files": files, "path": path}


class OneDriveImport(BaseModel):
    file_id: str
    file_name: str
    client_id: int | None = None
    project_id: int | None = None


@router.post("/import")
async def import_from_onedrive(body: OneDriveImport):
    """Import a file from OneDrive into the knowledge base."""
    _refresh_token_if_needed()
    token = _get_token()
    if not token:
        raise HTTPException(status_code=401, detail="OneDrive not connected")

    # Download file content
    resp = httpx.get(
        f"{GRAPH_BASE}/me/drive/items/{body.file_id}/content",
        headers={"Authorization": f"Bearer {token}"},
        follow_redirects=True,
    )

    if resp.status_code != 200:
        raise HTTPException(status_code=resp.status_code, detail="Failed to download file")

    content = resp.content

    # Save to uploads
    upload_dir = Path("data/uploads")
    upload_dir.mkdir(parents=True, exist_ok=True)
    safe_name = Path(body.file_name).name
    file_path = upload_dir / safe_name
    file_path.write_bytes(content)

    # Ingest
    ingested = 0
    try:
        from src.ingestion.loader import _infer_doc_type, _load_text_with_lines, _load_pdf_with_pages

        suffix = file_path.suffix.lower()
        if suffix == ".pdf":
            locations = _load_pdf_with_pages(file_path)
        else:
            locations = _load_text_with_lines(file_path)

        content_text = "\n\n".join(loc["text"] for loc in locations if loc["text"].strip())
        if content_text.strip():
            doc_type = _infer_doc_type(file_path)
            doc = {
                "content": content_text,
                "metadata": {"source": str(file_path), "filename": safe_name},
                "locations": locations,
                "doc_type": doc_type.value,
            }
            chunks = chunk_documents([doc])
            from src.api.deps import get_vector_store
            store = get_vector_store()
            store.add_documents(chunks)
            ingested = len(chunks)
    except Exception:
        ingested = 0

    # Save to database
    db = get_db()
    try:
        cursor = db.execute(
            """INSERT INTO documents
               (filename, chunks, doc_type, client_id, project_id, source, onedrive_id, onedrive_path)
               VALUES (?, ?, '', ?, ?, 'onedrive', ?, ?)""",
            (safe_name, ingested, body.client_id, body.project_id, body.file_id, body.file_name),
        )
        db.commit()
        return {
            "id": cursor.lastrowid,
            "filename": safe_name,
            "size": len(content),
            "status": "imported",
            "chunks_ingested": ingested,
        }
    finally:
        db.close()


@router.post("/disconnect")
async def disconnect_onedrive():
    """Disconnect OneDrive."""
    db = get_db()
    try:
        db.execute("DELETE FROM onedrive_tokens WHERE id = 1")
        db.commit()
        return {"disconnected": True}
    finally:
        db.close()
