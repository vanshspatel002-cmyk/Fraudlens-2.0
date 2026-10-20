# Presentation workflow checklist — 18 October 2026

Branch: `presentation/customer-workflow-20261018`, based on `8e9a10f`.
The eight pre-existing documentation changes/untracked notes are preserved.
No applicable AGENTS.md was found in the workspace or its parent directories.

| Requirement | Existing behavior / dependencies | Focused change | Verification |
| --- | --- | --- | --- |
| Baseline and preservation | FastAPI, TanStack React; durable worker; PostgreSQL adapter and explicit SQLite rollback | New private consistent backups before additive migration; read actual configured tables | Read-only PG inventory, backup manifests, isolated restore/tests |
| Field suggestions | Intake uses native controls and FormData, image previews | Reusable accessible portal combobox, fictional separate catalog, dependent warnings, configuration | Keyboard/pointer/touch browser checks, narrow layouts, typecheck |
| Customer authentication/ownership | Reviewer PBKDF2 accounts and hashed bearer sessions; applicant receipt capabilities; manually linked dashboard | Reuse authentication primitives for customer accounts/sessions and transactional case ownership; protected UI and owner-scoped endpoints | Isolated integration tests for login, expiry, logout, ownership and role boundaries |
| Two ordinary tabs | Reviewer sessionStorage is already tab scoped; request helper adds admin bearer indiscriminately | Explicit customer request scope, independent expiry/logout, server role enforcement | Two pages in one Chrome context, refresh and forced expiry |
| Submission | UUID4 idempotency, decoded upload validation, atomic acceptance/job/receipt, file cleanup | Include ownership and owner identity in same transaction and idempotency fingerprint; immediate confirmation | Claims/underwriting integration, retries and failure injection |
| Dashboards | Reviewer queue/detail and receipt tracker exist; dashboard only holds linked cases in memory | Persisted owner list/detail, real event timeline, evidence response, nonoverlapping polling; expose processing separately | Cross-tab outcomes, list/detail privacy, network recovery and mobile checks |
| Honest PDF | Persisted run-specific JSON snapshots and browser print report | Durable authenticated PDF versions from snapshots, restrained branding, detailed real results and limitations | Text/page/render inspection; no model call during read/generation |
| Preview/download | Existing print view; no durable backend PDF | Authenticated blob preview/download, object URL cleanup, pending/failure/retry and mobile fallback | PDF header/authorization/idempotency tests and actual browser download |
| Human decisions | Server reviewer roles, audit history, revision count and reviewed-run attribution | Block active processing, validate reviewed run/evidence, explicit failed-analysis manual override, separate public explanation | Race/stale/fallback/role tests; four workflow outcomes |
| Persistence/storage | Qualified PostgreSQL adapter, private schema, bounded pool, host-local evidence | Verify real tables/history; explicit additive migration; persistent-volume configuration with startup safeguards | Disposable PG schemas and actual preservation checks; no silent SQLite fallback |
| Recovery/failure | Durable bounded worker recovery and stopped Gemini ledger | Preserve controls; errors/retries for new paths | Controlled fixture failures; real deterministic pipeline with stopped provider |
| Deployment/responsiveness | VITE_API_BASE_URL, CORS, runtime pins, separate worker helper | Document exact prerequisites, migration/startup/volume commands and unverified hosting | Production build, readiness without AI, 390/768/laptop browser viewports |
| Rehearsal/handover | Existing isolated Chrome harness and historical verification artifacts | Final-code authenticated four-case rehearsal and update four requested handover files | New private output directory; retain failures, distinguish fixtures/live services |

No push, deployment, external billing change, model-budget reset, or database reset is authorized.
