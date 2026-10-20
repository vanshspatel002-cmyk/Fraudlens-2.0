# Presentation verification — 18–20 October 2026

Results below belong to this branch. Overlapping reruns are **not** added into a
single release total. Earlier historical 241/272-pass releases remain historical.
No successful live Gemini request is claimed. Test command output is retained in
tool-console transcripts unless a private artifact path is explicitly named.
Initial test batches ran on 18 October. The resumed read-only preservation audit
and final browser rehearsal run on 20 October.

## Locally completed checks

| Check | Actual result | Boundary |
| --- | --- | --- |
| Focused backend regression: `test_pilot_workflow.py test_durable_pilot.py test_demo_readiness.py test_customer_workflow.py test_deployment_storage.py` | 97 passed, 593.72 s | Isolated SQLite; controlled embeddings and processing completions; before the last customer-contract additions |
| Existing standalone `test_api.py` | 25 passed, 0 failed; exit 0, 137.12 s | Isolated SQLite, real cached CLIP admission and document rejection; pipeline stubbed, no live model calls |
| Final `test_customer_workflow.py` | 9 passed, 84.39 s | Frozen backend; both kinds × approve/reject; server role separation, secure tracking, expiry/logout, ownership, supplementary evidence, stale/conflicting reviews |
| Stronger matching-email non-inheritance regression (`-k idempotency_ownership`) | 1 passed, 8 deselected, 11.75 s | Historical guest case deliberately contains the new account email; still requires receipt linking |
| `test_report_pdf.py` | 6 passed, 39.21 s | Real PDF rendering/bytes and private DB artifacts; auth, retries, pending state, immutable earlier PDF, long text/tables/Unicode/escaping |
| `test_deployment_storage.py` | 3 passed | Missing/unwritable/out-of-volume storage checks and deployment prerequisites; not deployed verification |
| Node 22 typecheck and production frontend build | Passed | Final build contains customer/role transports, suggestions, PDF CSP and underwriting application-type persistence; existing Nitro/Vite compatibility warnings retained |
| Suggestion Chrome harness | 6 enabled groups + disabled-configuration check passed; 0 JS errors | Actual reusable component/catalog/styles, isolated Vite harness; hover/focus/type/keyboard/edit/Escape/outside, dependencies, dates/numbers/narratives, explicit consent/files, 390 px touch/edge positioning |
| `scripts/verify_session_transports.py` | 7 Chrome checks passed | Actual transpiled frontend client code; controlled delayed network/body/clock fixtures verify stale-token and logout isolation and bounded PDF timeout |
| PostgreSQL migration/security | 4 passed, 76 deselected, 212.34 s | Actual Supabase PostgreSQL; unique disposable schemas, version/checksum and browser-role SELECT/INSERT/UPDATE/DELETE denial on all 26 private tables |
| PostgreSQL full format-2 backup/restore | 1 passed, 88 deselected, 61.37 s | Actual restore into a new test schema; nonempty customer sessions/ownership/PDF bytes retained, overwrite refused |
| PostgreSQL customer/PDF contracts | 14 passed, 81 deselected, 476.27 s | Real PostgreSQL and PDF rendering; controlled image/worker fixtures; both kinds and final outcomes |
| Final PostgreSQL ownership/tracking/recovery recheck | 8 passed, 89 deselected, 321.61 s | Latest secured tracker; independent sessions, all four outcome paths, idle-timeout rollback, import refusal, uncertain supplementary commit preservation |
| PostgreSQL concurrent reviewers/stale run | 1 passed, 96 deselected, 52.99 s | Simultaneous approve/reject yields 200 + 409; a new run rejects the former review basis |
| Pre/post migration preservation | All 20 original table row+rowid digests identical | Actual pilot data, not fixture-only connectivity; 821 cases, 1,462 images, 32 jobs/results, 57 snapshots at pre-edit boundary |
| Final read-only evidence audit | 1,462 images; 0 missing, SHA mismatches, unreferenced uploads, or changed files | Actual private filesystem and PostgreSQL references; ends remote read transaction before slow file hashing |
| Startup occupied-port guard | Passed | Intentional local listener retained; helper refused launch without killing it |

Known warnings: installed Starlette TestClient/httpx deprecation and existing
Nitro/Vite compatibility warning. They do not change the recorded test exit codes.
A clean dependency installation and future dependency compatibility are unverified.

PDF fixture render evidence is ignored/private at
`FraudLens-2.0-Backend/outputs/pilot_validation/reports-20261018`: four-page normal
report and eleven-page stress report. Raster pages 1/2 and 1/6/11 were inspected;
text blocks stayed within page bounds, long tables wrapped, and thumbnails kept
aspect ratios. These are controlled fixtures, not live insurance assessments.

Private backups and `evidence-audit-final.json` are under
`D:\projects\FraudLens-2.0-preservation\20261018-presentation-before-4cff328d`.
Both original provider ledger files matched their backups at the persistence
verification boundary; the browser harness also checks the original stop ledger.
The 20 October read-only recheck again confirmed both ledgers byte-identical,
all 20 original table counts unchanged, valid 001/002 checksums, 26 private RLS
tables with zero browser privileges, and all 1,462 original image hashes intact.
The original PostgreSQL extension tables still contained zero rows: isolated
rehearsals did not create customers, cases or PDF artifacts in the pilot database.

Final local startup at 20 October 08:41 UTC used the original PostgreSQL pilot:
frontend 5173 and API 8001 returned HTTP 200, `/ready` returned 200, OCR warmup
finished, and the dedicated worker held its PostgreSQL leadership lock. There
were zero active jobs, 821 cases and 1,462 images, and both provider ledgers still
matched backup bytes. Private evidence is at
`outputs/presentation_20261020/ready-postgresql/final-runtime-check.json` alongside
the startup logs. This is local readiness, not deployed or successful-AI evidence.

## Repeatable commands

From the backend, focused offline checks:

```powershell
$env:FRAUDLENS_TEST_LIVE = '0'
$env:FRAUDLENS_WORKER_ENABLED = '0'
$env:FRAUDLENS_WARM_MODELS = '0'
$env:HF_HUB_OFFLINE = '1'
$env:TRANSFORMERS_OFFLINE = '1'
.\venv\Scripts\python.exe -u -X utf8 -m pytest -q test_pilot_workflow.py test_durable_pilot.py test_demo_readiness.py test_customer_workflow.py test_report_pdf.py test_deployment_storage.py
```

The existing standalone runner also passed on the final code with the same
offline environment: `.\venv\Scripts\python.exe -u -X utf8 test_api.py`.
Its exit-0 line-buffered log is private at
`outputs/presentation_20261020/api-final-no-faulthandler/test_api.log`.
An earlier run also logged 25 passed / 0 failed. An intervening diagnostic retry
crashed in `python312.dll` during a faulthandler stack dump while importing CLIP;
that attempt is retained and is not counted as a pass. The clean retry without
that diagnostic completed normally. No out-of-memory cause is established.

The retained bounded `scripts/verify_offline_suite.py` now includes the new
customer/PDF/storage modules; choose a **new** `FRAUDLENS_OFFLINE_OUTPUT_DIR` when
running it. It disables live integrations and keeps earlier logs. A new complete
research-corpus sweep was not required or run for this presentation change.

PostgreSQL uses the same worker/live-disabled environment plus
`$env:FRAUDLENS_TEST_POSTGRES = '1'`, then
`.\venv\Scripts\python.exe -u -X utf8 -m pytest -q test_postgres.py -k '<selection>'`.
The exact recorded selections were:

1. `additive_customer_upgrade or browser_roles_cannot or migration_checksum`
2. `backup_restores_customer_ownership_sessions_and_pdf`
3. `registration_password or owned_workflow or idempotency_ownership or manual_override_stale or customer_additional or pdf_private or pdf_failure_retry or pdf_pending or saved_pdf_unchanged or report_history_is_immutable`
4. `owned_workflow or registration_password or rollback_after_idle or import_refuses_changed_existing_target or uncertain_supplement_preserves`
5. `conflicting_reviewers_and_changed_run_are_rejected`

Tests create uniquely named `fraudlens_test_*` schemas and remove only their own
schemas. They never truncate application tables. Do not copy test cleanup into
the application schema. New test additions can change deselection counts.

From the frontend, `scripts/node22.ps1 -Task typecheck` and `-Task build` use the
supported local runtime. `scripts/verify_field_suggestions.py` uses its isolated
Vite configuration; `scripts/verify_session_transports.py` transpiles the real
clients with installed TypeScript and runs controlled Chrome transport fixtures.

For a deliberate new browser rehearsal, stop only your own API/worker and point
both at the **existing isolated** database using
`start_pilot.ps1 -Database sqlite -SqlitePath '<absolute acceptance.db path>'`
with `-Port 8001 -NoWorker` for the API and `-WorkerOnly` for its worker. Keep the
production frontend on port 5173. The retained isolated database contains the
private reviewer fixture expected by the harness; an empty database does not.
The harness reads its credentials privately and creates a fresh fictional customer.
It adds four cases; never point it at the PostgreSQL pilot or frozen `demo.db`.
From the backend:

```powershell
$env:PRESENTATION_DB = Join-Path (Get-Location) 'outputs/presentation_20261018/browser-20261018-a/acceptance.db'
$env:PRESENTATION_OUTPUT_DIR = Join-Path (Split-Path $env:PRESENTATION_DB) ('attempt-' + (Get-Date -Format 'yyyyMMdd-HHmmss'))
$env:PRESENTATION_UI = 'http://127.0.0.1:5173'
$env:PRESENTATION_API = 'http://127.0.0.1:8001'
$env:PRESENTATION_PAUSE_RESTART = '1'
.\venv\Scripts\python.exe -u -X utf8 scripts/verify_presentation_browser.py
```

At its private `restart_requested` checkpoint, restart only that isolated API and
worker with the same database, wait for readiness, then create an empty
`restart_ready` file in the new output directory. The harness continues with its
two Chrome tabs open. Omit the pause variable only when intentionally excluding
actual service restart from a future run; report that boundary explicitly.

## Final browser rehearsal

The final-code rehearsal uses actual installed headless Chrome, **two tabs in
one shared browser context**, actual production frontend, API, explicit real
vehicle-photo uploads, and the durable local worker in a new isolated SQLite
database. PostgreSQL was qualified separately above; the browser run must not be
described as a PostgreSQL browser run or a manually operated headed browser.

Artifacts are kept in a new private
`FraudLens-2.0-Backend/outputs/presentation_20261018/browser-20261018-a` directory.
The first attempt registered a customer but stopped because the empty isolated
database lacked the private reviewer fixture. That failure is preserved; the
fixture is provisioned only into the isolated database before a complete rerun.
Later harness-only failures involved replaying an empty streamed multipart body,
an optional CDP diagnostic assuming that body existed, and interacting with a
background tab before hydration settled. The real browser FormData replay
returned the original case correctly. Two earlier accepted claims are retained;
the final run uses a fresh customer and checks its own four cases separately
from the preserved baseline. Failed artifacts are kept; none count as a complete
rehearsal. Raw credential-bearing browser errors are suppressed in the harness.

The uninterrupted `attempt-e-20261020` rerun completed with exit 0 and 36 recorded
checks. Both roles used the same Chrome context. It passed all four decisions,
additional-evidence request/upload/reprocessing, exact authenticated idempotency
replay, automatic customer outcome polling, authenticated PDF preview/download,
original-PDF immutability, tab refresh, cross-customer case/image/report denial,
receipt tracking, real signed-in claims/underwriting mobile forms, 390 px
customer/admin/report layouts, 768 px dashboards, actual API/worker restart with
the two tabs still open, independent logout, and both session expiries.

| Final fictional case | Human outcome | Server acceptance | Persisted processing duration | Downloaded PDF |
| --- | --- | --- | --- | --- |
| `case-ad45e278056c` — claims | Approve | 16.910 s | 29.291 s; supplementary run 13.808 s | 10 pages, 17,199 extracted characters |
| `case-1415993c44e8` — claims | Reject | 1.575 s | 5.851 s | 10 pages, 16,730 extracted characters |
| `case-b8f027fac979` — underwriting | Approve | 3.546 s | 72.022 s | 27 pages, 45,040 extracted characters |
| `case-e5d5cee1b7b7` — underwriting | Reject | 4.204 s | 18.491 s | 27 pages, 46,204 extracted characters |

Server supplementary acceptance was 1.214 s; exact idempotent replay was 1.408 s.
Acceptance uses API middleware timing and is separate from the persisted job
`started_at` to terminal `updated_at` interval. Browser confirmation and poll-wait
durations are recorded separately and must not be described as server latency.
The preserved earlier first cold run took 585.351 s; the next earlier run took
4.747 s. Cold local model loading and this 8 GB host remain material latency
limits. Timeouts were not increased to disguise them.

All five final real processing runs finished **failed / needs_review**, with
`provider_unavailable=true`. The reports disclose incomplete analysis, and the
four final decisions explicitly acknowledge manual review. Human approval did
not turn processing into success. The original model-stop ledger remained
byte-identical; no successful live Gemini execution is claimed.

Private, ignored artifacts under
`FraudLens-2.0-Backend/outputs/presentation_20261018/browser-20261018-a/attempt-e-20261020`:

- `browser_verification.json`: 36 incremental observations and final completion.
- `acceptance-processing-timings.json`: authoritative server timing and persisted
  job timestamps/durations, separated from browser waits.
- `pdf-render-verification.json`: all four PDFs have zero text spans outside page
  bounds; underwriting reports contain the actual application-type declaration.
- `persistence-final-check.json`: six retained cases/owners (four final plus two
  earlier attempts), zero active jobs or foreign-key violations, five durable PDFs.
- Four PDFs, rendered pages and laptop/mobile screenshots from the final build.

There were zero application JavaScript exceptions. The ten console errors were
the deliberate aborted request (one), refused requests during the intentional
restart (seven), and deliberate expiry responses (two). Playwright emitted four
`Response.finished / Target closed` cleanup-task warnings after completion;
the unnecessary diagnostic callback was removed from future harness runs only.
No product-code or build changes followed the successful four-case rehearsal.
The real browser restart verified retained state with an empty queue; active-job
crash recovery is covered separately by the isolated durable-worker/PG contracts.

## Limits

The preserved provider stop follows two earlier real Gemini HTTP 503 failures.
Controlled fixture model replies are not live AI verification. The real browser
workflow exercises truthful incomplete analysis and explicit human review while
the provider remains stopped. Existing research performance is not new accuracy
evidence. Same-vehicle six-view identity is not independently verified.

No hosting/TLS/CORS/persistent-volume deployment has been performed. Private
evidence needs the configured durable volume; Supabase Storage is not connected.
Physical phones, virtual keyboards, screen readers, manual OS print dialogs,
multi-organization tenancy, email verification/account recovery/MFA, load/security/
privacy review and independent model validation remain outside verified scope.
