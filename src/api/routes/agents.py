"""Agent execution endpoints."""

import json
import time

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from config.settings import settings
from src.api.deps import get_router_agent
from src.core import database as db
from src.core.models import AgentQuery
from src.utils.api_key import ApiKeyMissingError, resolve_api_key
from src.utils.cost_tracker import cost_tracker
from src.utils.telemetry import run_log

router = APIRouter()


def _require_api_key() -> None:
    """Fail fast with a structured 402 before any LLM work starts."""
    try:
        resolve_api_key()
    except ApiKeyMissingError as exc:
        raise HTTPException(
            status_code=402,
            detail={"code": "missing_api_key", "message": str(exc)},
        )


def _record_audit(query: str, response) -> None:
    """Write the query/response pair into the tamper-evident audit trail.

    Never fatal: an audit failure must not break a chat turn.
    """
    try:
        from src.compliance.audit import AuditLog

        meta = response.metadata or {}
        AuditLog().log_query(
            query=query,
            response=response.result,
            agent_type=response.agent_type,
            trace=meta.get("trace") or [],
            user_id="local",
            confidence=response.confidence_score or 0.0,
        )
    except Exception:
        pass


def _push_run(query, response, cost_before: float) -> None:
    """Record a finished run into the in-memory telemetry log (never fatal).

    Lives at the API layer so every execution -- regardless of router
    implementation -- is observable.
    """
    try:
        meta = response.metadata or {}
        trace = meta.get("trace") or []
        run_log.push(
            {
                "ts": time.time(),
                "query": query,
                "agent_type": response.agent_type,
                "routing_method": meta.get("routing_method"),
                "confidence": response.confidence_score,
                "trace": trace,
                "total_ms": sum(t.get("ms", 0) for t in trace),
                "error": bool(meta.get("error")),
                "cost": round(
                    cost_tracker.get_summary()["total_cost"] - cost_before, 6
                ),
            }
        )
    except Exception:
        pass


def _conversation_context(
    conversation_id: int | None, request_project_id: int | None
) -> tuple[dict | None, list[dict] | None, list[str] | None]:
    """Resolve conversation persistence + retrieval scope + turn history.

    Returns (conversation, history, allowed_filenames). History is the last
    10 non-error messages served from the database (server-authoritative).
    allowed_filenames is None when unscoped (Global) and the exact document
    list when the conversation belongs to a project (strict isolation).
    """
    if conversation_id is None:
        return None, None, None
    conv = db.get_conversation(conversation_id)
    if conv is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    if (
        request_project_id is not None
        and conv["project_id"] != request_project_id
    ):
        raise HTTPException(
            status_code=400,
            detail="project_id does not match the conversation's project",
        )
    project_id = conv["project_id"]
    allowed = db.documents_for_project(project_id) if project_id is not None else None
    history = [
        {"role": m["role"], "content": m["content"]}
        for m in db.list_messages(conversation_id)
        if not m["is_error"]
    ][-10:]
    return conv, history, allowed


def _scope_tagged(
    allowed: list[str] | None, tagged_filenames: list[str]
) -> list[str] | None:
    """Restrict a retrieval scope to the @-mentioned filenames.

    Strict isolation invariant: the tagged set is always intersected with the
    conversation's own scope (``allowed``), so tagging can narrow retrieval
    but can never widen it into another project's documents.

    Returns an empty list when the tags reference filenames that don't exist
    in the scope (the graph then answers with its explicit no-data result)
    instead of silently falling back to the closest in-scope match.
    """
    wanted = set(tagged_filenames)
    if not wanted:
        return allowed
    if allowed is None:
        return sorted(wanted)
    matched = [f for f in allowed if f in wanted]
    return sorted(matched)


def _persist_turn(
    conv: dict | None,
    user_query: str,
    response,
) -> None:
    """Persist a user turn + assistant answer into the conversation."""
    if conv is None:
        return
    db.add_message(conv["id"], "user", user_query)
    db.add_message(
        conv["id"],
        "assistant",
        response.result,
        agent_type=response.agent_type,
        citations=response.citations,
        trace=response.metadata.get("trace"),
        confidence=response.confidence_score,
        is_error=bool(response.metadata.get("error")),
    )


def _should_queue(response, conv_used: bool) -> tuple[bool, str]:
    """Decide whether an answer must wait for human review.

    Error responses never queue: a failed turn must surface to the user
    immediately so the cause (bad API key, outage, ...) is actionable.
    ENABLE_HUMAN_REVIEW=on queues everything else; otherwise rescue-path
    and low-confidence answers are auto-queued.
    """
    meta = response.metadata or {}
    if meta.get("error"):
        return (False, "")
    trace = meta.get("trace") or []
    rescue = any(t.get("node") in ("verify", "wide_search") for t in trace)
    low_conf = response.confidence_score < 0.5
    if settings.enable_human_review:
        return (True, "human review enabled")
    if meta.get("error") or rescue or low_conf:
        return (
            True,
            f"error={bool(meta.get('error'))} rescue={rescue} low_confidence={low_conf}",
        )
    return (False, "")


def _queue_response(conv, query, response, reason: str) -> dict:
    """Insert a review_queue item; returns the inserted row."""
    return db.add_review_item(
        conv["id"] if conv else None,
        query,
        response.result,
        agent_type=response.agent_type,
        citations=response.citations,
        trace=response.metadata.get("trace"),
        confidence=response.confidence_score,
        reason=reason,
    )


@router.get("")
async def list_agents():
    """List available agents.

    Returns:
        List of agent types and descriptions.
    """
    return {
        "agents": [
            {
                "type": "due_diligence",
                "name": "Due Diligence Agent",
                "description": "Analyze investment opportunities and conduct due diligence",
            },
            {
                "type": "term_sheet",
                "name": "Term Sheet Extractor",
                "description": "Extract structured data from term sheets",
            },
            {
                "type": "lp_report",
                "name": "LP Report Generator",
                "description": "Generate quarterly LP reports",
            },
            {
                "type": "compliance",
                "name": "Compliance Checker",
                "description": "Check regulatory compliance of documents",
            },
            {
                "type": "cross_doc",
                "name": "Cross-Document Comparison",
                "description": "Compare and synthesize information across multiple documents",
            },
        ]
    }


@router.post("/execute")
async def execute_agent(query: AgentQuery):
    """Execute an agent with a query.

    Args:
        query: Agent query with query text and agent type.

    Returns:
        Agent execution result.
    """
    _require_api_key()
    try:
        router_agent = get_router_agent()
        conv, history, allowed = _conversation_context(
            query.conversation_id, query.project_id
        )
        cost_before = cost_tracker.get_summary()["total_cost"]
        allowed = _scope_tagged(allowed, query.tagged_filenames)
        result = router_agent.invoke(
            query=query.query,
            agent_type=query.agent_type,
            conversation_history=history,
            allowed_filenames=allowed,
        )
        _push_run(query.query, result, cost_before)
        _record_audit(query.query, result)
        queue, reason = _should_queue(result, conv is not None)
        if queue:
            if conv is not None:
                db.add_message(conv["id"], "user", query.query)
            item = _queue_response(conv, query.query, result, reason)
            result.metadata["review"] = {"id": item["id"], "status": "pending"}
        elif conv is not None:
            _persist_turn(conv, query.query, result)
        return {
            "agent_type": result.agent_type,
            "result": result.result,
            "metadata": result.metadata,
        }
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Agent execution failed: {str(e)}",
        )


@router.post("/execute/stream")
async def execute_agent_stream(query: AgentQuery):
    """Execute an agent with streaming SSE output.

    Each event is a JSON object with a "node" field (the pipeline step)
    and an "update" field (the state update from that node). The final
    event     has "done": true and a "response" field with the full result.
    """
    _require_api_key()
    router_agent = get_router_agent()
    conv, history, allowed = _conversation_context(
        query.conversation_id, query.project_id
    )
    scope = _scope_tagged(allowed, query.tagged_filenames)
    if conv is not None:
        db.add_message(conv["id"], "user", query.query)

    def event_generator():
        final_response = None
        queued = False
        cost_before = cost_tracker.get_summary()["total_cost"]
        for event in router_agent.invoke_streaming(
            query=query.query,
            agent_type=query.agent_type,
            conversation_history=history,
            allowed_filenames=scope,
        ):
            if event.get("done"):
                final_response = event["response"]
            payload = {"node": event.get("node")}
            if event.get("done"):
                resp = event["response"]
                _push_run(query.query, resp, cost_before)
                _record_audit(query.query, resp)
                payload["done"] = True
                # Decide queueing before the payload leaves, so the client sees
                # metadata.review on the done event.
                queue, reason = _should_queue(resp, conv is not None)
                if queue:
                    item = _queue_response(conv, query.query, resp, reason)
                    meta = dict(resp.metadata)
                    meta["review"] = {"id": item["id"], "status": "pending"}
                    queued = True
                else:
                    meta = resp.metadata
                payload["response"] = {
                    "agent_type": resp.agent_type,
                    "result": resp.result,
                    "citations": resp.citations,
                    "metadata": meta,
                }
            else:
                payload["update"] = event.get("update", {})
            yield f"data: {json.dumps(payload)}\n\n"
        if (
            conv is not None
            and final_response is not None
            and not queued
        ):
            db.add_message(
                conv["id"],
                "assistant",
                final_response.result,
                agent_type=final_response.agent_type,
                citations=final_response.citations,
                trace=final_response.metadata.get("trace"),
                confidence=final_response.confidence_score,
                is_error=bool(final_response.metadata.get("error")),
            )

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
