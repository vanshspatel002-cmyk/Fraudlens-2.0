# FraudLens analysis repair — 20 October 2026

Branch: `repair/analysis-pipeline-20261020`, based on `26d8c91`. No push,
deployment, purchase, credential rotation, database reset or original-report
overwrite is part of this work. Eight pre-existing **staged** documentation
changes remain separate from these commits.

## Investigated failure

Case `case-7c915870c09a`, run `7ff03eda7bbc41d09a44ec89d90aa28b` accepted three
photographs, claimed one durable worker attempt, saved 29 findings and a fallback
decision, and persisted its report. Its vision sources were zero fresh, zero
request-cache, zero perception-cache, and three unavailable observations. There
were no saved perception records for those photographs and no agent responses.

The retained worker log records `QuotaBudgetExhausted` during vision admission.
The original session ledger was stopped following two **earlier** HTTP 503
responses. The adapter rejected a new request locally; this case did not record
a new HTTP 503. After the vision failure the pipeline deliberately disabled
agent generation and saved a human-review fallback. C2PA's missing dependency
was a separate nonfatal check problem. Scene/damage/severity checks lacked the
perception they needed. The final failed state was truthful, but its old generic
failure message omitted the actionable stage and control distinction.

Other defects repaired: indefinitely reused failed vision cache entries; missing
structured-response validation; stripped Gemini function-call content/signatures;
unsafe provenance-error interpretations; missing EXIF/baseline treated as passed;
missing as-of bounds on historical comparisons; and optional tool/cache writes
remaining open during a subsequent provider turn.

## Actual persistence boundary

Before changes: **822 cases** (665 claims, 157 underwriting), 1,465 image references
with 1,368 distinct hashes, 33 failed durable runs belonging to 22 cases, 800
legacy cases without a durable run, 33 processing results, 58 snapshots, one PDF
artifact, and 15 cases with human actions. All 1,465 evidence references were
available and matched their hashes. All 130 stored perception rows passed the
current compatibility check; 1,238 distinct image hashes still need perception.

Consistent backups and detailed read-only audits are private at
`<repository>-preservation\pipeline-before-20261020T140930Z-85cf36`:
24 application tables, 5,624 filesystem files, separately verified application
evidence, original provider controls/configuration, and the exact initial index.
Backups and private evidence remain outside Git.

## Assessment policy

The production agent selects a **routing band**, not an additive numerical risk
score. Its saved explanation therefore has `computed_value=null`. It records
finding citations, observations, rule parameters, eligibility, coverage, provider
sources and guards/fallbacks. Model routing, operational completion, evidence
sufficiency and the human decision remain separate.

Only the existing research baseline sums `registered weight × finding confidence`
for each CONCERN. PASS and INCONCLUSIVE contribute zero. Repeated findings are
added individually; no new correlation discount, normalization or score cap was
invented. Duplicate matching excludes the entire current case and retrospective
runs exclude later cases and later-uploaded photographs. These bounds also apply
to history/similarity tools. A heuristic score is never a fraud probability.

| Check | Weight | Scope | Eligible production case types |
| --- | ---: | --- | --- |
| Internal duplicate | 1.0 | Image | Claims, underwriting |
| External corpus | 1.0 | Image | Claims, underwriting |
| EXIF metadata | 0.7 | Image | Claims, underwriting |
| Plate OCR | 0.3 | Image | Claims, underwriting |
| C2PA credentials | 0.1 | Image | Claims, underwriting |
| Scene consistency | 1.0 | Image | Claims, underwriting |
| Entity graph | 1.0 | Case | Claims, underwriting |
| Damage plausibility | 0.7 | Case | Claims |
| Billing threshold pattern | 1.0 | Case | Claims |
| Baseline linkage | 1.0 | Case | Claims |
| Severity progression | 1.0 | Case | Claims |
| AI generation, digital edit | 0.0 | Image | Experimental only |
| Baseline corruption | 0.0 | Case | Underwriting experimental only |
| View completeness | 0.0 | Case | Not in either production check list |

Baseline thresholds are `<0.3` clear, `<0.6` request evidence, `<1.0` desk review,
otherwise investigation. Routing uses the unrounded sequential sum; the saved
display score is rounded to four decimals. The new explanation records both.
There is no automatic rejection band. Production policy versions and detector
weights remain unchanged; check implementation revision is recorded separately.

Default duplicate rules require cosine ≥0.90 and either perceptual distance ≤8
or cosine ≥0.95; cosine ≥0.88 below the concern rule is inconclusive. The saved
per-finding parameters include actual overrides. Metadata uses a 100 km location
threshold and a 48-hour time qualification; OCR needs confidence ≥0.5 for its
comparison. The billing benchmark is INR 45,000–50,000, with more than 40% of at
least five garage claims in that band. It is research context, not a verified
current legal requirement. Damage ranges and 1.5 ceiling tolerance, 30-day
baseline linkage, 90-day same-panel progression, and scene/weather thresholds
are frozen in each assessment explanation rather than re-derived by the PDF.

## Interface and reports

Both case types use one vertical detail view: heading/status, application facts,
photographs, Desk Review, human actions, timeline. Evidence Battery, finding JSON
cards and long concatenated desk narratives are removed. Desk Review contains
three attributed factual sentences followed immediately by PDF controls, then
compact version information. Reviewer-only diagnostics are collapsed; a viewer
cannot use them to retry analysis. Old/unknown human review bases are labeled.

Current reader PDFs use submitted facts, labeled photos, grouped findings, the saved
calculation/routing explanation, missing inputs, next action, and the human
decision applicable to that version. Technical identifiers belong in the optional
appendix. Version three keeps section headings with their content; version-two
rendering and all saved PDF bytes remain available. Repeated preparation
reuses a saved run/review/evidence/template basis; unrelated corpus changes do not
create duplicate versions. A new run, human revision or template creates a new
snapshot. Preview and download fetch the same saved artifact.

## Provider controls and historical scope

The one authorized recovery probe succeeded without retries or key rotation:
one uncached request, requested alias `gemini-3.5-flash`, serving version
`gemini-3.6-flash`. The original two failure events and stop reason remain in the
ledger. Recovery adds audited allowances under the original lifetime cap of 15;
it does not grant unlimited usage or reset attempts. Normal quota-day rollover
also retains earlier quota history; malformed ledgers fail closed.

On resumption on 21 October, the saved claims validation request had returned
another actual HTTP 503. Its recovery is now **failed**, with four lifetime
requests recorded and **zero currently authorized additional requests**. Keep
that stop. A reset of conversational limits or the provider quota day does not
reopen this application circuit. Successful live claims AND underwriting
validation and historical processing therefore remain blocked. Explicit
manual-review/PDF verification is recorded separately and cannot unlock the
historical gate.

Google documents the alias routing in its
[model guide](https://ai.google.dev/gemini-api/docs/models/gemini-3.5-flash).
Function-turn preservation follows the official
[thought-signature protocol](https://ai.google.dev/gemini-api/docs/generate-content/thought-signatures);
opaque signatures are carried back to the provider and never rendered as
reasoning. C2PA uses the pinned official
[Python SDK](https://github.com/contentauth/c2pa-python), with remote manifest and
OCSP fetches disabled for this local verifier.

The qualified full-corpus dry run requires **at least 2,060 requests**: 822 agent
requests plus 1,238 compatible-vision misses, before tool/parse retries. It refused
all-case enqueueing under the available allowance. Its private plan/checkpoint:
`FraudLens-2.0-Backend/outputs/analysis_repair_20261020/batch-all822-dryrun`.
This is a planning result, not completed historical processing.

## Startup and resumable commands

Use the preserved configuration and provider controls. Build before model warmup
on this 8 GB computer. The normal application uses the original PostgreSQL pilot:

```powershell
Set-Location <repository>\FraudLens-2.0-Backend
.\scripts\start_pilot.ps1 -Database postgresql -Schema fraudlens_pilot -Port 8001 -NoWorker
# In another terminal, after API startup:
.\scripts\start_pilot.ps1 -Database postgresql -Schema fraudlens_pilot -WorkerOnly
```

The isolated qualification schema is `fraudlens_repair_20261020_a`, with separate
evidence under `outputs/analysis_repair_20261020/pg-real-a`; use that schema and
`-RuntimeDirectory '<absolute private runtime directory>'` on **both** processes
when deliberately reopening it. The private rehearsal configuration contains
locally generated test credentials; it is not a default application account.

```powershell
Set-Location <repository>\FraudLens-2.0-Frontend
$env:FRAUDLENS_NODE22_HOME = 'D:\tools\FraudLens-node22\node-v22.23.3-win-x64'
$env:VITE_API_BASE_URL = 'http://127.0.0.1:8001'
.\scripts\node22.ps1 -Task typecheck
.\scripts\node22.ps1 -Task build
$env:HOST = '127.0.0.1'
$env:PORT = '5173'
& (Join-Path $env:FRAUDLENS_NODE22_HOME 'node.exe') .output/server/index.mjs
```

Customer: `http://127.0.0.1:5173/dashboard`; reviewer:
`http://127.0.0.1:5173/admin`; backend: `http://127.0.0.1:8001/docs`.
Do not start a second listener or kill unrelated processes. Stop only your own
writers before switching databases. The handover from the earlier presentation
work still describes secure account provisioning and the explicit SQLite rollback.

At final handover on 21 October, the normal `fraudlens_pilot` API and frontend
were restored to those ports; health/readiness and both dashboard routes returned
HTTP 200. Admission-model warmup completed, and the dedicated worker finished
OCR warmup and held PostgreSQL leadership with no active jobs. The pilot still
contained 822 cases and 1,465 image references. Its original provider controls
were unchanged. Fictional qualification cases remain in the separate repair
schema and are not accounts/cases in the ordinary application.

From the backend, read-only planning uses a new output directory:

```powershell
.\venv\Scripts\python.exe -X utf8 scripts/audit_analysis_history.py --db postgresql --schema fraudlens_pilot --output '<NEW private audit directory>'
.\venv\Scripts\python.exe -X utf8 scripts/reprocess_history.py --audit '<qualified cases.json>' --batch-id repair-20261020 --scope all --output '<NEW private batch directory>'
```

Apply requires successful fresh claims AND underwriting validation evidence,
the existing audited recovery ID, matching evidence hashes, and sufficient
remaining original budget. Use `--case-id` for each explicitly selected case,
`--apply --validation '<live-validation.json>' --db postgresql --schema fraudlens_pilot`.
The same output with `--resume --apply` continues its checkpoint; `--pause` writes
its own pause marker. It enqueues at most one case at once and never rewrites
human actions, original reports or findings. No quota expansion is implicit.

## Verification and rollback

See [ANALYSIS_REPAIR_VERIFICATION.md](ANALYSIS_REPAIR_VERIFICATION.md) for actual
live/fixture boundaries, outcomes, artifacts and remaining work. A manual fallback
and passing software tests do not establish successful live AI assessment or
perfect fraud-detection accuracy.

The resumed real PostgreSQL/Chrome rehearsal passed the partial-report and
explicit manual-review path for both types: claims `case-c69f94bd810d` approved,
underwriting `case-5beba174962a` rejected, with both outcomes received by the
customer tab. Both jobs remain truthfully failed, with nonconverged fallback
routing and no numeric production score. A separate targeted browser check
verified current v3 PDF preview/download and role persistence after the report
layout correction; it did not submit new cases or decisions. Current reports
have four claims pages and five underwriting pages, all visually inspected.

This was a **resumed** rehearsal. Cold local model admission exceeded the
underwriting browser wait; the exact saved server receipt was recovered without
resubmission. Start normally with admission-model warmup before presenting.
No provider controls were reset. One mistaken legacy-test invocation made one
live request through a temporary test ledger; its private audit, the permanent
test opt-in fix and all verification boundaries are disclosed in the verification
record. That request is not successful workflow validation.

Focused local implementation commits: `2f8f9d1` (pipeline, temporal checks,
explanations and controls) and `bcaf483` (case review, versioned PDFs and browser
verification). The original eight staged documentation changes remain preserved.

Main implementation paths:

- Backend `src/{llm,perception,session_budget,quota_budget,analysis_diagnostics}.py`:
  transport, compatible observations and truthful provider/control failures.
- Backend `src/{assessment_explanation,api,orchestrator,ingest}.py`,
  `src/agent/{engine,tools}.py` and affected `src/checks/` modules: frozen routing
  explanations, check states, historical bounds and transaction release.
- Backend `src/report_pdf.py`; frontend
  `src/experience/{Admin,CaseReview,HistoricalReport,ReportPanel}.tsx`,
  `reviewPresentation.ts`, `case-review.css`, `report-panel.css` and `shared.tsx`:
  readable case review and immutable, versioned private reports.
- Backend `scripts/{audit_analysis_history,recover_provider,reprocess_history,prepare_analysis_rehearsal,verify_live_analysis}.py`,
  `start_pilot.ps1`, `verify_offline_suite.py`, and frontend
  `scripts/{verify_admin_review,verify_analysis_browser}.py`: auditable planning,
  bounded recovery, safe startup and distinct fixture/live/manual verification.

To roll back code, stop your own writers, keep a fresh logical/evidence backup,
and revert only these focused repair commits. No schema change is required by
this repair. Retain newly added runs, reports and audit history; never overwrite
the database with the earlier backup. Restore a backup only into a new namespace
for recovery. Preserve the original control ledgers and unrelated staged edits.

## Visual risk and report update — 21 October 2026

Newly prepared reports use `fraudlens-pdf-2026-10-21-v4`. Renderers v1, v2 and
v3 remain available; existing snapshot payloads and PDF bytes are retained.
The template version remains part of the snapshot basis, so preparing the new
current report creates a separate version. Preview and download address the
same saved artifact and do not rerun checks, models or human decisions.

`src/risk_presentation.py::assessment_presentation` is the common display
contract. It derives presentation only from the saved explanation, processing
state, run association and policy version. The API includes it in the reviewer
report, and snapshots freeze it for the PDF. The frontend does not score cases.
The admin registration header and PDF front page use matching categorical
Low/Medium/High segments and text labels. Numeric scores appear only when the
saved baseline aggregation explicitly validates a finite score. Production
model routing remains category-only; the bar has no equal numerical ranges.

Failed, queued, running, interrupted, materially incomplete, missing, unsupported
or stale assessments stay neutral with no marker or current score. A human
approval/rejection cannot supply automated risk. A saved earlier run is labeled
historical; a run mismatch cannot silently inherit its classification.
Required check coverage is displayed separately from risk and excludes optional
zero-weight experiments from the required-completion count.

The v4 report groups saved check observations into identity, history, provenance,
context and economic panels. It includes OCR comparisons, metadata availability,
actual identifier links, dated baseline/severity tables and the recorded garage
benchmark. Comparison thumbnails are frozen only for database-owned internal
image references under reviewer-only report access. External filenames are never
opened. Missing crops, boxes, masks, maps or compatible scales receive honest
fallbacks. Experimental checks prominently show exclusion/zero contribution.
No scoring weights, thresholds, model outputs or processing rules were changed.

Controlled artifacts, before/after laptop/mobile screenshots, check-graphic
screenshots, exact changed-file purposes and verification records are in
[docs/visual_review/README.md](docs/visual_review/README.md). These are authored
software/layout fixtures, not successful live analysis or accuracy evidence.
The provider stop and historical processing gate remain in force. No Gemini
quota was used; browser APIs were fully intercepted and backend tests used
temporary databases. No existing application case or report was rewritten.

Verification includes focused display/PDF tests, existing assessment/customer/
reviewer workflow tests, v1–v3 artifact retention, frontend typecheck/production
build, browser Low/Medium/High/incomplete/stale/historical/unsupported states,
1440 px and 390 px layouts, and identical preview/download bytes. Every sample
PDF page was extracted, rasterized and checked for page bounds and image aspect
ratio; all-page contact sheets and representative full-size pages were reviewed.

Restart the API and frontend using the established local commands to load this
source. No migration, deployment, provider recovery or historical reprocessing
is required or authorized by this visual update. The earlier unrelated staged
documentation and local connectivity/loading edits remain preserved separately.

## Gemini diagnosis and guard repair — 21 October 2026

See [GEMINI_DIAGNOSTICS.md](GEMINI_DIAGNOSTICS.md) for the current code/control
audit, safe configuration evidence, offline repairs, request plan and repeatable
commands. The original ledger still has four requests and a failed recovery;
its existing one-recovery policy forbids another probe. Numerical headroom is
11 but currently authorized additional calls are zero. No live request was made
in this task, so fresh claims and underwriting qualification remain unverified.

New diagnostics retain model, safe provider identifiers/finish reasons, attempt
history and case/run context without raw provider error bodies. Generations must
finish with STOP; blocked, empty, truncated or invalid structured replies are
unusable. Image bytes/MIME remain traceable to the decoded input. Quota writers
fail closed on lock contention and enforce shared/selected-key limits. Original
provider controls, budgets and events were not reset or expanded.

Ordinary pytest blocks external transports before collection and isolates
inherited provider controls. Legacy perception callable tests now have the same
explicit live guard as LLM tests. Future rehearsal preparation requires a fresh
structured image probe, current bounded recovery and explicit photographs; an
earlier generic-text success or failed recovery cannot authorize a schema.
These are offline software/control repairs, not successful live AI analysis.

The final provider/legacy guard run passed 146 tests with 10 live-dependent
skips; the overlapping durable/report/explanation regression run passed 218.
The idle API and worker were reloaded with the same pilot settings. API health
and readiness returned 200, worker OCR warmed, one pilot leadership lock was
held, and no queued/running jobs remained. Both original provider controls
remained byte-identical after reload. The frontend was not changed by this task.

## Operator recovery follow-up - 21 October 2026

This section supersedes the preceding four-attempt/permanent-recovery-block
status. See [GEMINI_DIAGNOSTICS.md](GEMINI_DIAGNOSTICS.md) and
[operator-recovery-audit.json](docs/gemini_diagnostics/operator-recovery-audit.json).
The earlier configuration audit is retained unchanged.

The permanent `prior_recovery_already_recorded` gate was application logic.
Policy `operator-transient-recovery-2026-10-21-v2` permits a named, audited
operator to request one half-open probe after a failed transient recovery and a
30-minute cooldown. Original events/recoveries, cap, stop and daily controls
remain retained. Shared locking permits one probe; failure closes its allowance.
Configuration/access/quota/manual stops remain ineligible. Diagnostics now require
complete effective pilot settings (including PostgreSQL schema and original
ledgers), preferably read from the running API with `--process-id`.

Exactly one generation reached Google: HTTP 400 `INVALID_ARGUMENT`, no
observations, no schema-validation result and no finish reason. One separately
budgeted configured-model metadata GET returned 200 and advertised generation
support; metadata does not establish successful image generation. Attempts are
now 6/15, headroom 9, and additional authorized generation is zero. Original four
events and the original failed recovery remain unchanged.

Offline SDK inspection reproduced a concrete legacy `responseSchema` defect:
Pydantic extra-field exclusion emitted unsupported `additional_properties`. The
adapter now uses `response_json_schema` and explicitly validates returned JSON.
This likely explains the 400, but the first response did not retain field-level
provider details; the exact attribution and corrected wire format are NOT live
verified. Safe ErrorInfo/field hints are now retained for future diagnostics.
No second generation was made. Claims and underwriting remain unverified live.

Focused offline verification: 184 passed, 10 live-dependent tests skipped.
Controlled transports cover cooldown, concurrency, cap/history preservation,
configuration alignment, full observation schema, corrected wire format, parsing
and separately counted metadata. Ordinary tests retain the pre-collection network
guard and disposable controls. No frontend change was part of this repair.

The idle dedicated worker was paused for the authorized operations. API/worker
were then restarted with matching original pilot settings and stopped controls.
API health/readiness returned 200, OCR warmed, one leadership lock was held and
zero queued/running jobs remained. No application case, report or decision was
created or reprocessed. No credential, cap or original audit history was reset;
no push or deployment occurred. A future corrected probe needs new authorization
and a correction-specific audited gate because the latest failure is HTTP 400.
Another qualifying probe plus both fresh case types needs at least 10 requests,
which exceeds the retained 9 slots before any agent tool follow-ups.

## Corrected schema live probe - 22 October 2026

Current status supersedes the preceding unverified-perception status:
**corrected live perception verified; full pipeline NOT verified**.
See [GEMINI_DIAGNOSTICS.md](GEMINI_DIAGNOSTICS.md) and
[corrected-schema-audit.json](docs/gemini_diagnostics/corrected-schema-audit.json).
One generation returned HTTP 200 with ten schema-valid observations; zero metadata
calls/retries. Attempts are now 7/15, remaining slots 8, additional generation
permission zero. Original six events, both prior recoveries, stop and quota history
remain intact. A one-use correction-specific grant links attempt 5's HTTP 400 to
commit 8a534bf and json_schema_v1; schema/prompt/image/model/profile are bound.
Ordinary background generation remains stopped; no validation grant was issued.

The live diagnostic saved actual observations but its new artifact writer failed
on a datetime. That local serialization bug was reproduced and fixed offline.
The original failed diagnostic receipt remains unchanged; a separate reconciliation
and observation artifact use the real JSON, original image/contract and ledger.
Exact serving version, response ID, provider latency and literal finish metadata
were not retained and remain null. STOP validation passed inside the adapter.
The photograph supports extensive glass damage, no plate and no clear directional
shadow; rear orientation and the small ground strip remain uncertain. This is
single-image integration evidence, not accuracy or fraud/pipeline qualification.

Full offline regressions after persistence repair: 208 passed, 10 live-dependent
skips. Final gate follow-up: 138 passed; totals overlap. Tests include actual SDK
payloads, exact complete schema, single-use correction scope, concurrency, safe
parsing diagnostics, datetime persistence and forced write failures. No test
contacted Gemini. Services use the original pilot configuration and stopped
controls; final restoration evidence is in the current audit.

Prepared only: fresh claims/underwriting require at least 9 calls, 11 with a tool
exchange in each, at most 30 under the documented schema/agent caps and disabled
transport retries. Eight slots cannot cover both. A future explicitly authorized,
append-only development policy could set cumulative ceiling 37 (7 retained + 30
workflow calls), restricted validation scope and expiry. This is a proposal only;
no cap, key, Google limit or billing change was made. No case, report, decision,
historical reprocessing, push or deployment occurred.

## Isolated live workflows and scoped budget - 22 October 2026

**Claims: Live workflow verified (assessment incomplete). Underwriting: Blocked
by missing legitimate six-view evidence.** See [GEMINI_DIAGNOSTICS.md](GEMINI_DIAGNOSTICS.md)
and [live-workflow-audit.json](docs/gemini_diagnostics/live-workflow-audit.json).

The user's new explicit authorization superseded the prior 15-cap proposal
blocker. A revision to 37 cumulative / 30 new requests was appended without
changing the seven prior events, recoveries, daily controls or original stop.
The expiring grant was restricted to schema `fraudlens_validation_20261022` and
actual API-accepted job `64dcf803f54c43dd8f13a7c039ed7924`, case
`case-03dd3c967b5b`. Normal workers/unbound jobs cannot spend it. Current task
used four new generations (one fresh full-schema perception, three real agent
turns). Tools requested/executed: get_claimant_history and requery_perception;
the latter reads saved observations without another provider call. All four
requests returned HTTP 200 / STOP. Metadata/retries: zero. Actual requested and
serving models, response IDs, token counts, timing/source and run scope were
checkpointed before downstream persistence. The probe was not repeated.

Claims job completed on attempt 1 with one perception, 13 findings, a converged
decision, processing result and run-specific snapshot. The saved model decision
is clear/approve with null score; no human approval was written. Incomplete
required evidence/check coverage keeps the shared UI/PDF risk indicator neutral
and explicitly requires review. Three checks completed, seven were inconclusive
(including two zero-weight experiments), scene consistency was not run and two
baseline/history checks were not applicable. Valid execution is not accuracy or
proof of a fully cleared claim. The crop supports panel damage, not precise
body type, capture time, registration or incident cause.

No legitimate same-vehicle six-view set including odometer/plate could be
established in the authorized samples. No unrelated/AI images or fake labels
were substituted, so no underwriting case or PDF was created. Its exact blocker
is evidence quality/availability, not a fresh Gemini outage.

The nine-page claims PDF, actual desktop/mobile/customer screenshots and front
page are in [live_validation](docs/gemini_diagnostics/live_validation/README.md).
All PDF pages were extracted/rendered/visually inspected. Blob/API/browser
preview/download bytes agree; ownership, private images, roles, two-tab sessions
and saved risk display passed. Headless Chrome's native viewer frame loaded,
but native document pixels were not confirmed; the identical PDF was fully
rendered independently. This limitation is retained in the audit.

Offline checks: 226 passed / 10 live skips for provider/engine preflight; 108
passed for durable/customer/PDF/risk; 18 passed for final scoped controls. Counts
overlap. Tests cannot contact external Gemini by default. No frontend application
source, scoring weights, thresholds or renderer version were changed.

Grant closed after claims completion and before PDF/UI checks. Total attempts
11, unused 26 revoked, authorized generation now zero. Original pilot services,
schema/storage and ordinary 15 process setting were restored with normal
provider generation still stopped. Case/report/decision counts in the original
pilot are checked against the preflight. Isolated live data and original audit
prefixes remain retained. No billing, purchase, key rotation, provider-limit
bypass, historical reprocessing, push or deployment occurred. Future underwriting
requires the real six-view evidence and new explicit scoped authorization.

Later offline dependency/parameter/candidate-policy work is documented in
[ASSESSMENT_AUDIT_HANDOVER.md](docs/ASSESSMENT_AUDIT_HANDOVER.md). It preserves this
live history, introduces no generation or historical batch, and keeps the new
two-axis calculation shadow-only. Underwriting live validation remains deferred.

## 22 October 2026 — normal local operation supersedes the stopped handover

Baseline `835ae28103060c0a087da63eac4a979d22bfd47f` on
`repair/analysis-pipeline-20261020`; no later commit was discarded. The latest
user explicitly authorized normal local operation, an audited controls migration,
and at most thirty new attempts. The historical eleven attempts and all original
recovery/grant/quota records remain intact. The ordinary pilot no longer depends
on a fresh diagnostic grant or its old fifteen-request lifetime ceiling.

**Claims: Live workflow verified. Underwriting: live validation deferred; shared
software fixture verification passed. Historical reprocessing: prepared only.**

One fictional ordinary customer UI claim, `case-e4f345a50f26`, was accepted into
`fraudlens_pilot` with ownership and a durable job. Its first run
`5964e717c7d04b50b3078dbff25730fd` retained an actual 503 failure. A reviewer UI
retry completed run `bbb9ed14d1c28c961b74093212aa8a6e` with one fresh full-schema
perception, two fresh agent turns and one real `get_claimant_history` exchange.
The qualifying stages were not cached. Model routing was escalation, triggered
by expected reuse of the authorized public sample in the existing pilot corpus.
This does not prove fraud or improved accuracy. Material plate, scene/context and
external-image gaps keep UI/PDF neutral and incomplete despite completed execution.
The new fictional reviewer requested evidence; the customer saw `awaiting_evidence`.
No original human decision was touched.

Operating policy `local-operation-2026-10-22-v1` persists in the original ledger:
one active case, daily thirty attempts, per-case sixteen across runs, eight agent
turns, two bounded application attempts, transport retries disabled, two-second
pacing. A manual pause persists; two transient failures open a circuit with one
serialized recovery request after thirty minutes. Authentication/model/quota
errors block unchanged requests. Original stricter quota controls still apply.
Session admission and quota reservation share atomic lock ordering. Tests have
no external model access by default. Local limits do not establish Google quota.

Four new attempts were used (one 503, three successful generation responses):
fifteen cumulative; twenty-six unused task attempts close at handover. Normal
operation remains enabled independently under daily/per-case controls; no
diagnostic or historical workload is scheduled. At closure, local daily headroom
was fifteen, selected-key reservation headroom nine, actual Google quota unknown.
API and worker were restarted from the same original pilot configuration after
the final receipt/accounting fixes. No generic probe/metadata request was repeated.

Coverage policy `material-evidence-2026-10-22-v2` separates execution, applicability
and sufficiency. EXIF/C2PA, zero-weight experiments and research repairer-pattern
observations are advisory. Absent eligible history is not applicable, never a
verified clean history. Material requirements remain enforced. Original model
recommendation, effective deterministic guard and human decision are separate.
Production routing has no additive numeric score or fraud probability.

Renderer `fraudlens-pdf-2026-10-22-v5` adds concise material gaps/effective action,
real evidence comparisons and labelled INR heuristic bars. It explicitly says no
independent repair estimate/invoice was verified. Original artifacts remain
unchanged. Current claims snapshot:
`bba138dd00efbc74e298c7ed1ea803e97c1862b867bd9d455ee44bafa82537c1`.
Its PDF and representative underwriting fixture are nine pages each; every page
was rendered and inspected. Browser preview/download bytes matched. Headless
Chrome's native viewer did not paint pages, so manual/native preview pixels were
not verified. Controlled UI fixtures covered category boundaries, unknown/missing
scores, failures, stale/history and desktop/mobile behavior without model calls.

Provider regressions: 159 passed, 7 live-only skipped. Workflow/customer/report/
risk regressions: 130 passed. Runs overlap. Frontend typecheck/build passed.
Acceptance 42.765 s, successful worker pipeline 164.601 s, peak worker RSS about
986 MiB; local experimental classifier cold loading took 78.248 s. CPU model
warmup and database round trips remain bottlenecks on this 8 GiB machine. No
timeout increase conceals them. Restart the local production Node preview after
a build to avoid stale manifest/asset hashes and failed hydration.
Final restart: API warmup 663.875 s, peak about 1.56 GiB; dependency import and
CLIP initialization were severely constrained by available memory. The service
eventually became ready. This remaining cold-start limitation is explicitly
reported; no timeout or model/quota setting was relaxed.

Private consistent backups cover all 26 original tables and both provider
controls. Every original business row, report, decision, finding and account was
unchanged. Existing login cleanup removed five expired admin and one expired
customer session; none of the accounts were removed. The original audit had
825 cases, 800 legacy/no-durable-run and 25 genuinely failed/partial cases.
No-run records display as not recorded. The claims-only dry-run proposes new run
IDs, validates evidence/cache compatibility, checkpoints state and requires an
explicit future operator action. Its minimum estimate is 1,625 calls and its
per-case-cap bound 10,688; zero historical jobs were queued. Self/temporal
exclusion and retrospective labels apply, preserving earlier decisions/reports.

Exact files/purposes: [implementation record](docs/NORMAL_OPERATION_WORKLOG.md).
Startup, persisted pause/resume, conservative settings, safe read-only historical
command and rollback: [operating guide](docs/NORMAL_OPERATION.md).
Actual IDs, receipts/accounting, software verification and evidence limitations:
[diagnostics](GEMINI_DIAGNOSTICS.md), [sanitized audit](docs/normal_operation/audit.json).
Downloadable samples/screenshots: [artifacts](docs/normal_operation/README.md).
Rollback begins with a persisted pause; never restore an older ledger over new
provider history. No push, deployment, billing, key rotation or bulk reprocessing.
