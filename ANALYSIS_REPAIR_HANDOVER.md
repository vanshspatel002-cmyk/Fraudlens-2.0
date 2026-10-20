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
`D:\projects\FraudLens-2.0-preservation\pipeline-before-20261020T140930Z-85cf36`:
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
Set-Location D:\projects\FraudLens-2.0\FraudLens-2.0-Backend
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
Set-Location D:\projects\FraudLens-2.0\FraudLens-2.0-Frontend
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
