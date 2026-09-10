# Tenant-security threat model

Status: Phase 0 baseline. The current deployment is a single-user demo: it is
NOT production multi-tenant security. This document records the threats the
SaaS migration must close and maps them to implementation phases. It is a
working checklist, not a compliance certification.

## Threat inventory

### T1 — Cross-tenant data access
A user of organisation A reads or mutates organisation B's documents,
projects, conversations, review items, telemetry or connectors.

Current state (Phase 1): the control plane is tenant-isolated — the BFF and
validated session-gated pages derive the organisation from the session, the
`client` table is org-scoped with org-scoped uniqueness, and integration
tests cover cross-organisation rejection. Python-held domain data
(documents, conversations, review queue) is still global until Phases 2–4.

Controls (Phases 1–4):
- `organisation_id` FK on every tenant-owned table; indexes begin with it.
- All Python repository functions require organisation context; queries are
  org-scoped server-side (never trust a client-supplied ID).
- Next.js derives org from the authenticated session and passes a short-lived
  signed identity to Python (`BACKEND_SERVICE_SECRET`); Python validates and
  enforces the boundary independently.
- Integration tests: cross-tenant reads/mutations fail safely.

### T2 — Direct unauthenticated access to the Python service
The Python API is currently open except the BYOK LLM gate: clients,
documents, conversations, telemetry, OneDrive, review endpoints have no auth;
CORS is `allow_origins=["*"]`.

Current state (Phase 1): workspace pages are session-gated in Next.js
(`app/(app)/layout.tsx`, `proxy.ts`) and the BFF derives tenant context from
the session, but the Python service itself is still open. Direct calls to
Python remain possible until Phase 4.

Controls (Phase 4): internal-auth middleware on every Python route; wildcard
CORS removed in production; direct calls without valid identity rejected
(401/403).

### T3 — Privilege escalation via browser-supplied identity
Browser is allowed to claim an arbitrary tenant/role.

Control (Phase 1/4): internal identity token is issued only by the Next.js
server after session + membership checks; short expiry; Python verifies
signature/expiry and re-derives org from the token, not the request.

### T4 — Session/auth token theft
XSS or logs leaking session cookies, magic links, verification tokens or
provider keys.

Controls (Phase 1, implemented): Better Auth DB sessions in HTTP-only secure
cookies; no auth tokens or provider secrets in client bundles, `localStorage`,
or logs; magic-link tokens single-use with expiry; never log tokens or API
keys (the dev-console fallback is development-only; production hard-fails
without Resend). BYOK remains behind an explicit dev flag.
Rest of this control set applies to remaining surfaces (provider keys,
connector tokens) in Phases 4–6.

### T5 — Invitation abuse
Invitation tokens replayed after acceptance, used after expiry, or granting
roles beyond the inviter's own.

Controls (Phase 1, implemented): Better Auth invitation lifecycle — single-use
tokens, 7-day expiry, `requireEmailVerificationOnInvitation: true`; role
checks on invite creation (owner/admin only in the UI; server enforces plugin
permissions). Integration tests cover replay and expiry rejection.

### T6 — Unauthorised provider/model use
A customer selects a provider/model outside the organisation policy or a
disabled/global option; billing and policy data disagree.

Controls (Phase 5): configuration-driven model catalog; `organisation_ai_policies`
permits providers/models per org; server-side enforcement on every run;
`ai_runs` records actual provider/model/actor.

### T7 — Credit double-spend / ledger forgery
A retried run spends credits twice; failed runs keep reservations; usage
records are mutable.

Controls (Phase 5): immutable `credit_ledger_entries`; reservations +
idempotency keys on charge and webhook paths; failed runs release/refund;
audit linkage via request ID.

### T8 — Stripe entitlement bypass
Browser success redirect alone grants plan entitlements.

Controls (Phase 5): entitlements granted only by signature-verified,
idempotent webhook processing; customer portal for self-service changes.

### T9 — Connector token theft / cross-tenant reuse
OAuth refresh tokens stored globally, in plaintext, or readable across
tenants; state parameter missing on the OneDrive callback (today: state is
generated but never validated — CSRF).

Controls (Phases 4, 6): per-org `connector_accounts` with encrypted token
references (secret manager / envelope encryption); minimal read-only scopes;
explicit per-org enablement; OAuth `state` validated; revoke/disconnect
removes local references; no global one-row token table.

### T10 — Data persistence outside policy / retention failures
Document originals, chunks, embeddings, caches or derived files outliving the
configured retention deadline; deletion incomplete.

Controls (Phases 3): object storage keys in `documents`; deletion jobs cover
originals/extracted text/chunks/embeddings/caches/derived files; idempotent +
retryable; configurable retention deadlines per org.

### T11 — Log/data leakage
Full prompts, model responses or raw document contents in application logs;
eval artifacts with personal data committed to git.

Controls (Phases 0/5): request-ID correlation; log redaction rules; eval
output artifacts gitignored (done in Phase 0); `ai_runs` stores only metadata
allowed by org retention policy.

### T12 — Prompt injection / indirect injection
Documents containing instructions that steer the agent or exfiltrate content.

Control (Phase 4/5): redaction modes; human review for consequential outputs;
provider-policy metadata surfaced in UI. Note: this is an ongoing research
area, not a solved problem — do not overstate protection.

### T13 — Regulatory-poller abuse / background work
A module-global poll loop or scheduled work runs once per process, cannot be
replicated safely, and may cross tenants.

Controls (Phase 4): scheduler protected/disabled in multi-instance
deployments; queue/worker table for retryable idempotent jobs.

## Controls that must NOT ship as "compliance"

This product does not self-certify as FCP/SFC/HKMA-compliant or as an
autonomous financial decision-maker. See `docs/compliance.md` for the open
regulatory TODO and the language the UI must use.
