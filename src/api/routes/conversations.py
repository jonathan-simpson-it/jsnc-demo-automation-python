"""Conversation (chat history) endpoints."""

import sqlite3

from fastapi import APIRouter, HTTPException

from src.core import database as db
from src.core.models import ConversationCreate, ConversationMessageOut, ConversationOut

router = APIRouter()


@router.get("")
async def list_conversations() -> dict:
    """List all conversations, newest first, with message counts/previews."""
    rows = db.list_conversations()
    return {
        "conversations": [
            ConversationOut(**{**row, "message_count": int(row.get("message_count", 0))})
            for row in rows
        ]
    }


@router.post("", status_code=201)
async def create_conversation(req: ConversationCreate) -> ConversationOut:
    """Create a chat conversation. project_id None = Global workspace."""
    try:
        conv = db.create_conversation(
            project_id=req.project_id, title=req.title or "New chat"
        )
    except sqlite3.IntegrityError:
        raise HTTPException(status_code=400, detail="Invalid project_id") from None
    return ConversationOut(**conv)


@router.delete("/{conversation_id}")
async def delete_conversation(conversation_id: int) -> dict:
    """Delete a conversation and its messages."""
    if not db.delete_conversation(conversation_id):
        raise HTTPException(status_code=404, detail="Conversation not found")
    return {"deleted": True}


@router.get("/{conversation_id}/messages")
async def get_messages(conversation_id: int) -> dict:
    """Return all messages for a conversation, oldest first."""
    if db.get_conversation(conversation_id) is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    messages = db.list_messages(conversation_id)
    return {
        "messages": [
            ConversationMessageOut(**m)
            for m in messages
        ]
    }
