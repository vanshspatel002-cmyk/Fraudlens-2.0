# FraudLens presentation workflow — 20 October 2026

This is the current workflow guide. Earlier dated handovers and measurements are
preserved as history. Work is on `presentation/customer-workflow-20261018` based
on `8e9a10f`. No push, deployment, purchase, or model-budget reset was performed.
Implementation and initial qualification took place on 18 October; final
preservation checks and browser rehearsal continued on 20 October.

## What changed

- Customer registration/login/logout reuse the existing PBKDF2 and hashed opaque
  session primitives. Separate server session tables and explicit request scopes
  support customer and reviewer tabs in one ordinary browser context. Both
  sessions expire after eight hours; expiry affects its own view only.
- New applications associate ownership in the same transaction as the case,
  evidence references, private receipt, idempotency record, audit and durable job.
  Existing guest receipt intake remains an API compatibility path. The customer
  UI requires sign-in. Historical cases are never attached by matching email;
  linking requires the unexpired private case receipt and cannot replace an owner.
- The customer dashboard loads persisted owned cases, submitted information,
  authorized photographs, real event timestamps, processing and human outcomes,
  public explanations, and specific evidence requests. Polling is nonoverlapping,
  ignores stale requests, backs off on errors, slows after final outcomes and
  resumes when a tab becomes visible. The reviewer queue displays processing
  separately from its human outcome.
- Individual eligible application fields show fictional suggestions on hover,
  focus, tap and typing. Portaled lists support filtering, arrows, Enter, Escape,
  pointer selection and screen-reader semantics. Selecting fills that field only.
  Relative dates remain in the past. Make/model/variant mismatches show a warning
  without changing other entries. Native selects, banking input, files and consent
  remain explicit. There is no demo or autofill-all button. Build with
  `VITE_SAMPLE_SUGGESTIONS=false` to disable suggestions later.
- Acceptance returns immediately after durable admission; background processing
  is separate. Upload previews can be removed. Retry uses the same UUID4 key;
  a changed payload under an already accepted key conflicts. Form values survive
  validation/network failure. Existing cleanup preserves files after uncertain
  commits instead of deleting potentially committed evidence.
- Run-specific snapshots freeze evidence thumbnails, check coverage, submitted
  details and limitations. PDF artifacts persist privately in PostgreSQL/SQLite,
  are generated idempotently from saved snapshots and retry without rerunning
  analysis. The report distinguishes applicant statements, measured findings,
  unavailable/inconclusive/not-run/not-applicable checks, fallback, and human
  decisions. Heuristic scores are not fraud probabilities. Earlier analysis/PDF
  versions remain intact after a human decision.
- Reviewer Report tabs provide Preview report, Download PDF, version/generation
  metadata, retry/failure states and a mobile new-tab fallback. PDF blobs use
  authenticated requests and object URLs are revoked. Server authorization covers
  metadata, preparation, inline bytes and downloads. Customer reports are not
  exposed; the customer sees their application and public decision instead.
- Decisions require the exact reviewed revision, run and evidence IDs for
  processed cases. Active analysis blocks decisions. Failed/interrupted analysis
  requires explicit manual-review acknowledgement and a rationale for final
  decisions. Rejection requires separate internal reason and customer explanation.
  Row locks/revision checks reject conflicting or stale actions; history remains.
- Receipt tracking now requires a valid receipt, owning customer, or reviewer.
  Case ID plus registration/policy alone cannot disclose the final outcome.

## Persistence and preservation

Actual Supabase PostgreSQL use was verified against application data, not merely
`SELECT 1`: 821 cases, 1,462 images, 32 jobs/results and 57 report snapshots at the
pre-edit boundary. Version 002 adds accounts/sessions/ownership/PDF artifacts;
all 20 original table row+rowid digests were exactly unchanged after upgrade.
All 26 private tables passed browser-role privilege/RLS checks. The original
version-001 SQL/checksum was not rewritten. Tests use disposable schemas, never
application-table cleanup.

Consistent private backups are outside Git at
`D:\projects\FraudLens-2.0-preservation\20261018-presentation-before-4cff328d`:
filesystem/SQLite backups, the eight pre-existing documentation files, original
PostgreSQL backups and an after-upgrade full logical backup. The format-2 restore
drill includes nonempty customer sessions, ownership and PDF bytes and refuses
to overwrite an existing schema. The read-only evidence audit found zero missing
paths, SHA mismatches, unreferenced uploads or changed files across 1,462 images.

Evidence remains private filesystem data; PDFs are durable database artifacts.
Deployment selects a mounted private persistent volume, retaining the existing
Path-based analysis pipeline. Supabase Storage buckets have not been created or
configured. Hosting must preserve the evidence volume and existing stopped
provider ledgers. See [backend deployment guide](FraudLens-2.0-Backend/DEPLOYMENT.md)
and [migration details](POSTGRES_MIGRATION.md). No hidden fallback to SQLite is
used when PostgreSQL is unavailable.

## Exact PowerShell startup

Prerequisites: existing backend Python 3.12 venv and model caches; the preserved
provider stop/quota ledgers; installed frontend dependencies; the pinned Node
22.23.3 runtime at the existing tools path. New installs were not rehearsed.
The helper checks the venv and API port and refuses to kill an occupied listener.

Stop only your own API/worker before switching databases or applying a migration.
For a version-001 pilot, back up first and run:

```powershell
Set-Location D:\projects\FraudLens-2.0\FraudLens-2.0-Backend
.\venv\Scripts\python.exe -X utf8 scripts/upgrade_postgres.py --schema fraudlens_pilot --apply
```

The current local pilot already has 002. If rebuilding, finish frontend checks
first, before loading API/worker models on this 8 GB computer:

```powershell
Set-Location D:\projects\FraudLens-2.0\FraudLens-2.0-Frontend
$env:FRAUDLENS_NODE22_HOME = 'D:\tools\FraudLens-node22\node-v22.23.3-win-x64'
$env:VITE_API_BASE_URL = 'http://127.0.0.1:8001'
$env:VITE_SAMPLE_SUGGESTIONS = 'true'
.\scripts\node22.ps1 -Task typecheck
.\scripts\node22.ps1 -Task build
```

Start the API in one terminal:

```powershell
Set-Location D:\projects\FraudLens-2.0\FraudLens-2.0-Backend
.\scripts\start_pilot.ps1 -Database postgresql -Port 8001 -NoWorker
```

Wait for application startup, then start the worker in another terminal:

```powershell
Set-Location D:\projects\FraudLens-2.0\FraudLens-2.0-Backend
.\scripts\start_pilot.ps1 -Database postgresql -WorkerOnly
```

Wait for worker OCR warmup and `/ready` HTTP 200. Serve the final frontend build
in the frontend terminal; an existing listener on 5173 need not be restarted:

```powershell
Set-Location D:\projects\FraudLens-2.0\FraudLens-2.0-Frontend
$env:FRAUDLENS_NODE22_HOME = 'D:\tools\FraudLens-node22\node-v22.23.3-win-x64'
$env:PORT = '5173'
$env:HOST = '127.0.0.1'
& (Join-Path $env:FRAUDLENS_NODE22_HOME 'node.exe') .output/server/index.mjs
```

Build and development servers run sequentially. `VITE_*` changes require a build.
Customer URL: `http://127.0.0.1:5173/dashboard`; reviewer URL:
`http://127.0.0.1:5173/admin`. Use the same host spelling consistently.

At handover on 20 October, 08:41 UTC, the final frontend and PostgreSQL API were
left running on those ports. `/ready` returned 200; the dedicated worker finished
OCR warmup and held database leadership, with zero active jobs. The original
pilot retains 821 historical cases and 1,462 images; it has no customer accounts
or owned cases yet. Create your account rather than expecting the isolated
rehearsal's fictional cases in PostgreSQL. The two original provider ledgers still
matched their private backups. Recheck readiness if these processes have stopped.

Customers create their own account through the sign-in page. No default customer
password is provided. Provision a reviewer using the interactive prompt:

```powershell
Set-Location D:\projects\FraudLens-2.0\FraudLens-2.0-Backend
.\venv\Scripts\python.exe -X utf8 scripts/manage_reviewer.py --db postgresql --email reviewer@example.test --role reviewer
```

Passwords stay out of command arguments, screenshots, Git and this guide.
Required configuration names are in both `.env.example` files and the deployment
guide. Account recovery/email verification/MFA are not implemented.

## Two-tab claims and underwriting walkthrough

1. Register/sign in as a customer in tab 1. Open Admin and sign in with an
   individual reviewer account in tab 2. Refresh both; neither replaces the other.
2. Open `/apply/claims`. Hover/focus each field, type to filter, select one sample,
   and edit it if desired. Choose policy/settlement options and consent yourself.
   Select a legitimate local vehicle photograph explicitly. Remove/reselect a
   preview if needed. Submit once. Keep the durable case ID and private receipt.
3. Follow the dashboard link. The case immediately appears in both dashboards as
   queued/processing. Processing failure does not remove evidence or approve a case.
4. Open the reviewer case, inspect its evidence/results/limitations and Report.
   Preview and download the PDF. Use a historical version for earlier runs.
5. Request specific additional photographs if needed, with a separate public
   message. The customer opens that owned case and submits the requested files;
   a new run preserves earlier evidence, reports and review history.
6. After processing ends, approve with an optional note, or reject with an internal
   rationale and customer-visible explanation. For failed analysis, deliberately
   acknowledge manual review and explain the basis. Do not infer fraud from a
   provider outage. The customer tab receives the outcome through polling.
7. Repeat with a different claim for rejection. Repeat approval and rejection with
   `/apply/underwriting`: six explicit photo slots, application type, condition
   declaration and notes. View-slot labels do not establish same-vehicle identity.

## Verification, blockers and rollback

See [current verification record](PRESENTATION_VERIFICATION.md) for exact final
commands, outcomes, artifacts and fixture/live-service boundaries. Historical
counts in older documents must not be summed with new overlapping runs.

Gemini remains stopped after the earlier two real HTTP 503 failures. This work
does not claim successful live model analysis. Deterministic supported checks and
partial reports support an explicit human-review path. No hosting target, TLS,
external persistent volume or deployed mobile browser has been verified. One
organization is supported; tenancy, recovery/MFA, least-privilege DB provisioning,
independent security/load/privacy/model validation remain external/future work.

For code rollback, stop writers, keep fresh full backups, and revert the focused
presentation commits. Retain additive 002 and its backups; old code expects only
001. The current restore tool installs 001+002 even from an older archive: an
old-code PostgreSQL rollback needs the matching pre-upgrade restore tool and a
new namespace, or an already preserved 001 schema. Never destructively drop new
application tables. For explicit SQLite rollback run the API with
`start_pilot.ps1 -Database sqlite -Port 8001 -NoWorker` and the separate worker
with `start_pilot.ps1 -Database sqlite -WorkerOnly`. PostgreSQL-only new
accounts/cases/reports are not automatically merged into the frozen SQLite copy.
Restore a full latest logical backup to a new private schema for recovery; existing
schemas/backups are never overwritten. Preserve unrelated documentation changes.

## Exact source files and purpose

- Customer access/ownership: backend `src/customer_auth.py`; frontend
  `src/experience/{CustomerSession.tsx,customer-api.ts,customer-session.css,Dashboard.tsx,user-dashboard.css}`.
- Suggestions/intake: frontend `src/experience/{FieldSuggestions.tsx,sampleSuggestions.ts,field-suggestions.css,Intake.tsx}`,
  `src/experience/shared.tsx`, `.env.example`.
- PDF/review: backend `src/report_pdf.py`, `requirements.txt`; frontend
  `src/experience/{Admin.tsx,HistoricalReport.tsx,ReportPanel.tsx,reportClient.ts,report-panel.css}`
  and `src/lib/security-headers.server.ts`.
- API/queue/evidence integration: backend `src/{api.py,runtime_store.py,evidence_workflow.py}`;
  frontend `src/experience/Tracker.tsx` and the shared client above.
- Persistence/deployment: backend `migrations/postgresql/002_customer_workflow.sql`,
  `src/{pg_migrations.py,postgres.py,storage_health.py}`,
  `scripts/{upgrade_postgres.py,start_deployment.py,audit_evidence_paths.py,postgres_backup.py,migrate_postgres.py,start_pilot.ps1}`,
  `.env.example`, `railway.json`, `DEPLOYMENT.md`.
- Verification: backend `test_{customer_workflow,report_pdf,deployment_storage,pilot_workflow,durable_pilot,postgres,api}.py`,
  `requirements-pilot.txt`, `scripts/{verify_presentation_browser.py,verify_offline_suite.py}`; frontend
  `scripts/{field-suggestions-harness.tsx,field-suggestions.vite.ts,verify_field_suggestions.py,verify_session_transports.py}`.
- Handover: `PRESENTATION_IMPLEMENTATION.md`, this guide,
  `PRESENTATION_VERIFICATION.md`, and focused additions to `PILOT_HANDOVER.md`,
  `DEMO_RUNBOOK.md`, `CHECK_VERIFICATION_MATRIX.md`, `AUTONOMOUS_PROGRESS.md`,
  `POSTGRES_MIGRATION.md`. Pre-existing edits in these files remain preserved.
