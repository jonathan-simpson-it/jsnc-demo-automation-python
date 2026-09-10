# Migration notes

Status: Phase 0 baseline. Companion to `docs/architecture.md` and
`docs/security-threat-model.md`.

## Target (from PRD-saasification.md)

Single-workspace demo -> self-service multi-tenant SaaS for Hong Kong SMEs
(finance/compliance document work, human-reviewed AI). The demo behaviour is
preserved unless a change is required for tenant security. PostgreSQL becomes
the system of record; Prisma owns all DDL/migrations; the Python service keeps
LangGraph/ingestion/retrieval and talks to the same database with psycopg3 raw
SQL (no second ORM).

## Phase sequence (planned)

- **Phase 0 (complete):** green tests, request IDs, structured errors,
  secrets/data hygiene, docs, local pgvector Postgres. No schema migration.
- **Phase 1 (control plane landed, 2026-09):** Next.js 16 + React 19 upgrade
  (no-`src` layout, app under `frontend/app`), Prisma 7 schema with Better
  Auth tables + org-scoped `client` table, Better Auth magic link via Resend
  (dev console fallback without a key), organisation plugin with
  analyst/reviewer/viewer roles, sign-in/invitation/settings UI, session-gated
  workspace pages (`app/(app)/layout.tsx` + `proxy.ts`), BFF `/api/v1/clients`
  with session-derived organisation, BYOK demoted to `NEXT_PUBLIC_BYOK_DEV`.
  Integration tests cover magic-link single-use, invitation single-use and
  expiry, and cross-organisation isolation on a disposable `payo_test`
  database. Remaining for this phase: nothing blocking; provider policy and
  billing arrive in Phase 5.
- **Phase 2:** Python service to PostgreSQL. Replace sqlite3 with a psycopg3
  pool; port repository functions without changing their shape; add
  `organisation_id` scoping everywhere; no production path depends on
  `data/platform.db`.
- **Phase 3:** object storage + retrieval. Uploads move to object storage
  behind short-expiry signed URLs; Chroma production persistence replaced by
  pgvector (same `VectorStore` interface; Chroma kept as dev fallback until an
  embedding key exists); deletion jobs cover every representation.
- **Phase 4:** Python boundary hardening — internal-auth JWT middleware on all
  routes, wildcard CORS removed, SSE carries tenant/actor/request ID, OneDrive
  OAuth `state` validation, remove dead `src/ui/routes` stub.
- **Phase 5:** providers/credits/Stripe — adapter interface, config-driven
  catalog, credit ledger, Stripe Checkout/portal/webhooks.
- **Phase 6:** OAuth connectors (Graph mail first).

## Frontend/backend boundary notes

- The Next.js rewrite that proxies `/api/*` to Python is now a **fallback
  rewrite**: local route handlers (`/api/auth/*`, `/api/v1/*`) take precedence
  and the proxy only serves paths Next does not own. Python routes are still
  unauthenticated (Phase 4); the Next gate currently protects workspace pages
  only, not direct calls to the Python service.
- Dev-only behaviours to replace before production: magic links/invitations
  print to the dev console when `RESEND_API_KEY` is unset (production
  hard-fails instead), and the legacy BYOK key dialog is behind
  `NEXT_PUBLIC_BYOK_DEV`.

## Pre-public-presentation checklist

- Replace demo keyword tables in `src/tools/search.py` that reference sample
  documents about real named individuals (CVs etc.) with synthetic data, or
  remove the demo corpus from any external demo environment.
- Purge `scripts/eval_results.json` personal data from git history
  (`git filter-repo` + coordinated force push) before wider distribution.

## Local state being replaced (see architecture.md)

SQLite databases in `data/`, Chroma in `data/chroma/`, `data/uploads/`,
module-global singletons/schedulers, in-memory cost/run logs.

## Known simplification targets (ponytail notes)

- Python opens a fresh sqlite3 connection per repository call and sometimes
  several per request; psycopg3 pooling replaces this.
- Three near-identical thread-local SQLite helpers (LLMCache, AuditLog,
  ModelVersionTracker) could share one helper.
- Chroma keeps each chunk in a per-document collection AND a global
  collection with parallel search loops; pgvector collapses this to one table
  with metadata filtering.
- The LangGraph `review` node is vestigial (its state field is never set);
  real review gating lives at the API layer. Reconcile during Phase 4.
- Sync SSE work runs inside async endpoints and blocks the event loop;
  `invoke` vs `invoke_streaming` duplicate final-response assembly.
- Frontend: duplicated markdown renderers, date helpers, `friendlyError`,
  dead `api.ts` exports, upload-progress estimator complexity, window-event
  coupling for the key dialog — simplify as each file is touched.

## Testing gates per phase

- Next.js typecheck + production build.
- Python unit/API tests (`uv run pytest tests/`); playwright E2E in
  `tests/test_webapp.py` skips when playwright is not installed.
- Migration tests against a disposable PostgreSQL.
- Tenant-isolation tests (cross-tenant must fail safely).
- Lint/format; automated search for wildcard CORS, raw secrets, localStorage
  API keys, global tenant tables, production filesystem persistence.

## Environment

`compose.yaml` in this repo runs pgvector Postgres for local dev:
`docker compose up -d postgres`; URL
`postgresql://payo:payo_dev_password@localhost:5432/payo` (dev-only).
Production requires a paid/managed PostgreSQL with backups and region choice;
keep application code portable so the database can move later.
