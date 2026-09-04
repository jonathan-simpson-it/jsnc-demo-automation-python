"""Project management endpoints."""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from src.core.database import get_db

router = APIRouter()


class ProjectCreate(BaseModel):
    name: str
    client_id: int | None = None


class ProjectUpdate(BaseModel):
    name: str | None = None
    client_id: int | None = None


@router.get("")
async def list_projects(client_id: int | None = None):
    """List all projects, optionally filtered by client."""
    db = get_db()
    try:
        if client_id:
            rows = db.execute(
                """SELECT p.id, p.name, p.client_id, p.created_at,
                          c.name as client_name
                   FROM projects p
                   LEFT JOIN clients c ON c.id = p.client_id
                   WHERE p.client_id = ?
                   ORDER BY p.name""",
                (client_id,),
            ).fetchall()
        else:
            rows = db.execute(
                """SELECT p.id, p.name, p.client_id, p.created_at,
                          c.name as client_name
                   FROM projects p
                   LEFT JOIN clients c ON c.id = p.client_id
                   ORDER BY p.name"""
            ).fetchall()
        return {"projects": [dict(r) for r in rows]}
    finally:
        db.close()


@router.post("")
async def create_project(body: ProjectCreate):
    """Create a new project."""
    db = get_db()
    try:
        db.execute(
            "INSERT INTO projects (name, client_id) VALUES (?, ?)",
            (body.name, body.client_id),
        )
        db.commit()
        row = db.execute(
            """SELECT p.id, p.name, p.client_id, p.created_at,
                      c.name as client_name
               FROM projects p
               LEFT JOIN clients c ON c.id = p.client_id
               WHERE p.name = ? ORDER BY p.id DESC LIMIT 1""",
            (body.name,),
        ).fetchone()
        return dict(row)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
    finally:
        db.close()


@router.put("/{project_id}")
async def update_project(project_id: int, body: ProjectUpdate):
    """Update a project."""
    db = get_db()
    try:
        updates = []
        params = []
        if body.name is not None:
            updates.append("name = ?")
            params.append(body.name)
        if body.client_id is not None:
            updates.append("client_id = ?")
            params.append(body.client_id)
        if not updates:
            raise HTTPException(status_code=400, detail="Nothing to update")
        params.append(project_id)
        db.execute(f"UPDATE projects SET {', '.join(updates)} WHERE id = ?", params)
        db.commit()
        row = db.execute(
            """SELECT p.id, p.name, p.client_id, p.created_at,
                      c.name as client_name
               FROM projects p
               LEFT JOIN clients c ON c.id = p.client_id
               WHERE p.id = ?""",
            (project_id,),
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Project not found")
        return dict(row)
    finally:
        db.close()


@router.delete("/{project_id}")
async def delete_project(project_id: int):
    """Delete a project."""
    db = get_db()
    try:
        db.execute("DELETE FROM projects WHERE id = ?", (project_id,))
        db.commit()
        return {"deleted": True}
    finally:
        db.close()
