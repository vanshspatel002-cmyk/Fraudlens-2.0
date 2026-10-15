# Two-tab local demonstration

## PostgreSQL pilot — 15 October 2026

Use the migrated private `fraudlens_pilot` schema and unchanged local evidence.
The original SQLite demo remains the rollback source. Read
[POSTGRES_MIGRATION.md](POSTGRES_MIGRATION.md) for migration scope, validation,
backup/restore and rollback. DATABASE_URL stays privately in backend `.env`.
Do not use Supabase Auth, a browser database key or direct database access.

Start the API first and wait for **Application startup complete**:

```powershell
Set-Location D:\projects\FraudLens-2.0\FraudLens-2.0-Backend
.\scripts\start_pilot.ps1 -Database postgresql -Port 8002 -NoWorker
```

In a second backend terminal, start processing and wait for **Worker OCR warmup:
ready** (or its explicit unavailable limitation), then **Durable worker started**:

```powershell
Set-Location D:\projects\FraudLens-2.0\FraudLens-2.0-Backend
.\scripts\start_pilot.ps1 -Database postgresql -WorkerOnly
```

The separate process uses the existing durable queue/pipeline. It prevents cold
native checks from stalling HTTP/evidence requests. Authenticated
`/v1/operations` exposes `database_worker_leader_present`; the API's own worker
thread is intentionally inactive in this setup. Run model warmups, builds and
heavy tests sequentially on this 8 GB Windows host.

In the frontend terminal:

```powershell
Set-Location D:\projects\FraudLens-2.0\FraudLens-2.0-Frontend
$env:VITE_API_BASE_URL = 'http://127.0.0.1:8002'
npm.cmd run dev
```

Open `http://127.0.0.1:5173` in both Chrome tabs. Follow the claims and underwriting
steps below. Keep the applicant tab unauthenticated and preserve its private
receipt. Reviewer credentials are unchanged by migration; the ignored local
fixture is `outputs/pilot_validation/demo_credentials.json`. No credential is
included in this document. Both helper modes retain the original stopped live
ledger, rollback path, uploads and thumbnail directory.

For a new recorded automated rehearsal (backend directory):

```powershell
$env:PILOT_UI = 'http://127.0.0.1:5173'
$env:PILOT_API = 'http://127.0.0.1:8002'
$env:PILOT_DB = 'postgresql'
$env:FRAUDLENS_PG_SCHEMA = 'fraudlens_pilot'
$env:PILOT_EXPIRE_SESSION = '1'
$env:PILOT_OUTPUT_DIR = Join-Path (Get-Location).Path ('outputs\pilot_validation\postgres\browser-' + (Get-Date -Format 'yyyyMMdd-HHmmss'))
.\venv\Scripts\python.exe -u -X utf8 scripts/verify_browser_pilot.py --workflow both
```

The expiry opt-in modifies only the exact session this rehearsal created. A new
output directory preserves earlier observations/PDFs. `--workflow claims` or
`--workflow underwriting` allows independent runs. `--resume-review <case-id>`
finishes human review/tracking on an already submitted case without reuploading
or reprocessing. Do not use it to claim previously unobserved intake steps.
All demonstrations below concern fictional submissions using existing stock
research photographs, not real eligibility decisions or detection accuracy.

Current observed PostgreSQL outcomes and earlier failures are recorded in
[AUTONOMOUS_PROGRESS.md](AUTONOMOUS_PROGRESS.md). Gemini remains stopped at the
same two prior HTTP 503 failures; no new successful live adjudication is implied.

## Preserved flow instructions and earlier SQLite rehearsal

The flow steps below apply to both backends. For the qualified PostgreSQL pilot,
use API 8002 and the separate worker commands above; the earlier SQLite startup
in [PILOT_HANDOVER.md](PILOT_HANDOVER.md) remains historical. Wait for CLIP/OCR
warmup and `/ready` before presenting. Do not run a build or ML suite alongside
the demonstration.

This session made two actual Gemini vision attempts; both returned HTTP 503. Further live requests are stopped. The demonstration therefore shows accepted evidence, deterministic/cached checks, incomplete automated analysis and a disclosed human-review fallback. It must not be presented as successful live Gemini adjudication or validated fraud detection.

## Claims: applicant tab

1. Open `http://127.0.0.1:5173/apply/claims`. Leave this tab unauthenticated. Open `http://127.0.0.1:5173/admin` in a second tab and sign in with an individual local reviewer/admin account.
2. In the applicant tab, try submitting an empty form. Required fields should prevent submission and focus an invalid field. Complete the identity/contact, vehicle, registration/policy, incident, amount, settlement and declaration fields. Use demonstration details, acknowledge consent and select a genuine existing vehicle photograph. No authenticity/ownership is implied by acceptance.
3. Submit once. A valid upload receives a case ID and immediate confirmation after local admission/indexing, before background model processing completes. Save the case ID and private evidence receipt; this receipt permits later requested uploads. The applicant tab must not contain a reviewer session.
4. Confirmation/job status distinguishes queued/running from completed/failed/interrupted. If models fail, evidence remains accepted and the confirmation states that automated analysis is incomplete. Do not resubmit the whole form to compensate for a failed model run; its session-held idempotency key protects an accidental retry of the same accepted payload.

## Claims: reviewer tab

1. Return to the reviewer tab, select Case queue, search the complete case ID and open the case. Visible queues refresh every ten seconds; Refresh case fetches the latest details. Current-run findings appear only after that run persists them.
2. Verify declaration, processing status and actual recorded findings. Open a photograph and confirm the original resolution; Escape closes the viewer. Do not infer fraud from a filename, case ID, check count or heuristic score.
3. Open Agent Trace and Report. Distinguish the agent recommendation from the human decision. An outage fallback is explicitly disclosed and successful live reasoning is not claimed. Check run ID, policy version, missing/inconclusive evidence and per-check limitations.
4. Print report opens browser printing. Headless Chrome PDF generation was tested for readable content, run/case identification and findings; manual OS print/Save-as dialogs remain unverified. For live presenting, inspect the preview before saving.
5. Select Request More Evidence. Give an internal rationale, a separate public explanation and specific requested photographs, one per line, such as “Original rear view including the registration plate.” Record human decision. Server attribution must use the authenticated reviewer, never a submitted reviewer name. Stale revisions conflict and require refresh.

## Requested evidence and final human review

1. In the original applicant tab, follow Track this case or open `/track?case=<case-id>`. Enter the original registration/policy challenge and Check status. Only the public explanation/status/request should appear, without internal findings, traces, scores or private rationale.
2. Requested photographs are listed. The original tab restores its private receipt from session storage. In a different tab/device the applicant needs the saved receipt; registration/policy alone does not authorize uploads. This bearer receipt is a pilot capability, not verified identity or a recoverable applicant account.
3. Upload a different valid requested photograph and submit. The original photographs remain; identical bytes, invalid files, another case's receipt, expired receipts, stale requests and active-run conflicts are rejected. The request closes and a controlled new run queues. Closeups need not pass the whole-vehicle intake gate, but must decode/index successfully.
4. Return to the reviewer tab and refresh. See original plus supplementary evidence. Current findings/decision belong to the new run; previous reports are in Report history. Select a saved report and confirm its earlier run, declaration and human action. Escape closes the historical report dialog.
5. After reviewing the actual evidence and limitations, record an appropriate human approve/reject/evidence-request action. Automated failure alone does not establish fraud. The automated rehearsal used an explicitly labeled approval of a fictional local demonstration to verify plumbing; it was not an insurance eligibility decision.
6. Recheck the public tracker. Final approved/rejected status and only the public human explanation should update. Log out in the reviewer tab and confirm protected access is revoked.

## Underwriting

Repeat the same two-tab flow at `http://127.0.0.1:5173/apply/underwriting`, with the underwriting application/condition fields and all six photograph slots: front left, front right, rear left, rear right, odometer and registration plate. Verify queue workflow, declaration notes, processing failure/success, original evidence, current findings, trace/report, specific evidence request, secure supplement, report history and public human outcome.

Slots/labels are applicant declarations; this pilot does not validate six actual views of the same vehicle. The automated rehearsal used six distinct existing research photographs, rather than inventing consistent same-vehicle evidence. Selecting “Unsure; inspection needed” must not become an invented undamaged declaration. Production v2 and current v3 preserve actual notes and mark zero-weight experimental baseline findings inconclusive.

## Earlier SQLite automated replay and observations — 14 October

This section preserves the earlier port-8001 rehearsal. For the qualified
PostgreSQL pilot, use the new port-8002/output-directory commands above.

The private demo account fixture exists at `outputs/pilot_validation/demo_credentials.json` and must remain ignored/unshared. The script uses two pages in one installed headless Chrome browser, actual HTTP uploads and actual local checks; it does not intercept/fake provider responses. It writes logs, screenshots, PDFs and incremental observations to the ignored `outputs/pilot_validation` directory. It creates new cases and preserves old ones.

```powershell
Set-Location D:\projects\FraudLens-2.0\FraudLens-2.0-Backend
$env:PILOT_UI = 'http://127.0.0.1:5173'
$env:PILOT_API = 'http://127.0.0.1:8001'
.\venv\Scripts\python.exe -u -X utf8 scripts/verify_browser_pilot.py
```

The final observed completion, earlier actual failures and fixes are recorded in [AUTONOMOUS_PROGRESS.md](AUTONOMOUS_PROGRESS.md). Both workflows passed through human/public outcome in run 13; its final mobile harness call failed. The corrected continuation passed expiry/logout/mobile checks, and a later latest-source smoke reopened the same saved report twice. Preserve earlier logs; `browser_verification.json` retains the flow and continuation observations, including failures. Some failed rehearsals accepted cases before the browser timed out; those cases remain in the isolated database. Do not delete them to conceal failure.

Unverified browser coverage: visible/manual Chrome interaction, OS print/Save-as dialogs, screen-reader behavior, every viewport/control, long-running successful live agent traces and all frontend security threat scenarios. Focused API tests provide additional authorization/rollback/restart coverage; mocked tests do not validate live model reliability. A 390 px tracker layout and Escape dismissal were checked separately.

## Troubleshooting

| Observation | Next step |
|---|---|
| `/ready` unavailable before startup complete | Wait for warmup; inspect model/startup logs. Missing cached weights are a dependency issue. |
| Submission remains uploading | Check admission/model warmup and request log. Preserve the form/idempotency key; do not repeatedly submit a changed payload. |
| Case accepted but analysis failed | Read the explicit limitation/job details. Evidence is preserved; do not claim a model success. |
| Active-job conflict | Refresh and wait for queued/running work. Retry only terminal work. |
| Evidence duplicate/request closed | Refresh tracker/request and select the actual newly requested photograph. |
| Reviewer session expired/rotated | Sign in again with authorized credentials. Do not enable legacy raw-password access. |
| CORS/CSP failure | Match the configured local API origin and frontend origins. Do not disable browser security. |
| Queue looks stale while tab hidden | Bring it forward and Refresh case; background refresh intentionally pauses. |
| Dev frontend disrupted after build | Run dev and build sequentially and restart the standard dev command. |
| Gemini quota/repeated failure stop | Keep this session stopped and continue with cached/offline verification. Do not reset the ledger. |

Backups/restore, monitoring, independent accuracy and production SaaS gaps are documented in the handover and check matrix. No billing, deployment or tenant isolation is represented by this demonstration.
