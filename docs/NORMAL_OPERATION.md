# FraudLens normal local operation

The normal policy is stored under `operation` in the original private session
ledger. It was explicitly migrated from diagnostic operation, retaining all 11
previous attempt records, recoveries, stops, quota reservations and closed grants.
The old `FRAUDLENS_LIVE_LIMIT=15` remains a legacy diagnostic setting; it does not
disable migrated normal workers. A zero value still acts as a kill switch.
Local allowances do not establish available Google account quota.

## Controls

| Setting | Initial value / behavior |
|---|---|
| Active processing cases | One; existing PostgreSQL schema leadership |
| Daily attempts | 30 across consumers, Pacific quota day; historical calls that day also count |
| Per-case attempts | 16 across its runs, image requests, corrections, retries and agent follow-ups |
| Agent iterations | At most eight, including correction/tool follow-up turns |
| Application retries | At most two attempts per call; perception diagnostics retain one; SDK transport retries disabled |
| Pacing | At least two seconds after the previous provider attempt |
| Transient circuit | Two consecutive transient failures stop requests; one serialized half-open request after 30 minutes |
| Non-transient rejection | Authentication/access, invalid request/model and quota errors block further unchanged calls |
| Manual pause | Persisted; survives restarts. An in-flight request may finish, subsequent attempts are blocked |
| Existing quota ledger | Still enforced, including its stricter per-key/consumer limits; no key rotation on rejection |

`src/operating_policy.py` owns these defaults and their audited revisions.
`session_budget.py` retains the cross-process lock, atomic reservation and complete
attempt history. A worker must supply its actual schema/case/run context. The
normal policy accepts only the pilot schema. Unbound diagnostic calls cannot
silently borrow normal operation. Old isolated diagnostic grants remain closed.
Historical jobs additionally require explicit activation of their proposed run ID.

The implementation task has a separate, non-renewing ceiling of 41 cumulative
attempts (11 retained + at most 30 new). Its closure records the final count; it
does not create a scheduled workload or reset any daily counter.

## Startup and safe control commands

In `FraudLens-2.0-Backend`, use two terminals:

```powershell
.\scripts\start_pilot.ps1 -Database postgresql -Schema fraudlens_pilot -Port 8001 -NoWorker
.\scripts\start_pilot.ps1 -Database postgresql -Schema fraudlens_pilot -WorkerOnly
```

The existing backend `.env` supplies private PostgreSQL and provider settings.
The startup script selects the preserved ledger/storage paths and repaired
`gemini3_defaults_v2` request profile. It never migrates or reopens controls.
`FRAUDLENS_PROFILE_STAGES=1` enables content-free timings and memory counters.
Health is `http://127.0.0.1:8001/health`; readiness is `/ready`. Neither makes an
inference request. Cold CPU model imports/weights can delay startup substantially.

Find the **actual** API Python PID using the process listening on port 8001,
then substitute it for `API_PID` below. Diagnostics copy the running process's
effective configuration rather than selecting shell SQLite/default controls.

```powershell
.\venv\Scripts\python.exe scripts/operate_provider.py status --process-id API_PID
.\venv\Scripts\python.exe scripts/operate_provider.py pause --process-id API_PID --operator local_operator --reason "Pause new provider attempts"
.\venv\Scripts\python.exe scripts/operate_provider.py resume --process-id API_PID --operator local_operator --reason "Resume after inspecting provider and local status"
```

`resume` does not erase a circuit stop or bypass its cooldown. A quota/access/model
block requires diagnosis and a specific correction; it cannot be cleared by
restarting services. A received valid reply is checkpointed before parsing/cache/
database work. On the same run and exact request, a restart can reuse that saved
reply, labelled `response_checkpoint`, rather than generating again. A receipt
whose response bytes were lost requires explicit local reconciliation.
An already received agent turn replayed with changed finding IDs or other inputs
blocks generation until its original findings/reply are reconciled. A local
artifact failure does not authorize a replacement model request.

Intentional setting changes use `configure --daily-attempts N`, optionally
`--case-attempts N --agent-turns N`, with PID/operator/reason. Revisions are audited;
the current implementation task's conservative ceilings cannot be raised while it
is active. This changes application settings, not Google limits or billing.
Control mutations create private consistent ledger backups first.

In `FraudLens-2.0-Frontend`, development uses `npm run dev`. For a production local
preview, stop the old Node server **before** `npm run build`, then:

```powershell
$env:NITRO_HOST='127.0.0.1'; $env:NITRO_PORT='5173'
node .output/server/index.mjs
```

Customer: `http://127.0.0.1:5173/dashboard`; admin: `/admin`.
Restart a running production preview after rebuilding: its in-memory manifest
otherwise references replaced asset hashes, leaving server-rendered pages unable
to hydrate. A changed `VITE_API_BASE_URL` requires rebuilding the frontend.

## Coverage and routing policy

`material-evidence-2026-10-22-v2` records execution, applicability, evidence
sufficiency and material requirements separately. Missing EXIF/C2PA credentials
are optional provenance gaps, not manipulation. Zero-weight experiments are
advisory. Repairer-pattern thresholds are research benchmarks, not clearance
requirements. Applicable identity, image comparison, incident-context, damage and
history checks remain material. With no eligible historical comparison, the
comparison is not applicable; an empty isolated corpus proves no clean history.
One completed plate comparison can satisfy that check even when damage close-ups
contain no plate; this does not authenticate every photograph as one vehicle.

The production policy is `agent-production-<type>-2026-10-22-v4`. Original model
recommendation/band remain unchanged in saved decisions. The explanation separately
records effective routing and a deterministic material-evidence guard. Incomplete
approval is routed to request evidence; stronger model escalations are retained.
Nonconverged execution requires desk review. No customer case is automatically
approved/rejected. Incomplete assessments stay neutral in both UI and PDF.

There is **no additive numeric production risk score** or fraud probability.
The model selects routing using saved findings, cited evidence and implemented
rules. Experimental detector outputs and research baseline scores do not become
production fraud probabilities. Execution completion does not establish evidence
sufficiency or accuracy.

Renderer `fraudlens-pdf-2026-10-22-v5` adds the material-gap/effective-routing summary
and saved-data amount comparison. It states that the severity/amount bands are
configured research heuristics; no independent repair estimate/invoice is verified.
Earlier renderer artifacts and snapshots remain available unchanged. Preview and
download read the same saved bytes and never run models/checks.

## Historical claims: prepare only

The current audit/manifest is private under ignored outputs. No historical job
was queued. A fresh read-only audit is reproducible with:

```powershell
.\venv\Scripts\python.exe scripts/claims_batch.py --process-id API_PID --output outputs/history_NEW_AUDIT
```

The resulting `claims-plan.json` proposes new run IDs, validates file hashes,
estimates compatible-cache reuse and distinguishes legacy/no-run from genuine
failure and completed-but-insufficient assessments. Existing reviewer decisions
are recorded for preservation. Counts are point-in-time observations.

For a **future separately authorized** batch, `--enqueue-next --operator ...
--reason ...` resumes that manifest one job at a time. Reviewed cases require
`--include-reviewed`. It refuses an active task allowance, active jobs, changed or
missing evidence, a provider stop, insufficient minimum daily headroom, or a prior
failed/incomplete batch result. Checkpoints retain terminal status and sufficiency.
An already accepted run is not duplicated. There is no background batch loop.

Retrospective comparisons exclude the current case and use its submission cutoff;
new reports are labelled historical. Earlier findings, PDFs and human outcomes
are retained. Underwriting historical execution and live six-view validation are
deferred. Software fixtures do not establish live underwriting operation.

## Verified local result and limits

Ordinary UI case `case-e4f345a50f26` completed on run
`bbb9ed14d1c28c961b74093212aa8a6e` after one retained HTTP-503 failed run and an
explicit reviewer retry. Qualifying perception and two agent turns were fresh;
one `get_claimant_history` exchange actually occurred. Material registration,
scene/context and image-comparison gaps keep the assessment neutral. A fictional
reviewer requested evidence and the customer received that update. No original
decision was changed. This proves execution, not accuracy or complete coverage.

Four new generation attempts were used: fifteen cumulative. The task closes its
unused twenty-six attempts; no automated diagnostic/batch workload remains.
Normal operation remains bounded and enabled. At closure, on the recorded Pacific
quota day, local daily headroom is fifteen and selected-key reservation headroom
is nine. Re-read controls before a new case: dates/activity change these counts.
Google account quota was not measured.

The pre-submission audit found 825 cases, including 668 claims and 157 underwriting.
Eight hundred have no durable run, rather than a failed run; 25 cases have 36
failed runs. All 1,473 evidence references were available. The claims-only dry-run
estimates at least 1,625 calls (957 distinct compatible observation misses plus
668 minimum agent calls), at most 10,688 under the per-case ceilings. No historical
job was queued. Recheck evidence/cache compatibility before any future batch.

Acceptance took 42.765 seconds and the successful worker pipeline 164.601 seconds.
Peak worker RSS was about 986 MiB; local experimental classifier cold loading took
78.248 seconds. Observed API warmups ranged from 118 to 419 seconds on this 8 GiB
host. Model initialization and database round trips remain material bottlenecks;
timeouts were not increased to hide them. Underwriting live validation is deferred.
The final service restart took 663.875 seconds of API model warmup (peak about
1.56 GiB, available memory below 1 GiB). Wait for readiness before submitting;
this cold-start limitation remains unresolved.

[Actual PDFs, screenshots and audit](normal_operation/README.md) include the
verification limits. Native Chrome preview pixels were not verified headlessly;
saved/download bytes and standalone rendered pages passed. Original business
rows/reports were retained; login cleanup removed only expired sessions.

## Rollback

Pause new attempts first; let the current request/job reach a safe terminal state.
Preserve the private control/database backups and latest receipts. Revert this
task's focused code commit if required, but do not restore an older ledger over
new provider history or delete the operating migration. Older code cannot enforce
the migrated policy safely: keep provider consumers stopped until compatible
controls are restored or an explicit append-only rollback is implemented. Reports
and decisions are additive and do not require deleting historical records.
