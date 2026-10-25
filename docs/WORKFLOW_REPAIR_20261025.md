# FraudLens workflow repair — 25 October 2026

Started 25 October; final verification completed 26 October 2026. Local repair
only. No push, deployment, database-provider change, historical
reprocessing, new provider grant or change to approval/escalation routing.
Verification receipts are in the ignored backend `outputs/workflow_repair`.

## Reproduced causes

The original `Intake.tsx` saved a separate `formReady` boolean. Ordinary input
events and file selection updated it, but `FieldSuggestions.tsx` selected values
through component state without a native input/change event. In the actual
browser, both forms had all four/six accepted photo states, consent checked and
`form.checkValidity() === true`, yet Submit stayed disabled when the last required
description was selected from suggestions. The original script receipts and
screenshots are `baseline-readiness.json` and `baseline-{kind}.png`.

Silent browser/password-manager autofill exposed a related controlled-input
problem: reading the changed DOM value could trigger a React render that restored
the older component value. Fields now synchronize native autofill values before
the form snapshot is evaluated. Suggestions notify their parent after commit.

The original risk detail/PDF contract required every material requirement and a
converged assessment before showing any category. A paused provider therefore
produced only “Assessment incomplete,” even when actual local findings existed.
Meanwhile the queue derived Low/Medium/High directly from routing, so a fallback
desk-review route could appear Medium without the same evidence assessment.

## Implementation and policy

`intakeValidation.ts` reads active controls and supplies one final validator to
both button readiness and submit handling. It retains native constraints,
registration/mobile/coordinate/bank checks, consent and exact configured photo
slots. Every current blocker appears beside Submit and can focus its field/slot.
File presence, current accepted states and duplicate hashes determine photo
readiness. Existing revision tokens protect replacement/removal from old replies;
the bounded transport and validation queue retain retry recovery. Initial photo
admission remains policy `initial-photo-admission-2026-10-23-v4`, with the same
server-authoritative MIME/decoding/count/duplicate/relevance rules and cache
bindings. No Gemini call was added to admission.

The existing `assessment_presentation` contract is extended, rather than adding
a competing assessment. A terminal worker transaction saves it in the existing
job JSON together with the run result and immutable report snapshot. API detail,
queue, filters and PDF consume those saved values. Historical snapshots/artifacts
remain immutable; older run summaries are read safely, without bulk rewriting or
applying the new partial policy on read. Reports use renderer v13; v1–v12 readers
and existing artifact bytes remain available.

Display policy `partial-evidence-display-2026-10-25-v1` is deliberately separate
from production routing and the unvalidated two-axis shadow candidate:

| Saved evidence | Display outcome |
|---|---|
| Completed supported model/rules assessment, sufficient material coverage | Existing recorded category: LOW/MEDIUM/HIGH |
| Terminal, run-bound partial work with one completed eligible material concern | Provisional MEDIUM — partial assessment |
| Completed plate identity concern plus image/history concern | Provisional HIGH — partial assessment |
| Only missing/failed/inconclusive results, only garage concerns, only zero-weight experiments, or no usable concern supporting a band | UNASSESSED — insufficient evidence |
| Stale, unversioned, queued or genuinely failed local work | UNASSESSED; processing/recovery state remains separate |

Partial LOW clearance is not supported. An outage cannot become LOW or an
arbitrary MEDIUM. Eligible concerns must come from the saved positive-weight
check policy and completed executions. Internal/external image reuse and
baseline/severity history are one concern domain, regardless of repeated rows.
Garage billing concerns and experimental checks cannot establish claimant risk.
HIGH uses the explicit identity-plus-history rule, not repeated counts or a
shadow score. These are conservative review categories, not calibrated fraud
probabilities or proof of intent. Manual review stays required independently.

The contract records display/run/policy versions, actual check results,
supporting finding IDs and attribution, material coverage/gaps, explanation,
next action and processing completeness. Production model routing has no
numerical score. A previously supported baseline sum is labelled an unbounded
heuristic index, never a probability; partial results have no numerical gauge.

The existing worker executes available local/database checks after provider
failure and saves their results. The terminal status, display summary and report
snapshot are then committed together under the case and worker ownership locks.
Real PostgreSQL regressions caught an initial repair bug: calling the ownership
fence a second time after the terminal transition rejected the worker's own
write. The corrected implementation saves the summary under the lock already
held in that transaction. Genuine storage/evidence failures remain failed.
Durable ownership/idempotency, conservative recovery and explicit manual-review
authorization remain in place. Customer disclosure remains limited to owned
cases, processing state and the actual reviewer outcome.

## Verification

Initial broad backend regression: **223 passed**, 1846.82 seconds. This suite
covered photo admission/count/cache consistency, customer ownership and roles,
idempotency, durable recovery, partial local checks, human actions, immutable
PDFs, production explanation and shadow exclusion. No external model transport
was permitted. A Windows PowerShell stderr/deprecation wrapper reported a shell
error after pytest's completed success; the pytest result above is explicit.

Initial frontend typecheck and production build passed. The extended silent
autofill browser test then found the additional synchronization issue described
above. The final production build, including TypeScript checking and the explicit
saved supporting-check display, also passed (`build-reviewed.log`). Node 22.23.3
was used without upgrading dependencies.

Controlled browser tests use real React components with explicitly simulated API
responses. They are separate from native classifier and saved workflow evidence.
Required-field blockers, suggestions, input-event and silent autofill, consent,
photo replacement/removal, stale replies, pending/unavailable states, failed
submission recovery, duplicate-click protection, expired-session sign-in
recovery and mobile layout passed for both case types against the production UI.
The existing admission browser harness also passed unavailable/recheck, malformed
files, stale replies and final rejection/outage retention at both viewport sizes.

Final focused runs, which overlap the broad suite rather than adding unique
counts: **58 passed**, including two disposable real PostgreSQL transaction
tests; **76 passed** for final risk, historical rendering and PDF regressions.
The intake validator, saved review presentation and existing API-transport Node
checks passed. Controlled risk-component browser scenarios verified LOW/MEDIUM/
HIGH colours and text, provisional coverage, neutral UNASSESSED and no numerical
partial gauge at desktop and mobile widths.

Useful rerun commands from the backend directory:

```powershell
.\venv\Scripts\python.exe -m pytest test_partial_risk_policy.py test_report_pdf.py test_risk_presentation.py -q
$env:FRAUDLENS_TEST_POSTGRES='1'
.\venv\Scripts\python.exe -m pytest test_partial_review_postgres.py -q
Remove-Item Env:FRAUDLENS_TEST_POSTGRES
.\venv\Scripts\python.exe scripts/verify_intake_readiness.py
.\venv\Scripts\python.exe scripts/verify_photo_admission_browser.py
```

The PostgreSQL tests require the existing test database configuration and create
disposable schemas. The workflow rehearsal script uses the existing private
fictional presentation accounts, never committed credentials. Its `inspect`
and `persistence` phases operate only on its two receipts; `recover` uses the
reviewer UI to retry a failed new run. It does not retry historical cases.

## Actual saved workflows

Both Chrome customer and reviewer tabs used the real local API, PostgreSQL Panel
schema, native CLIP admission and durable worker; no routes were intercepted.

| Workflow | Saved case / final run | Processing | Saved display | Material evidence |
|---|---|---|---|---|
| Claims, four photos | `case-167fc4c5e190` / `8a4154bbbd6179ed3d219eb1a1faee08` | completed_partial | Provisional MEDIUM | 1 / 7 sufficient |
| Underwriting, six photos | `case-296ab7f9670a` / `4590ed78deca4326befdffce3ecae7f7` | completed_partial | Provisional MEDIUM | 2 / 5 sufficient |

The ten accepted prevalidation files were the exact bytes indexed by final
multipart submission. Four additional inspected damaged-car corpus photographs
passed native damage-close-up admission. One real unrelated animal photograph
was withheld in all ten configured slots. These are 14 positive requests and ten
negative requests, not 24 independently sourced photographs or an accuracy
calibration. Mounted-plate detail and powered-off dashboard images were admitted
for later assessment; readable registration, current identity and mileage were
not established. Existing printed-car-page false-positive limitations remain.

The provisional bands are supported by actual internal image-reuse findings
against the archived presentation corpus. Repeated matches form one domain.
Metadata concerns do not silently become claimant risk. These fictional records
are workflow tests, not fraud findings or claims of current insured loss.

The first Claims attempt exposed the terminal-write fence bug. Its accepted case
ID, evidence and failed run `5d2d4b2231a145e38de5ff0ed52b963b` remain intact. The
actual reviewer Retry analysis action created the final run above on the same
case. Underwriting recovered its interrupted attempt conservatively and finished
on attempt two. No duplicate case and no historical retry was introduced.

For both cases the queue API, detail and snapshot contained the same saved
contract. Actual UI preview/download, API inline/download bytes and selected
case/run agreed. Each reviewer requested specific evidence; the owning customer
saw the actual public explanation and request. Customer access to the private
reviewer PDF was denied. Approve/reject/authorization paths were covered by the
backend suite; these two real rehearsals used request-evidence actions.

The API, production frontend and dedicated worker were restarted using the
existing configuration. Saved run IDs, summaries, reviewer actions and PDF hashes
survived. Earlier pre-restart PDFs remained byte-identical. Final samples contain
13 Claims pages and 12 Underwriting pages; every page rendered, text stayed inside
page bounds, and contact sheets were visually inspected. The final first page
names only the findings cited by the saved display band, with their attribution.
Detailed/advisory check observations remain in the report body.

Cold model loading and cloud-database latency made this rehearsal slow. One
Underwriting PDF preview needed the existing bounded-request retry; the retry
opened the saved PDF without rerunning analysis. This is an operational latency
limitation, not proof of instant processing. Final health showed database,
validator and worker ready; Gemini remained manually paused/degraded. **No new
Gemini generation occurred.** Original provider ledgers stayed byte-identical,
all five prior Panel case rows stayed unchanged, and the original 800-case pilot
was not processed or modified.

Samples and sanitized receipts: [workflow_repair/README.md](workflow_repair/README.md).
Detailed local logs/screenshots remain in ignored `outputs/workflow_repair`.

## Exact task files

Backend:

- `FraudLens-2.0-Backend/src/api.py`
- `FraudLens-2.0-Backend/src/risk_presentation.py`
- `FraudLens-2.0-Backend/src/report_pdf.py`
- `FraudLens-2.0-Backend/src/report_visuals.py`
- `FraudLens-2.0-Backend/test_risk_presentation.py`
- `FraudLens-2.0-Backend/test_partial_risk_policy.py`
- `FraudLens-2.0-Backend/scripts/verify_intake_readiness.py`
- `FraudLens-2.0-Backend/scripts/verify_risk_summary_browser.py`
- `FraudLens-2.0-Backend/scripts/verify_workflow_repair.py`

Frontend:

- `FraudLens-2.0-Frontend/src/experience/Intake.tsx`
- `FraudLens-2.0-Frontend/src/experience/intakeValidation.ts`
- `FraudLens-2.0-Frontend/src/experience/FieldSuggestions.tsx`
- `FraudLens-2.0-Frontend/src/experience/RiskIndicator.tsx`
- `FraudLens-2.0-Frontend/src/experience/risk-indicator.css`
- `FraudLens-2.0-Frontend/src/experience/Admin.tsx`
- `FraudLens-2.0-Frontend/src/experience/shared.tsx`
- `FraudLens-2.0-Frontend/scripts/test-intake-validation.mjs`
- `FraudLens-2.0-Frontend/scripts/risk-summary-harness.tsx`

Documentation/artifacts:

- `docs/WORKFLOW_REPAIR_20261025.md`
- `docs/workflow_repair/README.md`
- `docs/workflow_repair/verification.json`
- `docs/workflow_repair/Claims-partial-review.pdf`
- `docs/workflow_repair/Underwriting-partial-review.pdf`

Existing unrelated edits, including overlapping API/Admin/shared edits and
previously staged handover documents, were preserved outside the task commit.

## Local startup

Use three terminals; do not start a second listener on an occupied port. The
presentation dataset is separate from the original pilot and its 800 legacy cases.
The launchers preserve original provider controls and private evidence paths.

```powershell
# Terminal 1, from the repository root
Set-Location .\FraudLens-2.0-Backend
.\scripts\start_review.ps1 -Dataset Panel -Service Api

# Terminal 2, from the repository root, once validator is ready
Set-Location .\FraudLens-2.0-Backend
.\scripts\start_review.ps1 -Dataset Panel -Service Worker

# Terminal 3, from the repository root
Set-Location .\FraudLens-2.0-Frontend
$env:NITRO_HOST='127.0.0.1'
$env:NITRO_PORT='5173'
& 'D:\tools\FraudLens-node22\node-v22.23.3-win-x64\node.exe' .output/server/index.mjs
```

To rebuild use `./scripts/node22.ps1 typecheck` and `./scripts/node22.ps1 build`
from the frontend directory, then restart its owned Node process. Use `-Dataset
Pilot` in **both** backend terminals only when intentionally selecting the original
pilot. Never mix worker/API schemas or evidence directories. The worker launcher
checks the actual API environment. Provider readiness remains degraded while the
existing manual pause is active; restarting does not authorize model generation.
