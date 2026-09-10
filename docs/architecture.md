# Architecture

Status: discovery baseline (Phase 0). Refresh after each migration phase.

## System topology

Two separately deployed services (kept in separate repositories):

```text
Browser
  -> Next.js App Router (Vercel)          jsnc-demo-automation-nextjs/frontend
       marketing pages + demo tools
       /api/* proxied server-side to the Python service
  -> FastAPI + LangGraph (Docker host)    jsnc-demo-automation-python
       agent execution and SSE
       document extraction/chunking/retrieval (Chroma today)
       review workflows, regulatory feeds, MS Graph/OneDrive
  -> PostgreSQL (local: docker compose; prod: Supabase or managed PG)
  -> Object storage (prod: Supabase Storage or S3-compatible)
  -> External AI providers (DeepSeek today; OpenAI/Anthropic/Kimi later)
```

Target: the Next.js app becomes a SaaS control plane (Better Auth + Prisma on
PostgreSQL). The Python service keeps the AI engine, receives an authenticated,
short-lived internal identity context from Next.js, and independently enforces
the same tenant boundary. The browser never supplies a tenant ID directly to
Python.

Current state (2026-09): the control plane is live — Next.js 16 + React 19,
Prisma 7 on PostgreSQL, Better Auth magic link (Resend) + organisation plugin,
gated workspace pages, and BFF `/api/v1/*` handlers with session-derived
tenancy. The Python service remains as before (open routes, SQLite/Chroma) and
the Next.js proxy to it is a fallback rewrite: local route handlers take
precedence, Python serves the remaining `/api/*` paths until Phase 4 adds
internal auth and org context.

## Frontend (jsnc-demo-automation-nextjs/frontend)

- Next.js 16 App Router + React 19 (app code at the repo frontend root, no
  `src/`), Tailwind 3, no UI component library.
- Two apps in one codebase: static marketing site (`/products`, `/services`,
  `/work`, `/blog`, `/contact`, `/support`, `/compliance`) and the workspace
  (`/chat`, `/documents`, `/mailbox`, `/radar`, `/review-hub`,
  `/telemetry`, `/summary`, `/config`, `/eval`, `/workbench/*`, `/settings`),
  gated by Better Auth session checks (`app/(app)/layout.tsx` plus an
  optimistic cookie check in `proxy.ts`).
- Local route handlers: Better Auth at `/api/auth/[...all]`, BFF tenant
  endpoints at `/api/v1/*`. The Python proxy is a fallback rewrite for the
  remaining `/api/*` and `/health` paths (`BACKEND_URL`, default
  `http://127.0.0.1:8000`).
- Auth: Better Auth magic link via Resend, DB sessions in HTTP-only cookies;
  organisation plugin for tenancy/roles/invitations. The pre-SaaS BYOK
  mechanism (`localStorage` DeepSeek key) is dev-only behind
  `NEXT_PUBLIC_BYOK_DEV` and off in normal mode.
- All other data access is client-side fetch against the same-origin proxy
  (`lib/api.ts`); SSE is consumed by a hand-rolled reader.

## Python service (jsnc-demo-automation-python)

### API surface (routes)

| Prefix | Purpose | Notes |
|---|---|---|
| `/health` | liveness + `server_key_configured` | no auth |
| `/api/agents` | list, `execute`, `execute/stream` (SSE) | execute gated on API key (BYOK or server) |
| `/api/documents` | upload/list/stats/tags/assign/reindex/download/delete | no auth |
| `/api/clients`, `/api/projects` | workspace CRUD | no auth, not org-scoped |
| `/api/conversations` | conversations + messages | no auth |
| `/api/review` | human review queue (approve/reject) | no auth |
| `/api/telemetry` | run + cost records, reset | no auth |
| `/api/regulatory` | SFC/HKMA feed, poll, status | no auth |
| `/api/graph/mail` | MS Graph mail read/drafts/reply | no auth |
| `/api/onedrive` | OAuth connect/browse/import/disconnect | no auth |
| `/api/summary` | weekly/monthly digest | no auth |
| `/api/assurance` | manifest + downloadable assurance pack | no auth |
| `/api/eval/results` | eval output artifact | strips `cv_*` questions at serve time |

### Persistence today (all local, all to migrate)

- `data/platform.db` — SQLite: clients, projects, documents, tags,
  document_tags, onedrive_tokens (plaintext OAuth tokens), regulatory_feed,
  conversations, conversation_messages, review_queue.
- `data/llm_cache.db` — SQLite TTL cache for classification/retrieval.
- `data/audit.db` — SQLite hash-chained audit log.
- `data/model_versions.db` — SQLite model-version records.
- `data/graph_drafts.db` — SQLite demo-mode mail drafts.
- `data/chroma/` — Chroma collections (one global `pe_documents` + one
  collection per document filename).
- `data/uploads/` — raw uploaded files on local disk.

### Module-global state

- `_vector_store`, `_router_agent` singletons (`src/api/deps.py`);
- compiled LangGraph (`_compiled_graph`);
- in-memory cost tracker / run log;
- `_auto_signals_cache` retrieval-routing cache;
- Graph access-token in-memory cache;
- regulatory `poll_loop()` asyncio task started in lifespan
  (`enable_regulatory_poll`).

Every global above must become tenant-aware or queue-backed before
multi-tenant production use (see threat model).

### Streaming

`POST /api/agents/execute/stream` yields LangGraph node updates as SSE events
then a final `{done, response}` event. The generator is synchronous inside an
async endpoint (blocks the event loop); `X-API-Key` context survives streaming
via `BaseHTTPMiddleware` + contextvar.

## Deployment

- Local dev: FastAPI on :8000 (uvicorn), frontend on :3000, PostgreSQL via
  `docker compose up -d postgres` (this repo's `compose.yaml`, pgvector image).
- Production (recommended by owner, 2026-09): Next.js on Vercel with
  `BACKEND_URL=https://<hosted-python-api>`; FastAPI via the existing Dockerfile
  on a persistent container host; PostgreSQL on Supabase (or region-appropriate
  managed PG later); object storage on Supabase Storage/S3. The Next.js rewrite
  (`/api/*` -> `BACKEND_URL`) remains, with authenticated tenant endpoints
  moving to a BFF route handler that injects a signed internal identity
  (Phase 1/4). Do not target a single-Vercel-deployment monorepo until the
  Python service is stateless (no local disk, no process-lifetime state).

## Request IDs

Every HTTP request gets an `X-Request-ID` (incoming header honoured when
safe), echoed on the response, kept in a contextvar
(`src.utils.request_ctx`), attached to structured log records, and included in
the JSON envelope for unhandled 500s (`RequestContextMiddleware`).

## Compliance posture

See `docs/compliance.md` for the regulatory-positioning TODO and privacy
controls mapping.
