# FraudLens deployment configuration — 18 October 2026

Prepared locally; no hosting, TLS, public-origin CORS, volume attachment, or
redeployment has been verified. Existing Railway/Vercel files are configuration,
not proof that the application is deployed.

The presentation uses PostgreSQL for accounts/sessions, ownership, cases,
evidence references, jobs/results, report snapshots/PDF bytes, decisions, and
audit history. There is no automatic SQLite fallback. Local SQLite remains an
explicit research/rollback option only.

## Runtime and migration

Backend: Python 3.12 (`runtime.txt`); install `requirements.txt`. Frontend:
Node 22.23.3 (`.nvmrc`, package engine >=22.16 <23). Build the existing frontend
with `VITE_API_BASE_URL=https://<backend-origin>`. This is a build-time value.
Never put DATABASE_URL, provider/service credentials or bootstrap hashes in
frontend environment variables.

Stop writers and make new private filesystem and logical backups first. An
existing version-001 PostgreSQL pilot upgrades additively:

```powershell
Set-Location D:\projects\FraudLens-2.0\FraudLens-2.0-Backend
.\venv\Scripts\python.exe -X utf8 scripts/upgrade_postgres.py --schema fraudlens_pilot
.\venv\Scripts\python.exe -X utf8 scripts/upgrade_postgres.py --schema fraudlens_pilot --apply
```

Version 002 adds customer accounts/sessions, explicit ownership, and PDF artifacts.
It does not assign historical cases by email. Applied SQL checksums are retained.
For a fresh import use `scripts/migrate_postgres.py` and the complete preservation
procedure in [POSTGRES_MIGRATION.md](../POSTGRES_MIGRATION.md). Never reimport a
historical SQLite corpus over a pilot that has accepted new applications.

## Private durable evidence and provider controls

The Path-based processing pipeline needs a **private persistent volume** shared
by the API and worker on one host. Provision it externally before startup.
Set `FRAUDLENS_PERSISTENT_ROOT` to its existing absolute mount (for example
`/data`). Evidence is never exposed as a public static directory. PDFs are
private PostgreSQL artifacts and downloads require a reviewer session.

Restore original evidence and the existing stopped provider ledgers onto the
volume. Preserve relative directories for historical research evidence, and set
`FRAUDLENS_DATA_DIR` appropriately; verify historical paths with
`scripts/audit_evidence_paths.py`. Windows absolute paths are not deployment
URLs; copy their files and migrate/validate references before presenting them on
another host. New uploads store server-side private paths and are served only
through authorized HTTP endpoints.

Required backend environment variable names (values belong in the host secret
store):

- `DATABASE_URL`, `FRAUDLENS_PG_SCHEMA`, `FRAUDLENS_PERSISTENT_ROOT`.
- `FRAUDLENS_UPLOAD_DIR`, `FRAUDLENS_THUMB_DIR`, `FRAUDLENS_DATA_DIR`.
- `FRAUDLENS_LIVE_LEDGER`, `GEMINI_QUOTA_BUDGET`, `GEMINI_QUOTA_CONSUMER`.
- `CORS_ORIGINS`: comma-separated exact HTTPS frontend origins, without wildcards.
- `ADMIN_EMAIL`, `ADMIN_PASSWORD_SHA256` only if retaining bootstrap access;
  prefer individual reviewer accounts.
- `GEMINI_API_KEY`, `GEMINI_MODEL`, `LLM_PROVIDER` for provider configuration;
  keep the existing ledger stop and call limits intact.
- `PORT` supplied by hosting; optional `FRAUDLENS_WARM_MODELS` and model cache
  configuration. Startup/readiness never spend AI quota.

Use a least-privilege backend database login before exposing a deployment.
Supabase browser roles have no access to the private application schema.
Supabase Storage buckets are not configured by this build. A mounted volume is
the selected evidence persistence strategy; multi-host object storage and shared
provider-budget coordination require additional work.

## Startup and readiness

Set the backend service root to `FraudLens-2.0-Backend`. Railway's existing
configuration runs a single API plus durable worker with a shared volume:

```text
python scripts/start_deployment.py --embedded-worker
```

For separate processes on the **same host and volume**:

```text
python scripts/start_deployment.py
python scripts/start_deployment.py --worker
```

The entrypoint refuses missing PostgreSQL credentials, a missing/relative volume,
paths outside the volume, missing preserved ledgers, and non-HTTPS/wildcard CORS.
Declaring a path cannot prove the hosting provider actually mounted it; test
restart/redeploy retention externally. Model weights must be available within
the host's memory/disk budget. Avoid warming multiple large model processes at
once on a small machine.

`GET /ready` checks the database schema and writable private storage, without a
provider probe. `GET /health` reports provider configuration without calling
Gemini or claiming connectivity. Authenticated `GET /v1/operations` reports
jobs, leadership and provider control status.

Sessions use separate, tab-scoped customer/reviewer opaque bearer tokens. They
do not rely on cross-origin cookies; HTTPS protects the Authorization header.
The frontend CSP permits authenticated blob image/PDF previews. Configure the
actual backend and frontend origins before building/publishing.

## Accounts and external verification

Customers register through `/dashboard` or either protected application form.
No password or consent suggestions are supplied. Provision reviewers locally
with the interactive password prompt (do not put passwords in arguments):

```powershell
.\venv\Scripts\python.exe -X utf8 scripts/manage_reviewer.py --db postgresql --email reviewer@example.test --role reviewer
```

The account must belong to the selected schema. This remains one organization,
with no email verification, MFA, or account recovery. Validate TLS, origin
headers, private file permissions, persistence after redeploy, memory/load,
monitoring, security/privacy requirements, and mobile access on the actual hosts
before asserting deployment readiness. Local tests do not establish these.
