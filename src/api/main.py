"""FastAPI application for PE AI Engineering API."""

import asyncio
import json
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from config.settings import settings
from src.api.deps import set_vector_store
from src.api.key_middleware import ApiKeyContextMiddleware
from src.api.routes.agents import router as agents_router
from src.api.routes.documents import router as documents_router
from src.api.routes.summary import router as summary_router
from src.api.routes.clients import router as clients_router
from src.api.routes.projects import router as projects_router
from src.api.routes.onedrive import router as onedrive_router
from src.api.routes.conversations import router as conversations_router
from src.api.routes.review import router as review_router
from src.api.routes.telemetry import router as telemetry_router
from src.api.routes.regulatory import router as regulatory_router
from src.api.routes.graph_mail import router as graph_mail_router
from src.vector_store.chroma import VectorStore


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager."""
    vector_store = VectorStore()
    set_vector_store(vector_store)
    poll_task = None
    if settings.enable_regulatory_poll:
        from src.regulatory.scheduler import poll_loop

        poll_task = asyncio.create_task(poll_loop())
    yield
    if poll_task is not None:
        poll_task.cancel()


app = FastAPI(
    title="JonathanSimpson AI Platform",
    description="AI-powered Private Equity workflow automation",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.add_middleware(ApiKeyContextMiddleware)

app.include_router(documents_router, prefix="/api/documents", tags=["documents"])
app.include_router(agents_router, prefix="/api/agents", tags=["agents"])
app.include_router(summary_router, prefix="/api/summary", tags=["summary"])
app.include_router(clients_router, prefix="/api/clients", tags=["clients"])
app.include_router(projects_router, prefix="/api/projects", tags=["projects"])
app.include_router(onedrive_router, prefix="/api/onedrive", tags=["onedrive"])
app.include_router(conversations_router, prefix="/api/conversations", tags=["conversations"])
app.include_router(review_router, prefix="/api/review", tags=["review"])
app.include_router(telemetry_router, prefix="/api/telemetry", tags=["telemetry"])
app.include_router(regulatory_router, prefix="/api/regulatory", tags=["regulatory"])
app.include_router(graph_mail_router, prefix="/api/graph/mail", tags=["graph-mail"])


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {
        "status": "healthy",
        "version": "0.1.0",
        "server_key_configured": bool(settings.deepseek_api_key),
    }


@app.get("/api/eval/results")
async def eval_results():
    """Return eval results JSON, excluding personal candidate CV questions."""
    result_file = Path("scripts/eval_results.json")
    if not result_file.exists():
        return {"error": "No eval results found"}
    data = json.loads(result_file.read_text())
    questions = [
        q for q in data.get("questions", [])
        if not str(q.get("id", "")).startswith("cv_")
    ]
    if len(questions) != len(data.get("questions", [])):
        total = len(questions)
        passed = sum(1 for q in questions if q.get("passed"))
        meta = dict(data.get("meta") or {})
        meta["questions"] = total
        meta["passed"] = passed
        meta["pct"] = round(passed / total * 100, 2) if total else 0.0
        data["questions"] = questions
        data["meta"] = meta
    return data
