# Compliance and privacy notes

## Open question — "FCP"

TODO(confirm-with-principal): the PRD refers to an "FCP" requirement whose
exact meaning is unconfirmed. The intended reference may be financial-crime
prevention, financial-crime compliance, or another framework. Do not invent an
interpretation. Until confirmed, position the product as supporting
evidence for finance-sector customer due diligence without claiming "FCP
compliance", "SFC approval", "HKMA approval" or general legal compliance.

## Product claims must stay careful

Use language such as "privacy-conscious", "configurable retention",
"human-reviewed workflow" and "provider policy controls". Never claim
regulatory approval or autonomous financial decision-making.

## Controls aligned to principles

| Principle | Mechanism |
|---|---|
| Purpose limitation | Per-org retention policy, classification on documents |
| Least privilege | Roles (`owner`/`admin`/`analyst`/`reviewer`/`viewer`), org-scoped queries |
| Tenant isolation | See `security-threat-model.md` (T1–T3) |
| Configurable retention/deletion | Retention deadlines + deletion jobs (Phase 3) |
| Data processor/provider register | `provider_configs` policy metadata (no raw secrets) |
| Auditability | `audit_events` with tamper-evident linkage + request IDs |
| Human review | Review workflow for consequential outputs |
| Model/provider/region records | `ai_runs` provider/model metadata per run |
| No training on customer data | Explicit per-org provider policy flags |
| Incident + export/delete paths | Deletion jobs; documented export path |
| Redaction/sensitive-data classification | Redaction modes in ingestion/agent paths |

## Operational hygiene already applied (Phase 0)

- `scripts/eval_results.json` (eval output containing personal data) is no
  longer tracked; the `/api/eval/results` endpoint tolerates its absence.
  Regenerate locally when running evals. A history purge
  (`git filter-repo` + force push) is recommended before the repository is
  shared more widely.
- Demo keyword tables in `src/tools/search.py` reference sample documents
  whose subjects are real named individuals (CVs etc.). Replace the demo
  corpus with synthetic data before any external demo/production use.
