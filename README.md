# PE AI Engineering — Python Backend

FastAPI + LangGraph backend for the JS&C private-markets AI platform: RAG over a
ChromaDB vector store, multi-agent orchestration, document management, review
queue, telemetry, regulatory feed, and Microsoft Graph mail/OneDrive
integrations.

> The frontend lives in the separate
> [`jsnc-demo-automation-nextjs`](https://github.com/jonathan-simpson-it/jsnc-demo-automation-nextjs)
> repository. Deployment topology is documented in the combined repo's
> `docs/deploy.md`.

## Quick start

```bash
pip install -e ".[dev]"
cp .env.example .env          # set DEEPSEEK_API_KEY (optional; BYOK supported)
./run.sh                      # API only when no sibling ../nextjs/frontend exists
# or: uvicorn src.api.main:app --reload --port 8000
```

First boot with an empty `data/` tree: `python scripts/ingest.py` seeds the
vector store from `data/sample/`.

- API docs: http://localhost:8000/docs
- Health: http://localhost:8000/health

## Environment variables

| Variable | Default | Purpose |
|---|---|---|
| `DEEPSEEK_API_KEY` | _(empty)_ | Server fallback key; users can also bring their own per-request `X-API-Key` |
| `DEEPSEEK_MODEL` | `deepseek-chat` | LLM model |
| `DEEPSEEK_TEMPERATURE` | `0.0` | Sampling temperature |
| `CHROMA_PERSIST_DIRECTORY` | `./data/chroma` | Vector store path (persistent disk in production) |
| `CHROMA_COLLECTION_NAME` | `pe_documents` | Collection name |
| `CHUNK_SIZE` / `CHUNK_OVERLAP` | `1000` / `200` | Document chunking |
| `RETRIEVAL_K` | `4` | Documents retrieved per query |
| `CACHE_DB_PATH` | `./data/llm_cache.db` | LLM response cache |
| `ENABLE_LLM_REWRITE` | `false` | Query rewriting |
| `ENABLE_HUMAN_REVIEW` | `false` | Human-in-the-loop review queue |
| `ENABLE_REGULATORY_POLL` | `true` | HKMA/SFC feed scheduler |
| `ONEDRIVE_CLIENT_ID` / `_SECRET` | _(empty)_ | OneDrive OAuth |
| `GRAPH_TENANT_ID` / `GRAPH_CLIENT_ID` / `GRAPH_CLIENT_SECRET` / `GRAPH_MAILBOX` | _(empty)_ | Microsoft Graph mail (drafts + inbox) |

## API surface

All routes are under `/api` except `/health`:

| Prefix | Purpose |
|---|---|
| `/api/agents` | Agent execution + SSE streaming |
| `/api/documents` | Upload, list, tag, assign, reindex, download |
| `/api/clients` · `/api/projects` | Workspace organization |
| `/api/conversations` | Chat history |
| `/api/review` | Human review queue |
| `/api/summary` | LP-report email summaries |
| `/api/telemetry` | Run logs, cost tracking |
| `/api/regulatory` | HKMA/SFC regulatory feed |
| `/api/onedrive` | OneDrive browse + import |
| `/api/graph/mail` | Mailbox list + AI drafts |

## Tests

```bash
python -m pytest tests/ -q
```

`tests/test_webapp.py` (Playwright E2E) additionally requires the Next.js app
running on `http://127.0.0.1:3000`.
