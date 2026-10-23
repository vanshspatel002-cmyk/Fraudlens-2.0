# Final presentation handover — 23 October 2026

Verified implementation commit: `9d240d0cc3645ccea701f5c47d786f32af54e947`. This documentation follow-up
records that tested release; `git log -1 --format=%H` identifies the final local
documentation commit. No push or deployment.

**The local application, real photo admission, durable persistence, saved PDFs and
reviewer/customer updates work for both case types. Fresh AI processing is blocked
by two actual Gemini HTTP 503 `UNAVAILABLE` responses. The provider remains paused.**
Do not describe either new rehearsal as a completed live AI analysis.

Inspected baseline: `0024843f5bb9ab370570afffa1dbf336ed301b41`, branch
`repair/analysis-pipeline-20261020`. No later commits or applicable `AGENTS.md` were
found. The release is the commit containing this handover; obtain its exact ID with
`git log -1 --format=%H`. Existing staged documentation and unrelated frontend/API
edits were retained separately. Verification used the actual working tree, including
those preserved transport/evidence changes. No dependency upgrade, deployment,
training, billing action, credential rotation or historical reprocessing occurred.

## What to present

| Acceptance item | Claims | Underwriting |
|---|---|---|
| Initial submission with real photo gate | **Passed**, 4 distinct real photographs | **Passed**, 6 distinct real same-car photographs |
| Live processing | **Blocked**, two fresh Gemini HTTP 503 responses | **Blocked**, no HTTP generation after the provider pause |
| Assessment completeness | **Incomplete**: perception/incident/damage/identity gaps | **Incomplete**: perception, unreadable plate and powered-off odometer; saved historical-policy gaps also retained |
| PDF preview/download | **Verified**, native headed Chrome, matching saved bytes, every page rendered | **Verified**, same checks |
| Reviewer/customer outcome | **Verified**, fictional request for evidence appears to customer | **Verified**, fictional request for readable registration/odometer appears to customer |

Both new durable runs correctly remain `failed` / `needs_review`, with a fallback
source, no converged model recommendation, no numeric production score, and a
neutral **Assessment incomplete** risk indicator. A human request for evidence
changes the public case to `awaiting_evidence`; it does not rewrite execution
history or assert fraud. No new successful perception, agent turn or tool exchange
is claimed. Real OCR and deterministic/local checks did execute and persist.

Full evidence, measurements, test results and limitations are in
[FINAL_PRESENTATION_VERIFICATION.md](FINAL_PRESENTATION_VERIFICATION.md).

## Running URLs and capability state

- Customer: [http://127.0.0.1:5173/dashboard](http://127.0.0.1:5173/dashboard).
- Claims form: [http://127.0.0.1:5173/apply/claims](http://127.0.0.1:5173/apply/claims).
- Underwriting form: [http://127.0.0.1:5173/apply/underwriting](http://127.0.0.1:5173/apply/underwriting).
- Admin: [http://127.0.0.1:5173/admin](http://127.0.0.1:5173/admin).
- API: [http://127.0.0.1:8001/docs](http://127.0.0.1:8001/docs).
- [Health](http://127.0.0.1:8001/health) returns HTTP 200 with degraded status while
  the provider is paused. [Readiness](http://127.0.0.1:8001/ready) returns HTTP 503
  `PROVIDER_NOT_READY` once local components are ready. Inspect the capability body;
  this intentionally does not advertise a working AI provider.

Final services use the original PostgreSQL `fraudlens_pilot` schema, original
private evidence paths and shared ledgers. The final operational receipt is
[operational-state.json](final_presentation/operational-state.json). The queue is
checked before handover; no automated workload is left scheduled.

The new fictional cases live in **`fraudlens_validation_panel_20261022`**, with
separate evidence storage. They do not appear in the restored pilot dashboard.
Their actual saved reports are [claims.pdf](final_presentation/claims.pdf) and
[underwriting.pdf](final_presentation/underwriting.pdf); screenshots and provenance
are linked from the [artifact index](final_presentation/README.md).

## Exact PowerShell startup and stop commands

From the repository root, start the API in one terminal:

```powershell
Set-Location .\FraudLens-2.0-Backend
$env:FRAUDLENS_PROFILE_STAGES='1'
.\scripts\start_pilot.ps1 -Database postgresql -Schema fraudlens_pilot -Port 8001 -NoWorker
```

Wait for `/ready` to show `capabilities.validator = ready`, then start the worker
in a second terminal. Serialize these cold model loads on the 8 GB laptop.

```powershell
Set-Location .\FraudLens-2.0-Backend
$env:FRAUDLENS_PROFILE_STAGES='1'
.\scripts\start_pilot.ps1 -Database postgresql -Schema fraudlens_pilot -WorkerOnly
```

Start the already-built frontend in a third terminal:

```powershell
Set-Location .\FraudLens-2.0-Frontend
$env:NITRO_HOST='127.0.0.1'
$env:NITRO_PORT='5173'
node .output/server/index.mjs
```

Do not start a second listener while the supplied services are running. Use
`Get-NetTCPConnection -LocalPort 8001,5173 -State Listen` to identify listeners.
For foreground starts, stop the owned terminals with Ctrl+C after ensuring no
job is running. For this task's hidden starts, use the owned process IDs recorded
in the operational receipt; first recheck their command lines with
`Get-CimInstance Win32_Process -Filter "ProcessId = ACTUAL_PID"`, then
`Stop-Process -Id ACTUAL_PID`. Do not terminate all Python/Node/Chrome processes.
Stopping only the API does not stop the dedicated worker.

No frontend rebuild is needed to switch the server's database schema. Changing
`VITE_API_BASE_URL` does require `npm run build` and a Node restart. The actual
local build uses `http://127.0.0.1:8001`. Both `localhost:5173` and
`127.0.0.1:5173` are allowed CORS origins; use one browser origin consistently.

## Provider controls and the precise next step

The final controls preserve the original 15 events and all earlier recoveries.
This task made **2** new generation attempts; cumulative count **17**. No metadata
request or underwriting generation request occurred. The allowance was 30 new
attempts, ceiling 45. Its **28 unused slots are closed**, not a background grant.

The existing operating limits remain one case, 30 attempts per Pacific day,
16 per case across runs, eight agent turns, two-second pacing and at most two
application attempts per call. SDK transport retries are disabled. The original
quota ledger still applies its stricter 20/key/day and aggregate/consumer limits.
These are local controls, not evidence of Google account quota or entitlement.

At final inspection the Pacific application day contains two attempts: numerical
daily headroom 28; the selected-key ledger has 18 of its 20 local reservations
remaining. Neither is usable while paused. These daily counters are separate
from the closed 28 unused task slots and do not establish Google account capacity.

The actual blocking responses were HTTP 503 `UNAVAILABLE`, not an authentication,
invalid-schema or billing response. Both fresh failures are retained in the
shared ledger. The two-failure transient circuit and explicit operator pause
are preserved; restarting does not clear them. Wait for provider availability,
inspect the controls and idle queue, then intentionally resume under the existing
limits. Do not reset a ledger or retry an old historical corpus.

Find the actual API PID, then run in the backend directory:

```powershell
.\venv\Scripts\python.exe scripts/operate_provider.py status --process-id ACTUAL_API_PID
.\venv\Scripts\python.exe scripts/operate_provider.py pause --process-id ACTUAL_API_PID --operator local_operator --reason "Pause new provider attempts"
# Only after the service incident is resolved and the circuit cooldown has elapsed:
.\venv\Scripts\python.exe scripts/operate_provider.py resume --process-id ACTUAL_API_PID --operator local_operator --reason "Provider availability inspected; permit bounded normal recovery"
```

Resume preserves stop history and permits the existing serialized half-open
recovery; it does not create a successful result or bypass provider restrictions.
The next live verification should be **one new ordinary claims case** using the
required four photos. Estimate four perception calls plus up to eight agent turns
(normally fewer); all retries count toward the 16/case and daily controls. Do not
repeat a generic probe. Minimum fresh calls are five for claims (four perceptions
and one final agent response) and seven for six-photo underwriting. Tool/correction
follow-ups add turns. The enforced maximum is 16 attempts per case including
retries; exhausting it must yield a partial/blocked result, not a promise that
every eight-turn/retry path fits. Underwriting needs current readable mileage/registration
evidence before a sufficient assessment can be expected; admission success alone
does not supply that information. A live full underwriting pipeline remains
unverified.

## Accounts, photos and a short panel walkthrough

Use the existing private pilot reviewer credentials; no password is in these
documents. Customer self-registration is available on `/dashboard`. Provision a
reviewer through the actual interactive management script:

```powershell
Set-Location .\FraudLens-2.0-Backend
.\venv\Scripts\python.exe scripts/manage_reviewer.py --help
$env:FRAUDLENS_PG_SCHEMA='fraudlens_pilot'
.\venv\Scripts\python.exe scripts/manage_reviewer.py --db postgresql --email reviewer@example.test --role reviewer
```

Run with `FRAUDLENS_PG_SCHEMA=fraudlens_pilot` and the private pilot environment
loaded; use a new intended reviewer email. The script prompts for its password
and revokes prior sessions if the account already exists. Do not paste passwords
into shell history or commit them.
Private rehearsal account material remains in the ignored rehearsal directory.

1. Open customer dashboard and admin in two ordinary tabs of the same Chrome
   context. Explain the separate customer/admin sessionStorage keys.
2. Show the exact four/six slots, local validation, manual incident coordinate
   pair and explicit timezone. A slot label is an applicant declaration; passing
   relevance does not independently establish view, identity or authenticity.
3. Show the already recorded incomplete case/PDF and the evidence request/customer
   update. Explicitly identify the fresh provider outage; do not promise live AI.
4. For a successful previously recorded AI example, use the saved-case fallback
   below. Explain the model-selected routing, material-evidence guard, neutral
   incomplete risk and separately labelled shadow index. No fraud probability
   or automatic human approval is implemented.

Licensed real source photos and the precise 4/6 mapping are in
[presentation_assets/README.md](presentation_assets/README.md). They are original
2005 Chevrolet Classic photographs by Milkmandan~commonswiki, **CC BY-SA 3.0**.
Retain attribution/license when presenting or sharing. The same-car series is
supported by the published series and visual details, not authenticated identity.
The display is powered off and the photos do not prove the fictional loss.
They were not added to the pilot reference corpus.

To inspect the two new cases interactively, first stop the pilot worker and API
after checking the queue. Start the existing isolated schema without a worker:

```powershell
.\scripts\start_pilot.ps1 -Database postgresql -Schema fraudlens_validation_panel_20261022 -Port 8001 -RuntimeDirectory .\outputs\final_presentation\rehearsal -NoWorker -NoWarmup
```

This exposes real saved cases, not an intercepted/fake presentation mode. The
closed task does not authorize generation in that schema. Do not submit or
reprocess there. Restore the two default pilot startup commands afterward.

## Clearly labelled saved-case fallback

The original pilot case **`case-e4f345a50f26`**, run
**`bbb9ed14d1c28c961b74093212aa8a6e`**, previously recorded one fresh perception,
two real agent turns and one history tool exchange. Use the unchanged
[nine-page saved PDF](normal_operation/claims-live.pdf) during a provider outage.
Its processing completed, but its evidence assessment was incomplete and a human
requested evidence. This is a historical recorded result, not today's fresh run
or verified clearance. There is no corresponding successfully live-verified
underwriting fallback.

## Source changes and rollback

The exact focused source-file list and purpose are in the verification document;
`git show --stat HEAD` includes the licensed artifacts and updated handovers.
New renderer **`fraudlens-pdf-2026-10-23-v9`** preserves earlier artifact bytes.
Coverage **`material-evidence-2026-10-22-v3`**, explanation v5, risk presentation
v2 and checks revision **`production-checks-2026-10-23-v5`** separate execution,
applicability, evidence sufficiency, model recommendation and human action.
The two saved runs predate the final applicability correction; their older
conservative gaps are preserved rather than rewritten or reprocessed.

For rollback, stop owned services with the queue idle, retain the current data,
evidence, provider controls and private backups, then revert only this release's
focused code commit after preserving unrelated work. Never reset provider files,
overwrite original reports, restore business backups over newer decisions or
bulk-enqueue historical records. Versioned prior PDFs continue to open. The
existing claims-only dry-run/batch plan remains unexecuted; underwriting history
is deferred.
