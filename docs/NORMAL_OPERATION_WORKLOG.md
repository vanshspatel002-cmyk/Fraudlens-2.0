# Final presentation implementation record — 23 October 2026

Inspected baseline `0024843f5bb9ab370570afffa1dbf336ed301b41`; unrelated staged,
API CORS and frontend transport/evidence edits were preserved. Reused installed
CLIP/EasyOCR/ReportLab/psycopg/Playwright tools without upgrades. Private consistent
database/evidence/control backups preceded scoped mutations.

Focused changes: slot-aware photo prompts (unchanged 0.175/0.020 thresholds),
relevance separate from OCR, API background CLIP warmup, dedicated-worker OCR
heartbeat, read-only provider readiness, embedded-NUL EXIF JSON repair preserving
original bytes, pre-transaction hash/metadata work, aware incident/coordinate
wiring, intended-ODO material guard, accurate skipped-check applicability,
fallback/model attribution, saved shadow rounding and immutable renderer v9.
Report metadata/basis reads no longer transfer historical PDF/thumbnail blobs;
version metadata uses one joined query. No timeout increase or score replacement.

Actual customer UI submissions: claims `case-95a28aea367c` (4 photos, 11.281 s),
underwriting `case-ac757ae6f8b1` (6 distinct same-car photos, 19.453 s), isolated
schema `fraudlens_validation_panel_20261022`. Two fresh Gemini 503s stop claims AI;
underwriting has zero HTTP generation after pause. Both failed durable runs save
local findings, incomplete assessments, PDFs and human evidence-request/customer
updates. Neither new run qualifies as successful live processing. Each final PDF
has 11 pages; all pages rendered/inspected and native Chrome preview/download
verified. Final frontend label also distinguishes saved system fallback.

Actual request accounting: 15 preserved + 2 new = 17, scoped ceiling 45, unused
28 closed. Normal provider remains paused for the fresh external service blocker.
No historical jobs, private applicant test evidence, billing action or deployment.
The final pilot services use original controls/configuration; original table and
evidence comparisons are recorded in the final receipts.

[Final changed files/tests/measurements](FINAL_PRESENTATION_VERIFICATION.md),
[operating handover](FINAL_PRESENTATION_HANDOVER.md),
[shareable artifacts and attribution](final_presentation/README.md).
Older implementation evidence is preserved below.

---

# Normal local operation — implementation record

Baseline inspected on 22 October 2026: branch `repair/analysis-pipeline-20261020`,
commit `835ae28103060c0a087da63eac4a979d22bfd47f`. Existing staged documentation
and frontend/API edits are unrelated and will be preserved. No applicable
AGENTS.md was present in the repository or its parent directories.

Before editing: API and worker use PostgreSQL `fraudlens_pilot`, Gemini
`gemini-3.5-flash`, `gemini3_defaults_v2`, and the same original session/quota
ledgers. Eleven attempts are retained; this task permits at most thirty new
attempts (cumulative 41). Generation is stopped by historical diagnostic controls.
Private backups of the index, working patches and both controls were taken.

## Planned changes and potential effects

| Area / files | Change and possible effect | Verification |
|---|---|---|
| `src/session_budget.py`, new operating policy, startup/configuration | Append an audited normal-operation migration to the original ledger. Central daily/case/agent limits, task ceiling, manual pause and transient recovery. Existing events/recoveries remain untouched. Provider calls become possible only for worker job context in the pilot schema. | Offline accounting/concurrency/restart/circuit tests, consistent service environments, before/after ledger prefixes |
| `src/provider_receipts.py`, `src/llm.py` | Normal-operation receipts before parsing/storage; bounded retries, no key rotation on blocked provider errors. | Actual SDK serialization regressions; controlled failures, receipt persistence |
| `src/assessment_explanation.py`, `src/risk_presentation.py`, production policy | Version material coverage independently of execution. Metadata/experiments/history gaps remain visible. Preserve model output; freeze effective routing guard for material gaps. | Claims/underwriting fixtures; incomplete remains neutral; no numeric production score |
| `src/report_visuals.py`, `src/report_pdf.py`, damage plausibility check | New renderer version, precise heuristic wording, saved-data visuals and material-gap summary. Preserve old snapshots/artifacts. | PDF extraction, all-page rendering/visual inspection, existing report tests |
| Historical audit/batch tooling and admin status interpretation | Read-only classification and dry-run manifest. Enqueue requires an explicit separate operator command; no historical batch in this task. | Self/temporal exclusion tests, duplicate prevention, unchanged original decisions |
| Browser verification tooling | One fictional ordinary customer claims submission and explicit fictional reviewer action on that new case. | Real UI/API/worker/DB/report/customer checks, timings/memory and request accounting |

Dependencies: reuse installed Google GenAI 2.18.1, Pydantic, FastAPI, psycopg,
ReportLab, PyMuPDF and Playwright/Chrome. No package upgrades planned. Frontend
typecheck/build and focused backend regressions precede handover. Underwriting
live evidence/validation is deferred; shared software verification uses fixtures.
Historical reprocessing is preparation only. No push, deployment or billing change.

## Final files and verification

Paths below are relative to `FraudLens-2.0-Backend` unless a different prefix is shown.

| Files | Final purpose |
|---|---|
| `src/operating_policy.py`, `src/session_budget.py` | Explicit retained-history migration; normal/task/daily/per-case controls; atomic shared quota charge, pause/configure and recoverable circuit |
| `src/llm.py`, `src/provider_receipts.py`, `src/validation_budget.py` | Normal scoped requests and receipts, bounded retries/pacing, exact received-response reuse, changed-input replay protection, historical job context |
| `src/coverage_policy.py`, `src/assessment_explanation.py`, `src/risk_presentation.py`, `src/agent/production_policy.py` | Versioned material sufficiency and effective-routing guard, preserving raw model output and no numeric production score |
| `src/api.py` | Own changes only: run stage timings, central perception retry limit, authenticated operational status and retrospective report label. Pre-existing CORS edits excluded from commit |
| `src/checks/damage_plausibility.py`, `src/report_pdf.py`, `src/report_visuals.py` | Precise research heuristic language, renderer v5, real comparison bar and concise material-gap/action summary; older artifacts retained |
| `scripts/operate_provider.py`, `scripts/diagnose_gemini.py`, `scripts/start_pilot.ps1` | Strict process configuration, consistent control backups, explicit operator controls and truthful normal/legacy status |
| `scripts/claims_batch.py`, `scripts/audit_analysis_history.py` | Read-only claims manifest and future resumable explicit enqueue, actual sufficiency classification; no historical execution |
| `scripts/verify_normal_claims.py` | Repeatable guarded one-case fictional customer/admin verification; private credentials and resumable accepted-case checkpoints |
| `test_normal_operation.py`, `conftest.py` | Meaningful controls/concurrency/recovery/receipt/coverage/guard regressions; test isolation documentation |
| `FraudLens-2.0-Frontend/src/experience/reviewPresentation.ts`, `CaseReview.tsx` | Saved model/effective-routing/material-gap presentation. Pre-existing evidence-image edits excluded from commit |
| `GEMINI_DIAGNOSTICS.md`, `ANALYSIS_REPAIR_HANDOVER.md`, `docs/NORMAL_OPERATION.md`, this file, `docs/normal_operation/` | Current status, exact commands/limits/rollback, preserved historical evidence, sanitized audit and fictional sample artifacts |

Provider regression run: **159 passed, seven live-only skipped**. Workflow/customer/
report/risk run: **130 passed**. These suites overlap. Frontend typecheck and
production build passed. Ordinary tests made zero external model calls. Existing
visual fixture tools generated all display categories and incomplete variants;
browser checks covered unknown scores/categories, stale/historical runs and narrow
mobile layouts without overflow/JavaScript errors. Underwriting remains a software
fixture result, not a live claim of six-view validation.

Actual ordinary claims case `case-e4f345a50f26`: first run retained a real 503;
explicit UI retry `bbb9ed14d1c28c961b74093212aa8a6e` completed with one fresh
perception, two fresh agent turns, one real history tool exchange and persisted
schema-valid results. Required evidence remains incomplete, neutral UI/PDF,
effective escalation. A fictional human requested evidence only on this new case;
the customer saw the update. Authorization/ownership checks passed.

Four new generation attempts; original eleven retained, total fifteen. Unused
task allowance twenty-six closes at handover. No metadata call, historical job,
billing change, deployment or push. Normal operation stays enabled with one active
case, daily thirty, per-case sixteen and agent eight, subject to stricter original
quota controls. Google account headroom was not established.

Actual claims/underwriting-fixture PDFs are nine pages each, all pages extracted,
rendered and visually inspected. Preview/download bytes matched. Headless native
Chrome preview did not paint pages, so native/manual preview pixels are not claimed.
Acceptance 42.765 s, successful pipeline 164.601 s, peak worker about 986 MiB;
local model initialization, a 78.248 s experimental classifier and PostgreSQL
round trips are material limits. No timeout increase was used.
The final API restart required 663.875 s of model warmup, peak about 1.56 GiB,
with less than 1 GiB free memory. Its readiness was verified after warmup;
this cold-start limitation remains open.

Private before/after comparison verified every original business row/report/
decision/account unchanged; existing login cleanup removed only expired sessions.
Dry-run claims estimate: minimum 1,625 calls, upper cap bound 10,688, zero enqueues.
The original staged index and unrelated working edits are retained separately.
See [artifacts and verification limitations](normal_operation/README.md) and
[operating commands/rollback](NORMAL_OPERATION.md).
