# Emergency partial-review release — 23 October 2026

This section supersedes the operating instructions and failure wording below.
Baseline: `b2eff6b508d0a5d52c9e9358b3dd145577576934`, including implementation
`9d240d0`. No later commits were present. Unrelated staged/working changes remain
preserved. Use `git log -1 --format=%H` for the final local patch commit.

**The application remains useful with Gemini paused.** New jobs record
`completed_partial` only after local checks, findings, explanation and the report
snapshot persist. The status and snapshot commit atomically. Missing files,
database writes, snapshot failures and worker interruption remain genuine failures.
No model recommendation, risk number, approval or successful live AI result is
manufactured. Incomplete risk stays neutral; human decisions remain separate.

Older failed runs are not rewritten. The two presentation cases show **Ready for
manual review — AI unavailable** through a derived summary requiring saved
findings, a saved snapshot and provider-only diagnostics. Their stored status
remains `failed`. Technical diagnostics show the original status, sanitized
category/time/attempts/retryability. Customer wording is **Your application is
saved and awaiting review**; existing genuine evidence requests/outcomes remain.
An outage alone does not justify replacing a valid photo or alleging fraud.

## Current dataset and exact presentation sequence

The running API and worker select **`fraudlens_validation_panel_20261022`**,
with its existing `outputs/final_presentation/rehearsal/uploads` evidence and
database PDF persistence. They share the unchanged original provider ledgers.
The admin **Active dataset: Presentation cases** banner prevents silent confusion
with the separate normal pilot. There is no fake/intercepted presentation mode.

1. Open [customer](http://127.0.0.1:5173/dashboard) and
   [admin](http://127.0.0.1:5173/admin) in two normal Chrome tabs. Use the existing
   private rehearsal credentials from outputs/final_presentation/rehearsal/private-browser.json (backend-relative); no passwords are published or changed. Do not screen-share that private file.
2. In admin, click **Saved claims — partial local review**. This opens
   `case-95a28aea367c`, run `e98e025b4b4f4c34aebb6b6a18e54fb9`. Show actual local
   results, neutral incomplete risk, partial-review summary and saved PDF.
3. Click **Saved underwriting — partial local review** for `case-ac757ae6f8b1`,
   run `f5f91eb39c9b47f68eb282d5a38647f4`. The off odometer/unreadable plate are
   real evidence gaps; no successful live underwriting AI is claimed.
4. Preview/download the same saved PDF; show the existing reviewer evidence
   request in the customer tab. New explicit manual approvals/rejections require
   rationale and acknowledgement; they are human actions, not automated clearance.
5. For instant prior successful claims evidence, open the unchanged
   [previously recorded nine-page PDF](normal_operation/claims-live.pdf). It is
   **Previously recorded analysis**, not a new inference. To inspect it inside
   the application, switch to **Pilot** as described below and click the dated
   **Previously recorded analysis** button. It selects `case-e4f345a50f26`, saved
   run `bbb9ed14d1c28c961b74093212aa8a6e`. There is no successful live underwriting
   result to show. Even this earlier successful execution had incomplete evidence.

The 4/6 initial photo rules and server relevance gate are unchanged. New valid
submissions can finish available local work with AI paused. This patch adds no
new business-schema cases; controlled new jobs were tested in disposable schemas.
Licensed real photographs and their limitations remain in
[the photo provenance](presentation_assets/README.md).

## Starting and selecting the dataset

From `FraudLens-2.0-Backend`, inspect the selection:

```powershell
.\scripts\start_review.ps1 -Dataset Panel -Service Info
```

Stop only owned API/worker processes after checking the queue is idle. Do not run
two APIs on port 8001. Start API and worker in separate terminals with the **same**
dataset. Wait for the validator capability to be ready before cold-starting OCR.

```powershell
.\scripts\start_review.ps1 -Dataset Panel -Service Api
.\scripts\start_review.ps1 -Dataset Panel -Service Worker
```

Use `-Dataset Pilot` in both commands for `fraudlens_pilot` and its original
`outputs/pilot_validation/uploads`. The worker launcher verifies the actual API's
schema, evidence directories and original provider-control paths before starting;
a mismatch fails clearly. Neither launcher merges schemas, creates new accounts,
enables generation, changes ownership or clears a stop. The frontend stays on
port 5173 and does not need a rebuild for a database selection change.

Frontend, from `FraudLens-2.0-Frontend`:

```powershell
$env:NITRO_HOST='127.0.0.1'
$env:NITRO_PORT='5173'
node .output/server/index.mjs
```

Health: [http://127.0.0.1:8001/health](http://127.0.0.1:8001/health).
API: [http://127.0.0.1:8001/docs](http://127.0.0.1:8001/docs).
Health distinguishes ready core capabilities from degraded AI. Overall `/ready`
remains HTTP 503 for the preserved provider pause; this does not prevent saved
review, local processing, manual decisions or report access. No global AI-ready
claim is made. For foreground starts use Ctrl+C on owned terminals with an idle
queue. Final owned PIDs/configuration are in the emergency operational receipt.

## Database and safe rollback

Migration **003_partial_review.sql** extends only the durable job status check.
Existing payload/status equality, active-job uniqueness, roles and history remain.
Private consistent backups of both schemas, filesystem evidence and original
provider controls preceded the explicit upgrade. Versions 001/002 were retained.
No Supabase Storage migration, bucket, upload relocation or deployment occurred.

In Supabase Table Editor select `fraudlens_validation_panel_20261022` or
`fraudlens_pilot`, not `public`. In SQL Editor, safe counts are explicit:

```sql
select count(*) from fraudlens_validation_panel_20261022.cases;
select status, count(*) from fraudlens_validation_panel_20261022.api_jobs group by status;
select count(*) from fraudlens_pilot.cases;
```

An empty public schema says nothing about these private schemas. Browser roles
still do not gain direct database access. Evidence remains on the private local
filesystem; snapshots/PDF bytes remain in PostgreSQL.

Operational rollback: stop owned services with an idle queue, retain backups and
controls, then select **Pilot** for the original dataset or an earlier immutable
PDF version. Keep migration 003. Do not run an old backend that rejects the new
terminal status against new records, reset ledgers, downgrade constraints, rewrite
old failed states or restore a backup over newer human decisions. A code rollback
needs a compatibility patch preserving the additive status/reader support.

## Verification and limits

- Final renderer v11: both saved PDFs are 11 pages, all 22 pages rendered and visually inspected. Native Chrome preview/download, first-page reviewer action and case switching passed.
- Changed-file integrity and API-to-worker drift guards each passed their focused test.
- Controlled outage/local-check/manual-outcome, required photo and customer tests:
  **63 passed**. Additional engine/cache/recovery/PDF regression: **43 passed**.
  Isolated new suite: **12 passed**; suites overlap.
- Actual disposable PostgreSQL tests: **2 passed**, claims and underwriting,
  including constraint, durable acquisition, atomic snapshot and saved PDF reuse.
- Frontend typecheck and production build passed. A real browser rehearsal verifies
  the two saved partial cases, case switching, customer updates, mobile layout and
  native PDF preview/download. See the emergency artifact receipt for final proof.
- New model generation **0**; cumulative attempts remain **17**. Existing manual
  pause, provider history, daily/per-case limits and closed prior task are intact.
  No metadata probe, quota increase, credential/billing change or historical batch.
- Normal cache reuse now requires exact image hash, requested model, prompt hash,
  structured schema and profile. Unqualified older observations are not treated as
  current image-specific inference. Missing inputs stay unavailable/not run.
- Renderer **fraudlens-pdf-2026-10-23-v11** prepares a new snapshot/artifact from
  available saved results. Earlier PDFs remain unchanged. Native preview/download
  do not run AI or checks. No weights or production routing thresholds changed.

See [emergency artifacts](emergency_partial/README.md). Earlier handover/test
evidence is retained below as history and does not describe the current dataset.

---

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
