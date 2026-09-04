"""Client management endpoints."""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from src.core.database import get_db

router = APIRouter()


class ClientCreate(BaseModel):
    name: str


class ClientUpdate(BaseModel):
    name: str | None = None


@router.get("")
async def list_clients():
    """List all clients."""
    db = get_db()
    try:
        rows = db.execute(
            "SELECT id, name, created_at FROM clients ORDER BY name"
        ).fetchall()
        return {"clients": [dict(r) for r in rows]}
    finally:
        db.close()


@router.post("")
async def create_client(body: ClientCreate):
    """Create a new client."""
    db = get_db()
    try:
        db.execute("INSERT INTO clients (name) VALUES (?)", (body.name,))
        db.commit()
        row = db.execute(
            "SELECT id, name, created_at FROM clients WHERE name = ?",
            (body.name,),
        ).fetchone()
        return dict(row)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
    finally:
        db.close()


@router.put("/{client_id}")
async def update_client(client_id: int, body: ClientUpdate):
    """Update a client."""
    if body.name is None:
        raise HTTPException(status_code=400, detail="Nothing to update")
    db = get_db()
    try:
        db.execute(
            "UPDATE clients SET name = ? WHERE id = ?",
            (body.name, client_id),
        )
        db.commit()
        row = db.execute(
            "SELECT id, name, created_at FROM clients WHERE id = ?",
            (client_id,),
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Client not found")
        return dict(row)
    finally:
        db.close()


@router.delete("/{client_id}")
async def delete_client(client_id: int):
    """Delete a client."""
    db = get_db()
    try:
        db.execute("DELETE FROM clients WHERE id = ?", (client_id,))
        db.commit()
        return {"deleted": True}
    finally:
        db.close()
