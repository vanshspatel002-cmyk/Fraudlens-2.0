# Final presentation verification — 23 October 2026

Verified implementation commit: `9d240d0cc3645ccea701f5c47d786f32af54e947`. This documentation follow-up
records that tested release; `git log -1 --format=%H` identifies the final local
documentation commit. No push or deployment.

**Partial release qualification: Gemini availability blocks fresh live analysis.**
Real photo admission, durable submission, saved local checks/PDFs and reviewer/
customer evidence requests were exercised for both case types. Neither new run
completed live AI processing. Fixtures and fallback are not counted as success.

Baseline `0024843f5bb9ab370570afffa1dbf336ed301b41`, branch
`repair/analysis-pipeline-20261020`. No later commit or applicable AGENTS.md was
found. Current normal-operation, photo-admission, assessment/dependency/parameter/
check matrices, Gemini diagnostics and audits were inspected before editing.
Existing staged documentation and unrelated frontend/API changes were preserved.
Verification used the actual working tree, including those transport/evidence
changes. No dependency/model upgrade, deployment or historical reprocessing.

## Acceptance checklist

| Acceptance | Actual result |
|---|---|
| Consistent business/evidence/control backups before mutations | Done; private copies retained |
| Real four-photo claims and six-photo same-car underwriting admission | Passed server-side local model and authenticated prevalidation |
| Required fields, coordinates and timezone-aware incident time | Passed actual UI/API/database/report round-trip assertions |
| Durable job acceptance and customer ownership | Passed real UI, PostgreSQL and dedicated worker |
| Fresh perception and real agent completion | **Blocked** by provider HTTP 503; not replaced by cached/mocked success |
| Saved checks, explanation and neutral incomplete risk | Verified both |
| Admin evidence originals, PDF preview/download, immutable earlier PDFs | Verified both |
| Reviewer request and public customer update | Verified both new fictional cases |
| Cross-customer case/evidence/report protection | Verified both; authorized own evidence loads |
| Independent customer/admin logout and refresh | Verified two tabs in the same ordinary persistent Chrome context |
| Laptop and 390 px admin layout | Verified without horizontal overflow |
| Offline and disposable PostgreSQL regressions | Passed focused suites below |
| Task allowance closed; final pilot service state | See final operational receipt |
| Historical batch | Frozen; zero enqueues; existing dry-run commands retained |

## The two actual cases

| Recorded item | Claims | Underwriting |
|---|---|---|
| Case ID | `case-95a28aea367c` | `case-ac757ae6f8b1` |
| Run ID | `e98e025b4b4f4c34aebb6b6a18e54fb9` | `f5f91eb39c9b47f68eb282d5a38647f4` |
| Schema | `fraudlens_validation_panel_20261022` | Same isolated schema |
| Real photos admitted | 4/4 distinct photographs | 6/6 distinct same-car photographs |
| Durable acceptance | 11.281 s | 19.453 s |
| Terminal job / stage | `failed` / `needs_review` | `failed` / `needs_review` |
| New HTTP generation attempts | 2, HTTP 503 `UNAVAILABLE` | 0, provider paused locally |
| Successful fresh perception / agent turns / tool exchanges | 0 / 0 / 0 | 0 / 0 / 0 |
| Actual local OCR | 4 fresh | 4 fresh, 2 compatible cached |
| Production score / risk category | null / null, incomplete | null / null, incomplete |
| Fictional reviewer action | Request more evidence | Request more evidence |
| Customer public outcome | `awaiting_evidence`, message visible | Same |

Submission and worker acquisition used actual routes and durable jobs, with no
interception or direct successful-outcome insertion. The source assets remained
outside the pilot reference corpus. Matching photographs across these two real
applications legitimately produce duplicate/entity links; they do not prove fraud.
The terminal failed run and later human evidence request are separate records.

### Photo relevance is not complete evidence

[Licensed original photos and mappings](presentation_assets/README.md): 2005
Chevrolet Classic series, Milkmandan~commonswiki, CC BY-SA 3.0. The archive series,
visual details and setting support same-car use, not independently authenticated
identity/date/ownership. The odometer is off; plates do not read as the fictional
Indian registration. The claims declaration describes an unconfirmed electrical/
window concern. These photos prove neither insured loss nor repair cost.

Final real CPU CLIP smoke: **64/64 expected outcomes**, zero generation. It covers
all ten presentation slot uses, 12 corpus exteriors (six held out from this prompt
development), eight part-image positives, unrelated category/slot negatives and
paper/screen/blur controls. This small authored smoke is not independent accuracy
calibration. No dedicated real heavy-vehicle negative was available; a cropped
screenshot can defeat semantic classification.

Admission policy v3 retains floor **0.175**, margin **0.020**, exact 4/6 counts,
actor/slot/hash bindings, duplicate and stale-response protections. Slot-aware
descriptions improve relevance without lowering a global threshold. Plate/ODO
text extraction is deferred: `quality_readable=null`, `identity_verified=false`,
`slot_label_verified=false`, with capture guidance. A conservative detail variance
floor of 5 withholds severe blur. Warming/outage/busy is retryable 503, not permanent
rejection or silent acceptance.

### Inputs and real checks

Actual form/report round-trip assertions passed for all captured business fields:
contact, address, vehicle, policy, application type/condition, amount, settlement,
manual coordinates `22.3,73.2`, and incident
`2026-10-22T15:30:00+05:30`. Coordinates/time remain fictional declarations, not
verified GPS/capture evidence. Coordinate pairs require finite bounded values;
provided naive times are rejected. The browser consent control is not an
independent identity/policy verification record.

| Check | Saved result and limitation |
|---|---|
| Internal comparison | Claims empty eligible corpus is not applicable, not clean real-world history. UW has actual shared-photo matches; self-match exclusion retained. |
| External corpus | Actual configured 400-image local reference comparison, not Internet reverse search. |
| Plate OCR | EasyOCR ran; unreadable extraction remains inconclusive, not image irrelevance. UW reused two compatible local OCR results explicitly. |
| EXIF | Actual source editor tag is an optional provenance concern, not proof of manipulation. Missing EXIF is not fraud. |
| C2PA | Missing credentials inconclusive and optional. Native signed-credential verification is not newly qualified. |
| Scene/time/weather | Claims prerequisites persist, but fresh scene observations are missing. No successful current weather comparison is claimed; bounded/error handling is fixture-tested. |
| Damage/amount | Missing fresh perception prevents supported comparison. INR 2,000 is declared, not an independently verified repair estimate/invoice. |
| Entity graph | UW has a real shared registration link; conservatively inconclusive, no authoritative registry or proof of intent. |
| Baseline/severity | No eligible earlier history should be not applicable. Final source checks history before demanding perception. Saved claims run predates the correction. |
| Repairer pattern | Advisory research benchmark; unsupported garage context, not legal/insurer clearance. |
| Experimental AI/editing/view/baseline | Zero-weight/advisory/not run. Ineffective expensive AI classifier is not loaded in normal operation. Not a material clearance requirement. |
| Odometer readability | Required intended-slot saved OCR only; off display is a material gap. Speed/RPM/unrelated text cannot establish mileage. |

Final check framework distinguishes a skipped prerequisite (`not_run`) from a
measurement actually executed but inconclusive. Incident scene checks are claims-
only. The new runs predate those final applicability fixes, so old conservative
execution/gap records remain unchanged. Current behavior is fixture-verified;
there was no historical reprocessing to cosmetically change the PDFs.

Saved material gaps: claims `scene_consistency`, `plate_ocr`, `damage_plausibility`,
`severity_progression` (predates applicability correction); underwriting
`scene_consistency` (predates claims-only correction), `plate_ocr`, `entity_graph`,
`odometer_readability`. Missing optional EXIF/C2PA and zero-weight experiments do
not themselves block material completeness.

Production remains **model-selected routing plus material-evidence guards**.
There is no additive production score or calibrated fraud probability. Only a
converged model decision is labelled as a model recommendation. Raw outputs,
effective routing and human decisions remain distinct. The grouped two-axis
candidate remains shadow-only/unvalidated. UI and PDF display saved values with
readable rounding, without recalculating or promoting the candidate.

## PDFs and real browser evidence

Renderer **`fraudlens-pdf-2026-10-23-v9`** adds concise neutral summary/gaps/action,
facts/evidence, actual check panels, production routing, separately labelled shadow
calculation, human decision and appendix. Actual authorized references, registration
text, metadata and entity links support the graphics. Unsupported measurements
show compact gaps, not invented overlays, costs, maps, scores or private reasoning.
Photo attribution accompanies the [PDF/artifact index](final_presentation/README.md).

Both final PDFs were text-extracted, bounds/privacy-scanned, rendered on every page
and visually inspected. Headed installed Chrome displayed the native PDF viewer
inside admin. Browser downloads and protected API preview/download bytes match
the same saved artifact. Earlier v7/v8 PDFs were fetched again and their retained
hashes match. Preview/download consume zero generation calls and change no
analysis or human decision.

The first v9 UW preparation took **50.183 s**, exceeding the unchanged 45 s client
deadline; the server still saved the PDF. Inspection found unnecessarily fetched
historical PDF blobs/snapshot thumbnails. Final code projects small metadata and
report bases and joins version metadata in one query. The final browser retry
reuses the preserved artifact, without AI or a timeout increase. Snapshot/render
profiling spans were added. A new live case was not spent requalifying cold PDF
preparation after this correction.

## Focused verification

Ordinary tests block external model calls by default; no live-test opt-in. Counts
overlap and must not be summed as unique tests. Private logs remain in backend
`outputs/`; sanitized final receipts are in `docs/final_presentation/`.

| Suite / observation | Actual result |
|---|---|
| Final policy, normal controls, coverage, odometer/fallback and skipped checks | 105 passed, 38.60 s |
| Release readiness/engine/history/report/schema regressions | 89 passed, 81.58 s |
| Admission/normal/customer/final readiness | 84 passed, 331.65 s |
| Low/Medium/High, unknown/incomplete/historical/fallback risk | 38 passed, 16.87 s |
| Scene prerequisites / response fixtures | 28 passed, 5.48 s |
| Final v9 immutable versions/all-page fixtures/fallback reports | 9 passed, 57.38 s |
| Read-only provider/readiness | 5 passed, 6.84 s |
| Real disposable PostgreSQL concurrency/uncertain commit | 4 passed, 354.44 s |
| Real PG worker leadership/failover | 1 passed, 36.66 s |
| Real PG JPEG/EXIF embedded-NUL round-trip | 1 passed, 33.84 s |
| Final metadata/basis performance and immutable PDF checks | 4 local passed, 28.42 s; 2 disposable PG passed, 103.81 s |
| Final report/readiness suite after report-query optimization | 38 passed, 136.41 s |
| Native local admission | 64/64, no generation |
| Frontend typecheck | Final exit 0, 16.095 s |
| Production frontend build | Final exit 0, 22.043 s; one intermediate run under resource pressure took 108.742 s |

The real initial PostgreSQL ingestion error came from embedded NUL padding in EXIF
JSON; its transaction rolled back with no provider call. The fix sanitizes only
the extracted database representation while preserving original JPEG bytes/hash.
Tests also cover invalid counts/files, validator outage/retry, provider failure/
bounded recovery, shared budgets, duplicate submission, ownership/reviewer
conflicts, restart persistence and old report bytes. Disposable PG fixtures create
and remove only their own randomized schemas. The metadata regression enforces
bounded reads and absence of PDF payload in metadata handling.

Repeat from backend, sequentially:

```powershell
.\venv\Scripts\python.exe -m pytest test_final_readiness.py test_photo_admission.py test_normal_operation.py test_risk_presentation.py -q
.\venv\Scripts\python.exe -m pytest test_report_pdf.py -q
$env:FRAUDLENS_TEST_POSTGRES='1'
.\venv\Scripts\python.exe -m pytest test_postgres.py::test_report_history_metadata_has_bounded_reads_and_no_pdf_payload test_postgres.py::test_report_basis_idempotence_ignores_other_cases_and_versions_real_changes -q
Remove-Item Env:FRAUDLENS_TEST_POSTGRES
```

Use the existing private PG configuration. No Gemini authorization is needed for
these tests. Frontend `npm run typecheck`, then `npm run build` with old Node preview
stopped; restart Node afterward. Existing dependency range/directive warnings
remain; no broad upgrade was attempted.

## Performance and preservation

| Measurement | Observed interpretation |
|---|---|
| Previous reported cold model warmup | 663.875 s, historical workload |
| Final standalone native validator | 79.285 s, not total API startup |
| Rehearsal startup observer | HTTP first observed 20.802 s (late observer); validator 211.161 s; serialized full local readiness 351.452 s, including deliberate worker sequencing |
| Durable acceptance | Claims 11.281 s; UW 19.453 s. Prior 42.765 s was a different workload. |
| Pipeline elapsed | Claims 192.586 s; UW 168.467 s, **failed/blocked provider runs**, not successful AI performance |
| Check execution | Claims 90.216 s; UW 112.374 s |
| Fresh local OCR | Claims four calls roughly 15.8–17.9 s each; UW four roughly 14.3–20.2 s, two cache reuses |
| Memory | API peak about 1.65 GiB, worker 1.10 GiB; free RAM about 0.7–1.3 GiB during heavy stages |

API capability status serves before heavy warmup; API CLIP and worker OCR load
serially on the 8 GB machine. The zero-weight AI detector's prior approximately
78 s model load is avoided. Compatible embeddings/OCR are reused. Hash/EXIF work
moves before the database write transaction. SQL timings contain only operation
names/durations, not values. OCR and cloud database round trips remain bottlenecks;
no timeout was increased to conceal them. Final restored pilot startup is recorded
in `normal-startup.json`: HTTP 6.717 s, validator ready 298.594 s, all local
components observed ready 416.090 s including serialized worker startup. Overall
readiness remains HTTP 503 for the explicit provider pause; HTTP 200 health says
degraded. Cold model cost remains. An unrelated Ollama application was observed
using about 2.1 GiB during rehearsal; it was left untouched.

The original private backup covers 24 tables, 826 cases, 1,474 images, 38 jobs,
28 human actions and 63 report snapshots. Final read-only comparisons are in
[original-data-verification.json](final_presentation/original-data-verification.json).
New fictional accounts, cases, findings, reports and actions are confined to the
isolated schema. No historical run was enqueued. Credentials, private receipts,
database backups and provider controls remain ignored and excluded from Git.

## Focused source files and purpose

Backend-relative paths unless marked frontend. Published licensed photos, final
PDFs/screenshots, sanitized JSON and handover updates are documentation artifacts.

| Files | Purpose |
|---|---|
| `src/photo_admission.py` | Slot-aware relevance, separate extraction, retryable warmup, conservative blur check; preserve counts/bindings |
| `src/api.py` | Capability warmup/readiness, aware-time/coordinate wiring, prepared ingestion and compact report-basis projection; preserve unrelated CORS headers |
| `src/runtime_readiness.py`, `scripts/run_worker.py` | Atomic worker/OCR heartbeat and read-only provider status |
| `src/ingest.py` | EXIF JSON sanitization preserving originals; prepare hashes/metadata outside write transaction |
| `src/operating_policy.py`, `scripts/operate_provider.py` | Audited actual-count task, one validation schema and closure; history/caps preserved |
| `src/input_coverage.py`, `src/orchestrator.py`, `src/coverage_policy.py` | Intended odometer-slot requirement and saved-input sufficiency |
| `src/checks/base.py` | Honest skipped-prerequisite state; avoid zero-weight AI model loading |
| `src/checks/severity_progression.py`, `src/checks/scene_consistency.py` | History applicability before perception; claims-only incident context; sanitized weather failure |
| `src/assessment_explanation.py`, `src/risk_presentation.py` | Fallback/converged-model distinction; neutral incomplete risk |
| `src/postgres.py` | Content-free SQL operation timings |
| `src/report_pdf.py`, `src/report_visuals.py` | Renderer v9, actual slot provenance/graphics, metadata projection/join and render profiling; old artifacts preserved |
| `scripts/verify_final_presentation.py` | Actual persistent Chrome/API rehearsal with immediate private receipt, resumable inspection, ownership/sessions and immutable PDFs |
| `test_final_readiness.py`, `test_photo_admission.py`, `test_engine_reliability.py`, `test_durable_pilot.py`, `test_postgres.py`, `test_report_pdf.py` | Focused new behavior and regressions |
| Frontend `Intake.tsx`, `FieldSuggestions.tsx` | Explicit manual coordinates/timezone and guidance; clear obsolete upload status |
| Frontend `shared.tsx` | Multipart coordinate/aware-time wiring, preserve user transport changes |
| Frontend `reviewPresentation.ts`, `CaseReview.tsx` | Saved shadow rounding/declared-coordinate display, no production recalculation; preserve user layout/evidence changes |
| Frontend `report-panel.css`, `scripts/test-review-presentation.mjs` | Native PDF dialog label contrast; offline regression for fallback attribution and saved-value formatting |
| Root `.gitattributes` | Treat PDFs as binary so Windows checkout preserves saved byte offsets and hashes |

## Provider accounting and unresolved limits

Starting attempts **15**, new **2**, final **17**. Both fresh attempts returned
503 `UNAVAILABLE` on claims perception. Requested model `gemini-3.5-flash`, SDK
Google GenAI **2.18.1**, profile `gemini3_defaults_v2`, unchanged full structured
schema/local Pydantic validation. No fresh serving-model/response/token metadata
was returned to invent. No generic probe or metadata request was repeated.

Task ceiling 45; **28 unused slots closed**. Original history, limits and quota
controls retained. Provider pause and two-failure transient circuit persist.
Application allowances do not establish Google account entitlement/headroom.
The required external correction is restored provider availability, followed by
intentional bounded recovery under existing normal controls; these responses do
not indicate a key, schema, billing or cap correction.

Remaining evidence/capability limits: unreadable registration, powered-off
odometer, no independently verified loss/cost/identity/policy/ownership/current
condition, no calibrated accuracy, no newly qualified signed C2PA verification,
and no successful full live underwriting run. The earlier real claims fallback
is explicitly identified in [the handover](FINAL_PRESENTATION_HANDOVER.md).
