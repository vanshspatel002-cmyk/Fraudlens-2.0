# FraudLens 2.0 pilot handover — 14 October 2026

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
