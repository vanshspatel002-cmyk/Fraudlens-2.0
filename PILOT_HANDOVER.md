# FraudLens local pilot handover

This change continues the existing FastAPI/SQLite and React/TanStack project. It improves a single-instance, two-tab pilot. It is **not a completed multi-tenant SaaS release**, and it does not establish detector accuracy or guarantee Gemini availability.

## Changes

- `FraudLens-2.0-Backend/src/api.py`: server-validated admin email/password exchange, eight-hour revocable sessions, authenticated action attribution, private/public narrative separation, server-side image validation, unique stored filenames, rollback on indexing failure, real perception before the live API check pipeline, visible processing failures, persisted job retrieval, repeat-job conflict handling, a finding-counts endpoint, latest-decision statistics, latest-run trace selection and lightweight readiness endpoint.
- `FraudLens-2.0-Backend/src/runtime_store.py`: additive SQLite tables for hashed session tokens and job status. Startup marks interrupted queued/running jobs failed so reviewers can retry. It does not automatically resume or provide a distributed queue.
- `FraudLens-2.0-Frontend/src/experience/shared.tsx`: session token handling in sessionStorage, server login/session/logout, correct desk-review labels, actual audit entries, retry mapping, thumbnail reuse and removal of duplicate sort parameters.
- `Admin.tsx`, `AdminOverview.tsx`: queue refresh every ten seconds while visible, retry/refresh controls, fallback disclosures, heuristic confidence disclosure and accurate page-scoped metric labels.
- `Intake.tsx`: accepted case confirmation survives failed background analysis. `Tracker.tsx`: distinguishes status-check time from a server update time. `Home.tsx`: product wording retains detection limitations.
- `FraudLens-2.0-Backend/railway.json`: readiness uses `/ready` without spending model quota.
- `FraudLens-2.0-Backend/test_pilot_workflow.py`: isolated API regressions. Vision gate and embeddings are mocked; these tests do not measure detection.
- `FraudLens-2.0-Backend/test_api.py`: expectations updated for authenticated reviewer identity and public narrative privacy.
- `FraudLens-2.0-Backend/scripts/pilot_preflight.py`: dependency/configuration check, optional CLIP warmup and optional live model probe.

Research policies, detector weights and thresholds have not been changed. The existing ablation must not be continued with changed experiment inputs without a versioned decision.

## Local setup

Use your existing Python 3.12 environment if it already has the pinned backend dependencies and model files. Do not overwrite your current database or `.env` with this source export. Back up your database while the app is stopped before first run; runtime tables are additive.

In the backend directory:

```text
python -m pip install -r requirements.txt
python scripts/pilot_preflight.py
```

The pinned requirements include CPU Torch packages; a Mac may need platform-specific Torch installation. The full pinned ML environment has not been installed or validated in this review environment. If installation fails, preserve the exact error rather than replacing every version.

Configure backend `.env` using `.env.example`. Required local values include:

```text
ADMIN_EMAIL=your-reviewer-email
ADMIN_PASSWORD_SHA256=your-password-hash
GEMINI_API_KEY=your-key
GEMINI_MODEL=the-model-you-have-verified-access-to
LLM_PROVIDER=gemini
CORS_ORIGINS=http://localhost:5173
FRAUDLENS_DB=fraudlens.db
```

Do not paste secrets into chat or commit them. Generate the password hash with the existing frontend `npm run admin:password` helper. Login now requires the matching configured email as well as the password.

Optional preflight steps, from the backend directory:

```text
python scripts/pilot_preflight.py --warm-models
python scripts/pilot_preflight.py --live
```

Warmup can download model files. `--live` makes a real provider call and retries may consume more quota; it does not verify image analysis. Do not run it repeatedly during a presentation.

Start one backend process, without reload during the presentation:

```text
python -m uvicorn src.api:app --host 127.0.0.1 --port 8000
```

In a second terminal, from the frontend directory, use Node 22.16 or later within major version 22:

```text
npm ci
npm run dev
```

Set `VITE_API_BASE_URL=http://localhost:8000` in frontend `.env`. Open both Chrome tabs at `http://localhost:5173`. Keep the terminal processes running.

## Two-tab rehearsal

1. Check `http://localhost:8000/ready`. A ready response establishes database availability, not model availability.
2. Tab A: submit a claims application with a genuine, consented vehicle photo and realistic declaration. Save the returned case ID immediately.
3. Tab B: log in at `/admin`. The queue refreshes every ten seconds; open the new case and use Refresh case to retrieve updated processing status.
4. Inspect original stored findings, their attribution and limitations, the recorded trace, and the report. A fallback or failed job must be shown as such. Retry only after resolving the cause.
5. Record a human action. Enter a public message deliberately: it is the message the applicant sees. Internal reasons and model narratives are not returned by the public tracker.
6. Tab A: open `/track` with the case ID and original registration/policy number. Check the recorded human outcome.
7. Repeat for underwriting with the six views required by the existing form. This can consume substantially more vision quota than one claims photograph.
8. Use Print report for browser print/PDF. This is not a server-generated signed PDF report.

The API uses real perception and adjudication providers. It does not inject successful results or synthetic decisions into live submissions. Reusing a previously analyzed image may reuse its stored perception, which is existing content-hash caching, not a new model call.

## Gemini free-tier constraints

Stop competing research/perception batch jobs before rehearsal. Do not repeatedly resubmit or retry a case to force a desired verdict. Provider limits, delays and failures remain possible. The API retains evidence and makes failures visible; it cannot guarantee completion time or make quota available. Prepare an already completed **real** case as a disclosed backup, not as a fabricated result for a new submission.

## Remaining work and acceptance gates

- Live Gemini vision, adjudication, image gate, quota behavior and full browser rehearsal on the target laptop remain unverified here. No credentials or real corpus were supplied.
- Historical corpus and scenario-database evaluation requires your sanitized databases, image corpus and output artifacts. Blank local databases cannot demonstrate historical rings, repeat claims, external corpus matches or garage patterns without actual supporting records.
- AI-generated images and edited-image detection remain unproven for the uncovered archetypes. Zero-weight/retired checks remain as documented; they are not relabeled reliable.
- Request-more-evidence records and communicates a request; an authenticated applicant evidence-resubmission workflow remains to be implemented.
- Authentication is still one configured reviewer identity, now with expiring tokens. Per-user accounts, roles, tenant isolation, invitations and billing are not implemented. The legacy bearer-password interface remains for existing scripts.
- Job state is durable but execution still uses in-process background tasks. Single process only. Multi-worker durable execution, shared rate limits and interrupted-work recovery require further work.
- The current public tracker verifies a case ID plus registration/policy number, not a full applicant account.
- Reports retain model-generated prose and heuristic scores. Citations and recorded inputs support review; they do not guarantee every model statement is correct.
- Multi-tenant security review, backup/restore drills, production monitoring and independent detection validation remain release gates.

## Offline regression commands

From the backend directory:

```text
python -m pip install pytest
python -m pytest test_pilot_workflow.py -q
python test_models.py
python test_api.py
```

The legacy API runner additionally requires the corpus images and CLIP dependencies. The original agent runner expects `fraudlens.db`. Do not interpret missing-resource failures as model-accuracy measurements. Frontend validation: `npm run build` from its directory.

## Verification in this workspace

- Frontend TypeScript check and full Vite production build: passed on Node 22.23.3. The existing Nitro/Vite compatibility warning remains; no dependency upgrade was made.
- `python -m pytest test_pilot_workflow.py -q`: 11 passed.
- `python test_models.py`: 81 passed.
- Legacy API runner after intentional expectation updates: 21 passed, 4 failed because corpus photographs/CLIP dependencies were unavailable.
- Agent engine runner with two isolated in-memory fixture cases instead of the missing corpus DB: 15 checks passed; the SDK-schema test skipped because google-genai was absent (the legacy runner incorrectly includes that skip in its printed 16-pass total). This exercises mocked provider responses, not live Gemini.
- Python API import and changed-file compilation: passed. `git diff --check`: passed.
- The backend tests used available FastAPI 0.143.0 and Starlette 1.8.0, not the project's complete pinned production environment. Re-run on the target laptop's pinned environment.
- Live providers, all-archetype performance, actual browser interaction and multi-user/tenant isolation: not verified.

## Applying this source package

The download contains source, not your database, `.env`, image corpus, virtual environment or `node_modules`. Extract into a separate folder or apply the accompanying patch on a clean checkout of baseline commit `f30cd20f0d021e1dd670e49deb33a20dd96ed19f`. Keep a backup of local work first. Restore/configure your local resources deliberately; do not overwrite them with empty files.

```text
git switch -c pilot-workflow
git apply --check /path/to/FraudLens_Pilot_Changes.patch
git apply /path/to/FraudLens_Pilot_Changes.patch
```

Stop if the check reports a conflict; it indicates local differences that must be reviewed. These changes have not been pushed to GitHub or deployed.
