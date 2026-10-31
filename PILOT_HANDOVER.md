# Current presentation workflow — 18–20 October 2026

Use [PRESENTATION_HANDOVER.md](PRESENTATION_HANDOVER.md) for current customer
accounts, ownership, field suggestions, PostgreSQL version 002, stored PDFs,
review decisions, exact PowerShell startup, configuration names and rollback.
See [PRESENTATION_VERIFICATION.md](PRESENTATION_VERIFICATION.md) for final-code
evidence and external blockers. Earlier entries below are retained history;
their account/storage/receipt limitations and test counts may be superseded.

# FraudLens 2.0 pilot handover — 15 October 2026

## Current readiness continuation

Continue on `autonomous/demo-readiness-20261015`; this preserves the completed
PostgreSQL migration and earlier hardening. See [AUTONOMOUS_PROGRESS.md](AUTONOMOUS_PROGRESS.md)
for final verification, [GEMINI_DIAGNOSIS.md](GEMINI_DIAGNOSIS.md) for the stopped
provider, [LATENCY_MEASUREMENTS.md](LATENCY_MEASUREMENTS.md) for actual laptop
timings, and [DEMO_READINESS_CHECKLIST.md](DEMO_READINESS_CHECKLIST.md).

The supported runtime is now **Node 22.23.3 / npm 10.9.9**, installed separately
from the unrelated global Node 24. The lockfile is unchanged. Actual type-check,
production builds, built-server HTTP and Node-22 development-server HTTP passed.
Nitro 3.0.260903-beta's compiled Vite builder still warns that it requires ^8,
although its package metadata/current documentation include Vite 7 compatibility.
Vite 7.3.6 is retained: builds/SSR were exercised; broader compatibility is not
established. No dependency upgrade or fresh installation was necessary/rehearsed.

Gemini remains at **two original real HTTP 503 vision failures, zero new calls**.
The preserved ledger stays stopped. Fresh live vision/adjudication remains
unverified. `gemini3_defaults_v2` is an explicit pilot request profile; the default
research profile remains `legacy`. Production agent policy remains v3, with
`production-checks-2026-10-15-v2` recorded separately. This includes the plate
prefix correction and trusted intake time-basis handling. Genuine UTC instants
are not shifted again as synthetic research wall clocks; unverified production
time bases abstain. Cached raw OCR is reused, never a previous case verdict.
Reports record vision and agent response provenance, incomplete checks, fallback,
run/policy/check revision and the human's actual reviewed run/evidence.

The latest SQLite acceptance completed both workflows uninterrupted, including
supplements/history, exact human-review basis, logout/expiry, repeated selection,
Escape and mobile reviewer/tracker/both forms. It retained 817 cases/1,445 images,
25 failed runs and 42 snapshots in an isolated copy. The frozen rollback remains
812 cases/17 failed jobs. These copy submissions are not merged into PostgreSQL.
The bounded release passed **272**, failed **0**, skipped **11**. Ten skips disable
live integrations; one excludes the preserved whole REUSE/CLEAN research sweep.
The 241/10 baseline below is historical, not the current count. PostgreSQL
qualification results are recorded in the progress/runbook sections. Historical
snapshots remain immutable. All rows/schemas in the five original SQLite DBs,
all 82 original root output files, both policy files, configuration and the
stopped ledger matched preservation. Consistent new backups are outside Git.

The release manifest retains unchanged runners and reruns the affected suites;
its counts are not a sum of overlapping attempts. Models 82, baseline 14,
agent 16, LLM 7, perception 2, real local ingestion 6, checks 33, API 25,
integration runner 1, focused pytest 86 = **272 passes**. LLM/perception skip
7/3 live tests; checks skips one historical corpus sweep. The failed focused
attempt (85 passes/1 missing-helper failure) is retained; restoring the count
helper passed five targeted regressions and the complete 86-test rerun.
`pip check` reports no broken requirements. Nitro, Starlette and local torch
warnings remain recorded; they are not test failures or proof of future compatibility.

## Exact current Windows commands (API 8001, frontend 5173)

Preserve the original port-8000 service. Stop only the pilot API/worker/frontend
with Ctrl+C before switching a database or rebuilding. Backend `.env` retains its
server-only DATABASE_URL; no Supabase browser client or Supabase Auth is used.
Local evidence stays on disk. Existing cached model weights and the stopped
ledger are required; neither readiness nor startup sends a Gemini probe.

Install the pinned portable Node only if absent (official archive/checksum):

```powershell
$nodeTools = 'D:\tools\FraudLens-node22'
$nodeArchive = Join-Path $nodeTools 'node-v22.23.3-win-x64.zip'
$nodeRuntime = Join-Path $nodeTools 'node-v22.23.3-win-x64'
if (-not (Test-Path $nodeTools)) { New-Item -ItemType Directory -Path $nodeTools | Out-Null }
if (-not (Test-Path $nodeArchive)) {
  Invoke-WebRequest 'https://nodejs.org/dist/v22.23.3/node-v22.23.3-win-x64.zip' -OutFile $nodeArchive -UseBasicParsing
}
if ((Get-FileHash $nodeArchive -Algorithm SHA256).Hash.ToLower() -ne '2b0ff57b049cda1bbcea2240eec20467018713c1efe1f7360c2681859b90ed71') { throw 'Node checksum mismatch' }
if (-not (Test-Path $nodeRuntime)) { Expand-Archive -LiteralPath $nodeArchive -DestinationPath $nodeTools }
$env:FRAUDLENS_NODE22_HOME = $nodeRuntime
& (Join-Path $nodeRuntime 'node.exe') --version
```

Backend dependencies, using the existing venv (a clean install was not rehearsed):

```powershell
Set-Location D:\projects\FraudLens-2.0\FraudLens-2.0-Backend
.\venv\Scripts\python.exe -m pip install -r requirements.txt
.\scripts\start_pilot.ps1 -Database postgresql -Port 8001 -NoWorker
```

Wait for **Application startup complete**. In a second backend terminal:

```powershell
Set-Location D:\projects\FraudLens-2.0\FraudLens-2.0-Backend
.\scripts\start_pilot.ps1 -Database postgresql -WorkerOnly
```

Wait for **Worker OCR warmup: ready** and **Durable worker started**. `/ready`
must return 200. Authenticated `/v1/operations` should report database leadership
present and no API-local worker. Initial model loading can take over a minute;
`-NoWarmup` is a diagnostic option, not the presentation startup.

In the frontend terminal, build before starting any frontend server:

```powershell
Set-Location D:\projects\FraudLens-2.0\FraudLens-2.0-Frontend
$env:FRAUDLENS_NODE22_HOME = 'D:\tools\FraudLens-node22\node-v22.23.3-win-x64'
$env:VITE_API_BASE_URL = 'http://127.0.0.1:8001'
.\scripts\node22.ps1 -Task typecheck
.\scripts\node22.ps1 -Task build
$env:PORT = '5173'
$env:HOST = '127.0.0.1'
& (Join-Path $env:FRAUDLENS_NODE22_HOME 'node.exe') .output/server/index.mjs
```

For development, stop the production frontend, then use
`.\scripts\node22.ps1 -Task dev` instead. Build and development servers must run
sequentially; changing VITE_API_BASE_URL requires another build. The browser
acceptance uses the actual production build on 5173, avoiding cold Vite SSR
compilation. Native warning stderr is retained and actual exit codes checked.

Bounded offline release (new output directory preserves prior logs):

```powershell
Set-Location D:\projects\FraudLens-2.0\FraudLens-2.0-Backend
$env:FRAUDLENS_OFFLINE_OUTPUT_DIR = Join-Path (Get-Location).Path ('outputs\pilot_validation\release-' + (Get-Date -Format 'yyyyMMdd-HHmmss'))
.\venv\Scripts\python.exe -u -X utf8 scripts/verify_offline_suite.py
```

This uses each suite's correct runner, disables live integrations, and explicitly
skips the unchanged whole REUSE/CLEAN research sweep while retaining individual
reuse/clean regressions. Ten live tests are separately skipped. `--resume` retains
completed runners and gives interrupted attempts new logs. Do not use the older
unbounded check-sweep commands below merely to repeat research accuracy figures.

Latest PostgreSQL changes can be verified without touching pilot data:

```powershell
$env:FRAUDLENS_TEST_POSTGRES = '1'
$env:FRAUDLENS_TEST_LIVE = '0'
$env:FRAUDLENS_WORKER_ENABLED = '0'
$env:FRAUDLENS_WARM_MODELS = '0'
.\venv\Scripts\python.exe -u -X utf8 -m pytest -q test_postgres.py -k 'pipeline or processing_runs_never_mix or report_history or adjudication_response_source or time_basis or duplicate_snapshot'
```

That selection passed **11**, deselected 68, failed/skipped 0 in a new disposable
schema. A separate `-k duplicate_pool_count` run passed 1, deselected 78. The prior
full PostgreSQL qualification remains 73 passes; it is not added to these results.
Mock model replies in tests do not establish live AI success.

SQLite rollback: stop the PostgreSQL pilot API/worker, then use the same two
backend commands with `-Database sqlite` (retain `-NoWorker` for the API). This
explicit file selection overrides DATABASE_URL without editing credentials.
For the retained acceptance copy, also pass
`-SqlitePath outputs/pilot_validation/readiness_20261015/acceptance.db` to both
commands. Never merge this copy/research databases into the migrated pilot.
Original main rollback/backup procedures remain in POSTGRES_MIGRATION.md.

Current SaaS limits remain: one organization, no complete tenant isolation,
unverified applicant identity/MFA/recovery, owner-level DB credentials needing a
least-privilege service login, host-local evidence/budgets, unsupervised services,
and incomplete independent security/load/privacy/model validation. Cold uncached
multi-photo OCR can still take minutes on this 8 GB host. Consistent six-view
photos and signed C2PA fixtures are missing. Manual OS print dialogs and screen
readers remain unverified; headless PDFs and selected 390 px layouts were tested.

## Preserved migration handover (previous port-8002 examples)

The local pilot now uses **Supabase PostgreSQL**, qualified through actual claims
and underwriting browser workflows. React still calls FastAPI; authentication,
applicant receipts and local image storage are unchanged. The frozen 812-case
SQLite demo and all research databases remain available. Nothing was pushed or
deployed externally.

Read [POSTGRES_MIGRATION.md](POSTGRES_MIGRATION.md) for the complete SQL inventory,
private schema, import/validation results, backup/restore and exact rollback.
Read [DEMO_RUNBOOK.md](DEMO_RUNBOOK.md) for the two-tab flow. Both workflows
verified acceptance, queue/detail, processing failure disclosure, findings,
evidence, trace, PDF, secure additional evidence, controlled reprocessing,
historical reports, human decision and public tracking. Claims finished across
a preserved rehearsal and continuation; underwriting completed in one run.
Logout, expiry and the mobile tracker were checked. Earlier failures remain
documented in [AUTONOMOUS_PROGRESS.md](AUTONOMOUS_PROGRESS.md).

Final database-specific verification: **72 passed**, plus **1 external-worker
monitor test passed**; 0 final failures/skips. The full offline SQLite/backend
release passed **241**, failed 0, skipped 10 intentional live tests. Tests that
mock models do not prove AI reliability. Actual headless Chrome PDFs contained
9 pages/11,129 text characters for claims and 22 pages/33,015 for underwriting.
Manual OS print dialogs and screen-reader behavior remain unverified.

**Gemini remains stopped:** two prior actual vision requests, both HTTP 503;
zero additional provider requests during migration. No new successful live
vision or agent adjudication is claimed. Browser processing truthfully failed
with saved evidence and disclosed fallback, followed by fictional human reviews.
Scores remain heuristic and independent detection accuracy is unestablished.

## Current Windows startup

Existing backend `.env` contains the server-only DATABASE_URL. Install/update
dependencies with the commands below; `requirements.txt` now also pins psycopg
3.3.6 and psycopg-pool 3.3.3. Do not replace configuration or the stopped ledger.

Backend/API terminal:

```powershell
Set-Location D:\projects\FraudLens-2.0\FraudLens-2.0-Backend
.\scripts\start_pilot.ps1 -Database postgresql -Port 8002 -NoWorker
```

After **Application startup complete**, another backend terminal:

```powershell
Set-Location D:\projects\FraudLens-2.0\FraudLens-2.0-Backend
.\scripts\start_pilot.ps1 -Database postgresql -WorkerOnly
```

Wait for OCR warmup and worker startup before presenting. The worker uses the
existing queue/checks/pipeline in a separate process, avoiding API stalls from
cold native models. `/v1/operations` reports a database-visible worker leader;
an API-local worker thread is intentionally absent. Each helper sets the same
absolute rollback/evidence/ledger paths and retains the provider stop.

Frontend terminal:

```powershell
Set-Location D:\projects\FraudLens-2.0\FraudLens-2.0-Frontend
$env:VITE_API_BASE_URL = 'http://127.0.0.1:8002'
npm.cmd run dev
```

Open `http://127.0.0.1:5173`. API and worker must both remain running. Run builds
and model warmup sequentially on this 8 GB host. Node 24 was used successfully
here despite the package's Node-22 engine requirement; use Node 22 for a fresh
reproduction. Existing model caches are required for the offline startup.

PostgreSQL tests allocate and remove their own new schemas:

```powershell
Set-Location D:\projects\FraudLens-2.0\FraudLens-2.0-Backend
$env:FRAUDLENS_TEST_POSTGRES = '1'
$env:FRAUDLENS_TEST_LIVE = '0'
$env:FRAUDLENS_WORKER_ENABLED = '0'
$env:FRAUDLENS_WARM_MODELS = '0'
.\venv\Scripts\python.exe -u -X utf8 -m pytest -q test_postgres.py
```

The current source has 73 PostgreSQL tests; the recorded verification was a
72-test full run and the later one-test external-leader regression. Supabase
Storage, verified applicant accounts/MFA, complete tenancy, distributed rate/
provider budgets, least-privilege service credentials, security/load review and
successful live AI validation remain production work. This remains one local
organization and reports `tenant_isolation: false`.

Final private preservation: `20261015-postgresql-qualified` (logical backup),
fully restored/verified as `fraudlens_restore_qualified_20261015`;
`20261015-qualified-files` (5,134 files); and `20261015-frontend-config`.
These are under `D:\projects\FraudLens-2.0-preservation`, outside Git. The final
pilot has 816 cases/1,443 verified image files/23 run results/39 reports; the
rollback remains at 812 cases. Reimport now correctly refuses to merge those
new records into the frozen source. API readiness, public-field privacy,
anonymous denial and external worker leadership passed the final HTTP smoke.

## Preserved SQLite handover — 14 October 2026

This continues the existing FastAPI/SQLite and React/TanStack implementation on `autonomous-pilot-hardening-20261014`. The inherited staged patch and audit dossier were preserved in local commit `09d06e8`. No rebuild, external deployment, paid service or push was performed. No applicable `AGENTS.md` was found. The original audit remains historical; this document records subsequent behavior.

Read [DEMO_RUNBOOK.md](DEMO_RUNBOOK.md), [CHECK_VERIFICATION_MATRIX.md](CHECK_VERIFICATION_MATRIX.md) and [AUTONOMOUS_PROGRESS.md](AUTONOMOUS_PROGRESS.md). This is a single-organization local pilot; multi-tenant SaaS and deployment detection accuracy are not established.

## Preservation and implementation

Private preservation: `D:\projects\FraudLens-2.0-preservation\20261014T065436Z`, including consistent SQLite backups of all four databases (integrity `ok`), evidence, cached perception, models, config, research outputs, audit and binary working-tree patches. Credentials stayed outside Git. Original corpus counts and the latest research outputs were compared against preservation; results and the subsequent restore drill are in the progress document.

- Acceptance, indexing, applicant receipt, idempotency replay record, audit and durable job commit together. Validated JPEG/PNG/WebP files use unique names. Duplicate/invalid uploads and ingestion failures roll back; UUID4 submission keys replay identical submissions and reject changed payloads.
- Admins request specific photographs. Supplementary uploads require a case-scoped private receipt and open request. Original evidence, human decisions and report history remain; new evidence triggers one controlled run. Active processing, stale requests and exact duplicates conflict.
- SQLite jobs survive restarts, with one active job per case and one OS-locked worker per host. Recovery is bounded to three attempts. Queued/running/completed/failed/interrupted are distinct. Model failure preserves submissions and exposes an explicit human-review fallback; terminal work can be retried by a reviewer.
- Findings, decisions, traces, evidence IDs and policy versions belong to a recorded run. Queued new runs do not show historical findings as current. Immutable report versions remain readable. Legacy research results disclose missing run association.
- Individual PBKDF2 reviewer accounts have admin/reviewer/viewer roles. Eight-hour hashed-token sessions expire, revoke on logout/disable/rotation and authenticate reviewer attribution server-side. Private cases, images, reports, jobs and actions enforce access. Service credentials cannot record human decisions. Applicant receipts authorize only their own upload/job status.
- Existing branding/layout remain. Evidence resolves at original resolution; refresh/retry, historical reports, print styles, loading/failure states, public statuses and role-aware controls were repaired. Image/category mappings, CORS/CSP and stale/misleading filters were fixed. Confidence is labeled heuristic rather than a calibrated probability.
- `/ready` and `/health` never call Gemini. Authenticated `/v1/operations` exposes local worker/queue/failures and `tenant_isolation: false`. Structured logs include status/latency/server actor, without bodies or secrets.

Research policies, weights, thresholds and historical outputs remain frozen. Production corrections are separate in `src/agent/production_policy.py`: v1 integrates already registered nonzero scenario checks and corrects reliability/attribution; v2 converts zero-weight findings to inconclusive while retaining experimental observations and avoids inventing an undamaged underwriting declaration; current v3 labels the preserved billing threshold as a research benchmark whose current legal applicability is unverified. Previous v1/v2 reports remain historical. Latest ablation: 58/99 agent cases after 22 exclusions from 121 selected records; the existing integrity verifier checked 58/58 stored decisions without problems on a copy. These are research coverage figures, not deployment accuracy.

New human actions record the reviewed run, decision, processing status and evidence IDs in the audit and reports; prior-run actions remain labeled as history. Production OCR caches text/confidence observations by image hash and engine version/configuration, recomputes identity comparisons for each case, and releases cache writer locks before more inference. It never caches a case verdict. Invalidate `production_plate_ocr` cache entries on a copy if OCR weights/configuration change outside the versioned default engine. Research execution does not enable this production cache. Duplicate-pool metrics use SQL counts rather than decoding the entire corpus.

## Windows PowerShell setup

Verified environment: Python 3.12.8, FastAPI 0.141.1, google-genai 2.18.1 and Torch 2.13.0+cpu. The package engine requires Node `>=22.16.0 <23`. Use Node 22 for reproducible setup. This shell resolves Node 24.21.0/npm 11.19.0, outside the declared engine; actual frontend verification has that limitation. Preserve the lockfile/pinned dependencies. A clean environment installation was not rehearsed; the installed Python environment passed `pip check`.

Do not overwrite existing `.env`, databases, evidence or evaluation outputs. If dependencies are missing:

```powershell
Set-Location D:\projects\FraudLens-2.0\FraudLens-2.0-Backend
if (-not (Test-Path .\venv\Scripts\python.exe)) { py -3.12 -m venv venv }
.\venv\Scripts\python.exe -m pip install -r requirements.txt
.\venv\Scripts\python.exe -m pip install -r requirements-pilot.txt
.\venv\Scripts\python.exe -m pip check
```

The CPU Torch index is already in `requirements.txt`. Optional pytest/Playwright/PDF tools are pinned separately. Chrome automation uses the installed Chrome with `channel='chrome'`; no browser download is required here. Preserve exact errors if dependencies are unavailable.

In the frontend, after selecting Node 22:

```powershell
Set-Location D:\projects\FraudLens-2.0\FraudLens-2.0-Frontend
node --version
npm.cmd ci
npm.cmd run typecheck
npm.cmd run build
```

Run build and dev sequentially: they share generated TanStack files, and a concurrent build disrupted a rehearsal. Nitro is now enabled only for production build because its inherited dev integration broke Vite's environment runner. The inherited Nitro/Vite peer-version warning remains; dependencies were not migrated.

## Isolated database and reviewer provisioning

This session uses private `outputs/pilot_validation/demo.db` and separate uploads/thumbnails. Preserve it and its stopped live ledger. To create another isolated demonstration later, use a new directory and consistent backup:

```powershell
Set-Location D:\projects\FraudLens-2.0\FraudLens-2.0-Backend
$pilotRoot = (Get-Location).Path
$pilotDir = Join-Path $pilotRoot ('outputs\pilot-demo-' + (Get-Date -Format 'yyyyMMdd-HHmmss'))
New-Item -ItemType Directory -Path $pilotDir | Out-Null
$env:FRAUDLENS_DB = Join-Path $pilotDir 'demo.db'
@'
import os, sqlite3
from pathlib import Path
source=sqlite3.connect(Path('fraudlens.db').resolve().as_uri()+'?mode=ro', uri=True)
target=sqlite3.connect(os.environ['FRAUDLENS_DB'])
try:
    source.backup(target)
    assert target.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
finally:
    source.close(); target.close()
'@ | .\venv\Scripts\python.exe -X utf8 -
.\venv\Scripts\python.exe scripts/manage_reviewer.py --db $env:FRAUDLENS_DB --email reviewer@example.test --role admin
```

The account command privately prompts for a password (12 characters minimum). It also rotates existing credentials and revokes sessions. Use `--role reviewer` for review/retry, `--role viewer` for private read-only access, or `--disable` to revoke an account. Configured bootstrap email/password-hash access remains available; rotating either invalidates its sessions. Passwords must stay out of arguments, Git and screenshots.

## Startup: backend terminal

Exact commands for the preserved session demonstration follow. Port 8000 was occupied by an existing service and was left alone. For a newly prepared directory, substitute that directory for `$pilotDir`. Existing Gemini credentials load privately from `.env`.

```powershell
Set-Location D:\projects\FraudLens-2.0\FraudLens-2.0-Backend
$pilotRoot = (Get-Location).Path
$pilotDir = Join-Path $pilotRoot 'outputs\pilot_validation'
$env:FRAUDLENS_DB = Join-Path $pilotDir 'demo.db'
$env:FRAUDLENS_UPLOAD_DIR = Join-Path $pilotDir 'uploads'
$env:FRAUDLENS_THUMB_DIR = Join-Path $pilotDir 'thumbnails'
$env:FRAUDLENS_LIVE_LEDGER = Join-Path $pilotRoot 'outputs\pilot_validation\live_calls.json'
$env:FRAUDLENS_LIVE_LIMIT = '15'
$env:GEMINI_QUOTA_BUDGET = Join-Path $pilotDir 'quota_budget.json'
$env:GEMINI_QUOTA_CONSUMER = 'pilot'
$env:FRAUDLENS_WORKER_ENABLED = '1'
$env:FRAUDLENS_WARM_MODELS = '1'
$env:HF_HUB_OFFLINE = '1'
$env:TRANSFORMERS_OFFLINE = '1'
$env:CORS_ORIGINS = 'http://127.0.0.1:5173,http://localhost:5173'
.\venv\Scripts\python.exe -X utf8 scripts/pilot_preflight.py
.\venv\Scripts\python.exe -X utf8 -m uvicorn src.api:app --host 127.0.0.1 --port 8001
```

Wait for **Application startup complete**. In-process CLIP warmup avoids a cold load inside applicant acceptance: the first cold submission under contention took roughly 563 seconds. Offline flags assume existing model caches; missing weights fail startup rather than fabricate a gate result. `pilot_preflight.py --warm-models` warms a separate process, not the server. Do not run `--live` during this stopped session.

Another terminal:

```powershell
Invoke-RestMethod http://127.0.0.1:8001/ready
Invoke-RestMethod http://127.0.0.1:8001/health
Set-Location D:\projects\FraudLens-2.0\FraudLens-2.0-Frontend
$env:VITE_API_BASE_URL = 'http://127.0.0.1:8001'
npm.cmd run dev
```

Use `http://127.0.0.1:5173` consistently. Applicant/reviewer session storage is tab-local. Save the private receipt from acceptance; it expires after 30 days and permits requested evidence uploads. Public tracking requires case ID plus registration/policy, but that challenge does not verify applicant identity. Only status, public human explanation and requested photographs are exposed.

## Meaningful verification

Use a fresh PowerShell terminal for offline testing, disable live tests and use the correct custom runners. Do not collect every legacy file with pytest.

```powershell
Set-Location D:\projects\FraudLens-2.0\FraudLens-2.0-Backend
$env:FRAUDLENS_TEST_LIVE = '0'
$env:FRAUDLENS_WARM_MODELS = '0'
$env:FRAUDLENS_WORKER_ENABLED = '0'
$env:HF_HUB_OFFLINE = '1'
$env:TRANSFORMERS_OFFLINE = '1'
.\venv\Scripts\python.exe -X utf8 test_models.py
.\venv\Scripts\python.exe -X utf8 test_baseline.py
.\venv\Scripts\python.exe -X utf8 test_agent.py
.\venv\Scripts\python.exe -X utf8 test_llm.py
.\venv\Scripts\python.exe -X utf8 test_perception.py
.\venv\Scripts\python.exe -X utf8 test_ingest.py
.\venv\Scripts\python.exe -X utf8 test_checks.py
.\venv\Scripts\python.exe -X utf8 test_api.py
.\venv\Scripts\python.exe -X utf8 scripts/verify_integration.py
.\venv\Scripts\python.exe -X utf8 -m pytest -q test_pilot_workflow.py test_durable_pilot.py
```

`scripts/verify_offline_suite.py` runs those commands sequentially, isolates quota storage, preserves combined logs and records true exit codes/counts in `outputs/pilot_validation/offline_release/results.json`. It refuses to overwrite previous release logs. Run heavy tests, build and browser rehearsal sequentially on this 8 GB host. The check inventory script likewise preserves completed evaluation copies.

Focused transaction/auth/run tests disclose mocked model/embedding replies. Ingest/API/integration runners also exercise real local CLIP and storage; integration adjudication is stubbed. None proves live Gemini reliability. Actual pass/fail/skip counts, build and browser results are recorded in the progress document.

## Actual Gemini result

**2 actual provider requests out of 15**, both vision HTTP 503 failures. The persistent stop latch prevents further live attempts after repeated failures or quota exhaustion, including restart/day reset. No successful new Gemini vision or agent adjudication was observed. Legitimate cached perception was reused; failed vision remained missing. The browser exercised incomplete analysis and disclosed fallback behavior.

SDK automatic retries are disabled; explicit attempts reserve the persistent session budget before network access. Retry configuration was checked against [Google's SDK implementation](https://github.com/googleapis/python-genai/blob/main/google/genai/_api_client.py). Clients/images are closed. Every pilot process must share the ledger; historical entrypoints have an opt-in cap. Do not reset/rename/delete this session's ledger or switch models/keys to bypass the stop.

## Backup and restore

Stop evidence writers before filesystem copying. Stop the pilot with Ctrl+C; next startup recovers interrupted jobs under the exclusive worker lock. SQLite snapshots are consistent with WAL, but concurrent uploads prevent a guaranteed database/filesystem boundary. Backups are private: they contain config, applicant receipts and evidence.

```powershell
Set-Location D:\projects\FraudLens-2.0\FraudLens-2.0-Backend
$pilotBackup = 'D:\projects\FraudLens-2.0-preservation\backup-' + (Get-Date -Format 'yyyyMMdd-HHmmss')
.\venv\Scripts\python.exe -X utf8 scripts/pilot_backup.py backup . $pilotBackup
$pilotRestore = $pilotBackup + '-restored'
.\venv\Scripts\python.exe -X utf8 scripts/pilot_backup.py restore $pilotBackup $pilotRestore
```

The script rejects existing destinations, consistently backs up root/nested SQLite databases, copies evidence/outputs/models/backend config plus `.bak` / `.db.old` archives, and verifies manifest hashes/database integrity during restore. Initial preservation separately includes frontend config/audit/source patches. Preserve frontend `.env` privately too. Restored databases retain stored evidence paths: inspect/rebase paths on a copy before relocation/promotion. The drill verifies artifact integrity, not relocated deployment or a recovery-time objective.

## Outstanding production requirements

One `local` organization and its roles are implemented. Cases/evidence are not tenant-keyed; complete tenant isolation and cross-tenant tests are absent. Multi-organization SaaS requires isolation across all queries/routes/storage/reports/exports/jobs. Also outstanding: verified applicant identity/receipt recovery, MFA/account recovery, hosting/secrets/TLS, distributed execution if needed, storage lifecycle/encryption/privacy, tamper-resistant audit, central monitoring/alerts, load/security review and independent detector/adjudication validation.

Supported evidence is photographs. Invoice/PDF extraction, identity/ownership validation and verification that underwriting slots contain real views of the same vehicle remain unimplemented. Live successful vision/adjudication remains blocked by the observed provider failures. Billing and external deployment were outside this local demonstration.
