# Focused patch files and verification

Baseline `b2eff6b`; no later commits present when inspected. Existing unrelated
staged documentation, API CORS and frontend transport/evidence edits were kept.
The case-switch fix touches the polling cleanup needed by the new saved-case
selector; it does not remove the existing transport cancellation protections.

Backend paths below are relative to `FraudLens-2.0-Backend`.

| Files | Purpose |
|---|---|
| `src/processing_outcome.py` | Separate durable status, local completion, provider limitation and proven historical derived review summary |
| `src/api.py` | Atomic terminal status/snapshot persistence, real evidence-load failures, strict observation eligibility, safe customer job response, batched queue display, protected workspace navigation and explicit manual-review guard |
| `src/runtime_store.py` | Derived view without historical mutation; preserve proven partial state on same-run/restart reconciliation |
| `src/customer_auth.py` | Safe customer status/message/timeline, retain human outcome and evidence requests |
| `src/perception.py`, `src/checks/base.py` | Exact hash/model/prompt/schema/profile cache contract; never pass incompatible observations to normal checks |
| `src/risk_presentation.py` | Neutral incomplete risk; truthful partial-review explanation, no numerical/routing change |
| `src/report_pdf.py`, `src/report_visuals.py` | Renderer v11, compact partial banner, reviewer diagnostics appendix, preserved older renderers/artifacts |
| `src/pg_migrations.py`, `migrations/postgresql/003_partial_review.sql` | Explicit status-check extension; old payload/status and active-job constraints remain |
| `scripts/start_review.ps1`, `scripts/verify_review_configuration.py` | Panel/Pilot selection, API configuration check and worker inheritance of actual API settings instead of shell defaults |
| `scripts/claims_batch.py`, `scripts/audit_analysis_history.py` | Recognize terminal partial outcomes; batch remains frozen and stops on an insufficient prior result |
| `test_partial_review.py`, `test_partial_review_postgres.py`, `test_durable_pilot.py` | Outage/local checks, role/ownership, all manual actions, persistence failures, exact cache, migration, restart and no-repeat generation tests |

Frontend paths are relative to `FraudLens-2.0-Frontend/src/experience`:

| Files | Purpose |
|---|---|
| `WorkspaceSelector.tsx`, `Admin.tsx` | Visible active dataset and actual saved-case buttons; case-switch cleanup cancels only its own polling request |
| `CaseReview.tsx`, `reviewPresentation.ts` | Partial-review wording, original technical status/diagnostics, accurate timeline and explicit manual acknowledgement |
| `Dashboard.tsx`, `Tracker.tsx` | Saved/awaiting-review customer wording without raw provider errors |
| `Intake.tsx` | Treat partial completion as terminal in submission polling; use the safe saved/awaiting-review message |
| `shared.tsx` | Protected workspace API mapping; preserve pre-existing transport changes |
| `../scripts/test-review-presentation.mjs` | Both-type partial wording, saved source/formatting and run-scoped historical timeline regression |

Updated handover/verification documents and this artifact directory contain safe
receipts, fictional case screenshots and original licensed-photo attribution.
No credentials, applicant receipt secrets, database backups or provider ledgers
are committed. No Supabase Storage migration or dependency upgrade.

## Checks actually performed

| Check | Result |
|---|---|
| Partial + photo admission + customer regressions | 63 passed, 492.87 s; buffered output caused a late summary |
| New isolated partial suite | 12 passed, 101.90 s; overlaps the preceding suite |
| Engine/cache/recovery/PDF regressions | 43 passed, 54.31 s |
| Real disposable PostgreSQL, both case types | 2 passed, 140.58 s |
| API-to-worker configuration drift guard | 1 passed, 12.57 s |
| Changed evidence fails before any provider operation | 1 passed, 10.99 s |
| Frontend typecheck and production build after case-switch fix | Both exit 0; 89.676 s / 93.563 s |
| Node presentation assertions | Passed, no network |
| Real same-context Chrome walkthrough | Both saved cases; dataset buttons, partial wording, customer update, native PDF and mobile overflow checks |
| PDF final layout | 11 pages each; all 22 rendered/inspected; no almost-empty summary spill page |
| Provider controls | Byte-identical to this task's backup, 17 cumulative attempts, 0 new |

Earlier failing assertions expected the old whole-job failure status and were
updated to the intended partial contract. An invalid fixture hash was corrected.
An actual saved-case navigation race and first-page spill were repaired before
the final successful rehearsal. No test is counted as successful fresh AI.

Repeat focused checks from the backend:

```powershell
.\venv\Scripts\python.exe -m pytest test_partial_review.py -q
$env:FRAUDLENS_TEST_POSTGRES='1'
.\venv\Scripts\python.exe -m pytest test_partial_review_postgres.py -q
Remove-Item Env:FRAUDLENS_TEST_POSTGRES
```

Tests use controlled observations/providers and disposable schemas. Ordinary test
transport isolation prevents external model calls. Migration 003 was explicitly
applied to both existing datasets after consistent private backups. Original
business rows and old report prefixes were compared again afterward; only new
renderer snapshots/artifacts and the rehearsal's authentication sessions were
permitted additions. Old human decisions and ownership are unchanged.
