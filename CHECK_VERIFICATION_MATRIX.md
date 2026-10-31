# Presentation workflow verification — 18–20 October 2026

The new [workflow checklist](PRESENTATION_IMPLEMENTATION.md) maps requirements to
existing behavior, code and verification. [PRESENTATION_VERIFICATION.md](PRESENTATION_VERIFICATION.md)
records final authentication/ownership, two-tab, suggestion, submission, PDF,
decision, PostgreSQL, restart and mobile checks. The original research check and
archetype evaluation below is preserved; no new detector-accuracy claim is made.
Controlled model/embedding fixtures are distinguished from real database, PDF,
local image processing and browser tests. Gemini stop controls remain intact.

# Check and archetype verification — 15 October 2026

## Targeted continuation (no repeated corpus sweep)

The preserved 367-case execution inventory below was not rerun. Research policies,
weights, thresholds, retired checks, scenario databases and evaluation artifacts
remain unchanged. New production runs retain agent policy v3 and separately
record `checks_revision=production-checks-2026-10-15-v2`. Historical reports are not
rewritten. No verdict is inferred from a filename, archetype or desired outcome.

`case-0698`, the selected CONTEXT_MISMATCH representative, was traced on an
isolated consistent SQLite copy using recorded perception/weather only. It has
overcast weather, dry asphalt, daylight, no visible shadow, sun elevation 7.08°,
100% mean cloud and cached 1.2 mm precipitation for the declared UTC hour. The
existing weather contradiction requires clear/dry observations; overcast did not
satisfy it. Daylight agreed with solar geometry. Thus PASS meant no contradiction
in available comparisons, not demonstrated detection of its label. No rule was
changed to force CONCERN. Missing solar/weather/vision cues produce INCONCLUSIVE
in new focused tests; missing time/coordinates are disclosed as untestable in
reports. Partial scene comparisons now have explicit report limitations.

A separate production integration defect was found: intake sends an actual UTC
instant, whereas the generated research corpus tags local wall clocks as UTC.
New intake records the timestamp basis in a server-written audit. Production
uses aware instants directly, leaves an unverified basis inconclusive, and
records that basis in findings. It never derives the basis from applicant notes,
filenames or case IDs. The default research conversion remains unchanged.
Focused tests cover direct UTC use, abstention without lookups and the trusted
API-audit-to-check configuration path for aware/naive inputs.

The duplicate search now reads and prepares one complete comparison snapshot per
check invocation, rather than downloading every embedding again for every image.
It is discarded after the invocation; new submissions/reprocessing reload it.
No candidate sampling, weights, thresholds or attribution rules changed.
Exact ordered matches/scores agreed with the original float64 calculation for
seven existing PostgreSQL images against 1,446 comparison records. Focused
regressions include tied scores, null/zero embeddings, exclusion of the current
case and fresh evidence between invocations. An isolated real PostgreSQL test
also passed. This verifies execution equivalence and freshness, not independent
duplicate detection accuracy. See LATENCY_MEASUREMENTS.md for the remaining
cost of one complete cloud read and cold OCR.

Actual EasyOCR ran on one existing visually inspected project photo (original
rear registration manually transcribed before inference). One fresh local OCR
execution took **15.438 s** after **44.516 s** Reader initialization. Comparing the
rear registration yielded PASS; reusing the raw observation for a different
declaration yielded CONCERN (cache time rounded below 1 ms). This is real local
OCR/comparison execution with **zero provider requests**, not a model stub.
The photo contains two vehicles, so it does not validate vehicle attribution,
ownership, general OCR accuracy or consistent six-view underwriting evidence.
Private evidence: `readiness_20261015/readable-plate.json` and its isolated DB.

One historical false candidate was independently traced to advertising text:
`880-855-9217` was converted positionally into `BB08SS9217`. New production
comparison requires the first two registration letters to have been observed
as letters. It rejects this digit-only phone prefix as a plate candidate and
returns INCONCLUSIVE when no other candidate exists. Raw OCR caches remain
reusable; the current case comparison is always recalculated. The default
research coercion remains unchanged, with a regression preserving its old
output. This correction does not validate foreign/BH plate formats, candidate
jurisdiction, low-confidence reads or multi-vehicle attribution. Weight remains
0.3; no retired or zero-weight check was enabled.

New OCR evidence distinguishes engine unavailable, execution failed, no text,
text without a plate candidate, missing declaration, match, mismatch and low
confidence mismatch. Earlier aggregate INCONCLUSIVE counts cannot retrospectively
be assigned these new statuses. The frozen demo contains 1,499 historical plate
findings: 63 with empty raw-text arrays, 41 with nonempty arrays, and 1,395 in an
older evidence shape. These are stored findings, not 1,499 independent fresh
readings, and are separate from the 611 inventory outputs below.

Signed C2PA validation remains uncovered: no legitimate local signed fixture or
installed bindings. The attempted licensed Wikimedia plate download returned 403;
the actual comparison above instead used an existing local project photograph.
A genuinely consistent, authorized six-view vehicle set remains a missing input.

PostgreSQL continuation (15 October): the original inventory/accuracy limits
below remain historical and unchanged. The selected demo's cached perception,
findings, decisions and report bytes were verified during import. On isolated
`fraudlens_restore_20261015a`, `verify_postgres_checks.py` compared
`internal_duplicate`, `entity_graph`, `baseline_linkage`, `severity_progression`
and `threshold_gaming` against the same read-only SQLite demo. All ten original
workflow/archetype representatives produced identical findings, confidences,
explanations and evidence. Labels selected samples only; no label was passed to
a detector. Provider requests: zero. Private output:
`outputs/pilot_validation/postgres/check-equivalence.json`.
This covers PostgreSQL execution equivalence for those five checks. It does not
repeat the 367-case inventory on PostgreSQL or establish new detection accuracy;
the other ten registered checks, retired check and uncovered archetypes retain
the limitations below. No weight, threshold, research policy or prompt changed.

Real PostgreSQL browser processing also executed the unchanged production
policies on the fictional claims/underwriting submissions: 13 first-run claims
findings and 50 first-run underwriting findings were visible, with 21/58 on
their supplementary-evidence runs. Gemini was stopped, so both analyses and
their reprocessing runs truthfully failed with disclosed fallback. Claims and
underwriting reports remained readable in headless Chrome PDFs (9/22 pages),
and historical reports retained their earlier runs/evidence. These observations
exercise integration and do not expand archetype accuracy coverage or establish
successful new live vision/adjudication. Retired/zero-weight checks remain as
documented; no verdict was derived from labels, filenames or desired outcomes.

This records execution and coverage, not a deployment accuracy certificate. The audit dossier, existing ablation, policies, scenario labels and stored evidence were inspected before changes. Every database was copied with SQLite backup; originals and historical research outputs were preserved. No verdict was derived from filenames, case IDs, archetype names or expected demonstration outcomes. Labels selected evaluation samples and were used only afterward to count outcomes.

## Method and boundaries

`scripts/verify_check_inventory.py` executed the existing registry on 367 case records: 10 representatives in `fraudlens.db`, and 119 each in `fraudlens_scenarios.db`, `fraudlens_ring.db`, and `fraudlens_repeat.db`. The scenario samples include the original archetype representatives and all case IDs referenced in the three preserved scenario label artifacts. Related databases share records; these are not 367 independent samples. Each run requested all 15 registered checks; inapplicable checks may return no findings. There were **0 framework-caught check exceptions**, and the structured result contains all 367 executions. PowerShell marked the original redirected command unsuccessful because dependency warnings reached stderr; no Python traceback occurred and the result completed.

Detailed observed output is private and ignored by Git: `FraudLens-2.0-Backend/outputs/pilot_validation/check_verification.json`; four `checks-*.db` copies and `check_inventory.log` accompany it. Uncached external HTTP was deliberately disabled; existing perception/cache/index data was reused. No new Gemini result was supplied to this evaluation.

The verdict totals below are raw registry/research outputs across all four copies, often multiple findings per case. Production v2 onward separately converts every zero-weight finding to INCONCLUSIVE and preserves its original observations/verdict/confidence as experimental evidence. Historical policies and original evaluation files are unchanged. C = claims, U = underwriting. “Both” in the policy column means selected in both production policies; a selected zero-weight check still contributes no production detection signal.

## Inventory and observed execution

| Check / implementation (backend-relative) | Weight; production policy | Evidence and dependencies | Cases yielding output; P / concern / inconclusive findings | Limits |
|---|---|---|---|---|
| `ai_generation` — `src\checks\ai_detection.py` | 0; C/U | Image bytes; Transformers classifier/weights (optional) | 367; 0 / 0 / 611 | 611 inconclusive outputs; unsupported accuracy; zero weight. |
| `baseline_corruption` — `src\checks\baseline_corruption.py` | 0; U | Underwriting declaration plus legitimate vision damage observations | 158; 7 / 3 / 148 | Assumes undamaged declaration in research. Production v2 discloses that assumption and makes this zero-weight output inconclusive. |
| `damage_plausibility` — `src\checks\damage_plausibility.py` | 0.7; C | Claimed damage/amount plus parsed vision; no new provider calls here | 357; 209 / 0 / 148 | No concerns in this sample; plausible observations are not evidence of clean intent. |
| `digital_edit` — `src\checks\digital_edit.py` | 0; C/U | Image bytes; OpenCV/scikit-image forensic features and optional trained local model | 367; 0 / 0 / 611 | 611 inconclusive outputs; JPEG/capture artifacts confound editing; zero weight. |
| `internal_duplicate` — `src\checks\duplicate.py` | 1; C/U | Prior case images, hashes and CLIP embeddings; numpy/Pillow/open_clip | 367; 520 / 16 / 75 | A match requires examining the prior evidence and chronology; legitimate baseline/reuse may be expected. |
| `entity_graph` — `src\checks\entity_graph.py` | 1; C/U | Stored claimant, garage, phone, bank and address relationships | 367; 178 / 26 / 163 | Multiple shared identifiers suggest linkage, not collusion intent. UNASSIGNED is excluded. Applicant identities are unverified. |
| `view_completeness` — `src\checks\view_completeness.py` | 0; Excluded | Underwriting photos with parsed vision view labels | 158; 0 / 10 / 148 | View names supplied by applicant are not verified views. Excluded from production policy; zero weight. |
| `baseline_linkage` — `src\checks\baseline_linkage.py` | 1; C | Same-registration prior inspection, dates, image similarity, available vision; 30-day research rule | 302; 282 / 20 / 0 | Recent inspection linkage is a temporal lead, not proof that the baseline was fabricated. |
| `severity_progression` — `src\checks\severity_progression.py` | 1; C | Repeated registration, dates, parsed damage/severity and repair-completed history | 357; 162 / 47 / 148 | Missing repair records do not establish that no repair happened. Injected complete sequences are not prospective validation. |
| `external_corpus` — `src\checks\external_corpus.py` | 1; C/U | Image hashes/embeddings plus existing local external index; optional cached reverse-image lookups | 367; 405 / 194 / 12 | Uncached HTTP blocked for this review. Corpus membership indicates reuse, not submitter identity or intent. |
| `exif_metadata` — `src\checks\metadata.py` | 0.7; C/U | Extracted EXIF, timestamps/GPS/software and actual declaration time/location; Pillow | 367; 607 / 4 / 0 | Absent EXIF is common; metadata is editable; no authenticity certification. |
| `plate_ocr` — `src\checks\plate_ocr.py` | 0.3; C/U | Plate visible at useful resolution; optional EasyOCR/torch model weights | 367; 0 / 0 / 611 | 611 inconclusive outputs. Plate matching accuracy was not demonstrated; model availability/legibility may limit coverage. |
| `c2pa_credentials` — `src\checks\provenance.py` | 0.1; C/U | Signed content manifest plus optional c2pa bindings/trust evaluation | 367; 0 / 0 / 611 | 611 inconclusive outputs. No credentials is not fraud; signed-example validation remains uncovered. |
| `scene_consistency` — `src\checks\scene_consistency.py` | 1; C/U | Legitimate vision scene observations, declared place/time, geographic/weather/solar context; requests/pysolar | 367; 125 / 159 / 327 | External lookups disabled unless cached. Missing scene/declaration information stays inconclusive; model observations can be wrong. |
| `threshold_gaming` — `src\checks\threshold.py` | 1; C | Named garage and its existing claims/billing amounts around the preserved threshold | 302; 219 / 55 / 28 | Garage billing attribution only. Historical 34/34 target concerns came with 91/410 clean-claim concerns; no threshold change adopted. |
| `vehicle_consistency` — `src/checks/retired/vehicle_consistency.py` | Retired; disabled | Vehicle observations and prior perception | Not executed; absent from registry/policies | Remains retired; no supporting validation to reactivate. |

All implementation paths exist. Admission uses a local CLIP vehicle-likelihood gate; it is an upload suitability check and does not prove authenticity, ownership or fraud. Invoice/PDF/repair-document processing is not implemented. `get_perception()` now rejects stored parser-error responses rather than treating malformed vision as evidence. The original 130 perception records contained no such error records.

## Every original archetype

One original representative per workflow/archetype was observed. Single-sample concern counts cannot be used as sensitivity/specificity estimates. The original ground-truth CSV has eight fraud archetypes plus CLEAN; CLEAN occurs in both workflows.

| Workflow / archetype | Observed relevant finding | Coverage conclusion |
|---|---|---|
| claims / AI_GENERATED | `ai_generation`: 1 inconclusive | AI authenticity uncovered; zero-weight classifier. |
| claims / CLEAN | `threshold_gaming`: 1 concern | Claims representative had a garage concern; this does not establish claimant fraud. Underwriting representative had no concerns and missing vision remained inconclusive. |
| claims / CONTEXT_MISMATCH | `scene_consistency`: 1 pass | The selected mismatch was NOT detected; uncovered under this evidence/lookup coverage. |
| claims / DIGITAL_EDIT | `digital_edit`: 1 inconclusive | Editing detection uncovered; zero-weight detector. |
| claims / EXTERNAL_SOURCING | `external_corpus`: 2 concern | Both representative images matched the stored external corpus; no independent attribution validation. |
| claims / METADATA_FORGERY | `exif_metadata`: 1 concern | Representative metadata discrepancy executed; not general authenticity detection. |
| claims / REUSE | `internal_duplicate`: 1 concern | Representative reuse executed; match provenance/intent still requires review. |
| claims / THRESHOLD_GAMING | `threshold_gaming`: 1 concern | Representative garage billing signal executed; substantial historical clean-case concern rate. |
| underwriting / AI_GENERATED_BASELINE | `ai_generation`: 2 inconclusive | Authenticity uncovered. Raw baseline_corruption PASS and view_completeness concern do not validate fraud detection; both zero weight. |
| underwriting / CLEAN | `threshold_gaming`: no applicable output | Claims representative had a garage concern; this does not establish claimant fraud. Underwriting representative had no concerns and missing vision remained inconclusive. |

## Preserved injected scenario archetypes

The answer keys belong to isolated scenario datasets, not detector inputs. These samples were authored to exercise rules and are not independent examples of real fraud.

| Scenario / artifact / target check | Observed positive and control executions | Interpretation |
|---|---|---|
| Shared-identifier ring; `outputs/collusion_ring_labels.json`; `entity_graph` in ring DB | 18/18 injected member cases yielded a concern. 0/6 single-identifier controls concerned; all six were inconclusive. | Demonstrates multi-identifier rule execution on injected relationships; does not establish real collusion precision. |
| Recent baseline linkage; `outputs/baseline_linkage_labels.json`; `baseline_linkage` in scenarios DB | 20/20 injected recent claims concerned; 0/10 older controls concerned (10 PASS). | Exercises the preserved window/similarity rule. Does not detect AI-generated inspections independently. |
| Oscillating repeat damage; `outputs/repeat_claim_labels.json`; `severity_progression` in repeat DB | Eight positive sequences, 24/24 constituent cases concerned; six monotone control sequences (18 cases) and six repaired sequences (18 cases) all PASS. | Evaluation includes the complete stored sequence, including later declarations. No prospective temporal accuracy demonstrated. |

## Research reproducibility and provider boundary

The latest preserved ablation report is incomplete: baseline 99/99 eligible, agent 58/99 eligible, following 22 exclusions from 121 selected records. The existing integrity verifier returned 58 verified decisions out of 58 with no problems on an isolated copy. Seven clean underwriting cases in the historical evaluated subset were all flagged, with zero underwriting fraud examples there; that subset cannot establish underwriting sensitivity. Historical `check_performance_v2.md` and threshold investigation results remain frozen. Threshold candidate experiments did not justify adopting a replacement rule.

Production interpretation corrections are versioned separately in `src/agent/production_policy.py`: v1 integrates already registered nonzero scenario checks; v2 clarifies zero-weight limitations and actual applicant declarations; current v3 states that the billing threshold is a preserved research benchmark with unverified current legal applicability. Initial 14 October browser reports used v2; the latest 15 October rehearsals verify v3. Research policies in `src/agent/policy.py`, weights, thresholds, historical databases and output files are preserved.

Later performance corrections preserve verdict rules: duplicate-pool metrics first moved to a SQL count, then to the same complete comparison snapshot used for matching (see the current continuation above). Production-only plate OCR caches raw text/confidence observations by image hash and engine version/configuration, recomputes each case's registration comparison, and releases cache writer locks before subsequent inference. Focused regressions verify reuse without identity mixing and writer blocking. One earlier actual local reading took 1.641 seconds, reused its cache in 0.015 seconds, returned identical INCONCLUSIVE findings with zero plate observations, and released its writer lock. No provider was called. This establishes an execution/cache example, not OCR accuracy. The 367 raw registry executions predate these performance corrections; no new detection accuracy is inferred from them.

Original 14 October Gemini attempts: **2/15**, both vision HTTP 503 failures. This 15 October readiness continuation made **zero additional requests** and preserved the persistent stop. No new successful Gemini vision or agent adjudication is claimed. Offline tests use disclosed stubs where noted; cached legitimate perception and actual deterministic checks are different sources of evidence. Live vision, live agent adjudication, AI/edited-image accuracy, signed C2PA validation, general plate OCR coverage, complete external lookup coverage, same-vehicle multi-view inspection accuracy and independent real-world adjudication remain uncovered.
