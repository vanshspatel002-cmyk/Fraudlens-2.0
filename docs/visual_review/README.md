# Risk and report visuals — controlled verification

Renderer: **fraudlens-pdf-2026-10-21-v4**. Presentation contract:
**risk-presentation-2026-10-21-v1**. Date: **21 October 2026**.

These PDFs and screenshots use fictional accounts, authored illustrations and
controlled saved observations. They demonstrate layout and software behavior;
they do not establish successful live AI analysis or improved detection accuracy.
No real applicant data or credentials are included. No push or deployment was performed.

## Open the results

| Artifact | Link |
|---|---|
| Claims, completed High baseline | [PDF](claims-high.pdf) · [every page](claims-high-all-pages.png) |
| Underwriting, completed Medium category-only routing | [PDF](underwriting-medium.pdf) · [every page](underwriting-medium-all-pages.png) |
| Claims, incomplete / neutral | [PDF](claims-incomplete.pdf) · [every page](claims-incomplete-all-pages.png) |
| Underwriting, incomplete / neutral | [PDF](underwriting-incomplete.pdf) · [every page](underwriting-incomplete-all-pages.png) |
| Additional Low / Medium baselines | [Low PDF](claims-low.pdf) · [Medium PDF](claims-medium.pdf) |
| Claims laptop header | [Before](screenshots/before-claims-high-1440.png) · [After](screenshots/after-claims-high-1440.png) |
| Claims narrow mobile header | [Before](screenshots/before-claims-high-390.png) · [After](screenshots/after-claims-high-390.png) |
| Underwriting laptop header | [Before](screenshots/before-underwriting-medium-1440.png) · [After](screenshots/after-underwriting-medium-1440.png) |
| Underwriting narrow mobile header | [Before](screenshots/before-underwriting-medium-390.png) · [After](screenshots/after-underwriting-medium-390.png) |
| Representative check graphics | [Image comparison](screenshots/check-image-reuse.png) · [OCR](screenshots/check-registration.png) · [Metadata](screenshots/check-metadata.png) · [Relationships](screenshots/check-relationships.png) · [Billing pattern](screenshots/check-billing-pattern.png) · [Experimental exclusion](screenshots/check-experimental.png) · [Unavailable](screenshots/check-unavailable.png) |

The comprehensive fixtures deliberately exercise all registered check families,
including experimental and out-of-policy results. Claims samples are 10 pages
and underwriting samples 9 pages, including an isolated technical appendix.
The first page is the one-minute summary; repeated per-image results are grouped.
Actual reports include only their saved data and applicable/recorded checks.
Full-size page renders are retained locally in the ignored `.renders/` directory
and can be regenerated without contacting a model or application database.

## Risk display rules

`assessment_presentation` is returned by the reviewer report API and frozen with
each new snapshot. It carries the run, policy, processing/completeness state,
category, optional validated score/scale/thresholds, and explanation. The UI
displays that contract; the PDF reads the same frozen contract.

| Saved routing band | Display category | Numeric baseline rule, when applicable |
|---|---|---|
| `clear` | Low | Score < 0.3 |
| `request_evidence` | Medium | 0.3 ≤ score < 0.6 |
| `desk_review` | Medium | 0.6 ≤ score < 1.0 |
| `escalate_siu` | High | Score ≥ 1.0 |

These are the existing rules. No engine thresholds or weights were changed.
The three equal-width display segments are **categories**, not equal numerical
ranges. Their marker highlights a category rather than implying a precise
position. A baseline score is unbounded and is not a probability of fraud.
Production agent routing has no additive numeric score; confidence is not used
as one. The controlled baseline fixtures use the actual duplicate comparison
threshold/confidence helper and existing `baseline.decide` aggregation.

The display stays neutral when processing, required coverage, convergence,
run association, policy or supported category/basis is missing or invalid.
Queued/running/failed/interrupted/stale states never acquire a reassuring Low
marker. A historical completed assessment is explicitly labeled historical.
Human decisions remain separate. Unknown older snapshots retain their original
renderer and receive no invented data.

Required execution coverage is separate from risk. Optional zero-weight check
results are excluded from the required-completion count. Each check panel names
its purpose, evidence, saved observation, interpretation, contribution/exclusion
and uncertainty. Missing data uses a neutral state/reason table.

## Verification

- Frontend TypeScript check and production build passed with Node 22.23.3.
  The existing Vite/Nitro major-version warning remains nonfatal; no dependency changed.
- Focused risk/PDF tests passed, including actual baseline boundaries, invalid
  numeric values, missing scores, unsupported categories/sources, incomplete
  coverage, stale runs, historical labels, customer/report authorization and
  private internal-comparison freezing. Existing reader-layout tests remain
  pinned to renderer v3 to protect its historical behavior.
- Across the suite runs, **84 distinct backend cases passed**: 34 risk/display
  cases, 17 PDF/history cases, and 33 existing calculation/customer/reviewer
  cases. Repeated focused runs are not counted as additional cases.
- Existing assessment explanation, customer and reviewer workflow tests passed.
  Separate version-retention cases verify that preparing v4 preserves original
  v1, v2 and v3 artifacts and snapshot identities.
- Offline browser checks cover both case types, Low/Medium/High, missing score,
  failed/incomplete/stale/unsupported/historical states, 1440 px laptop and
  390 px mobile widths. No horizontal overflow or JavaScript exception was found.
- Preview and download returned identical saved PDF bytes for both case types;
  the browser made no analysis or decision request. Every API request in this
  harness was fulfilled locally from fixtures; there was no live fallback.
- All 58 sample PDF pages were extracted and rasterized. Text stayed inside
  page bounds and image aspect ratios were preserved. All-page contact sheets
  and representative full-size check graphics were inspected. Section headings
  stay with their first check panel; technical references stay in the appendix.

Machine-readable records: [PDF inspection](pdf-inspection.json),
[before browser checks](browser-before.json), [after browser checks](browser-after.json).

No Gemini requests were made. Tests wrote only temporary fixture databases;
the existing application database, evidence, decisions, provider controls and
saved reports were not modified by these tests. No schema migration is needed.

## Data limitations and deliberate fallbacks

- Existing snapshots do not contain OCR crops, real damage masks/boxes or map
  geometry. The report does not fabricate overlays, crops, heatmaps or maps.
- External corpus filenames are not authority to open private files. Only
  database-owned internal references can acquire frozen comparison thumbnails;
  otherwise a labeled missing-reference panel appears.
- Severity history is shown as dated observations/ordinal labels. No physical
  severity percentage is derived from image area or incompatible scales.
- Shared identifiers are relationships, not proof of fraud. Missing EXIF is not
  proof of editing. Garage billing bands remain research benchmarks, not verified law.
- Missing recorded measurements produce neutral text/table panels instead of
  invented charts. Raw experimental classifier outputs are labeled and excluded
  when their saved registered weight is zero.
- Live claims/underwriting qualification and historical processing remain subject
  to the persisted provider stop described in the current handover.

## Reproduce safely

From the backend directory, with the existing virtual environment:

```powershell
.\venv\Scripts\python.exe -X utf8 -m pytest test_risk_presentation.py test_report_pdf.py -q
.\venv\Scripts\python.exe -X utf8 -m pytest test_assessment_explanation.py test_customer_workflow.py test_pilot_workflow.py -q
.\venv\Scripts\python.exe -X utf8 scripts/build_visual_report_samples.py
.\venv\Scripts\python.exe -X utf8 scripts/verify_visual_report_layout.py
.\venv\Scripts\python.exe -X utf8 scripts/verify_risk_visual_browser.py --phase after
```

The browser harness needs the locally built frontend running on 5173; it does
not need a running backend and does not contact it. Before screenshots were
captured from the pre-change frontend; reproducing `--phase before` requires
that earlier build. Do not use live-analysis helpers for layout verification.

## Exact implementation files and purpose

| Repository-relative file | Purpose |
|---|---|
| `FraudLens-2.0-Backend/src/risk_presentation.py` | Pure shared display contract; no scoring or I/O. |
| `FraudLens-2.0-Backend/src/api.py` | Adds the display contract to reviewer reports. |
| `FraudLens-2.0-Backend/src/report_pdf.py` | v4 dispatch/versioning, preserved v1–v3 dispatch, frozen authorized internal comparisons and applicable-check metadata. |
| `FraudLens-2.0-Backend/src/report_visuals.py` | New vector risk bar, executive page, check-specific graphics, calculation/limitations and appendix. |
| `FraudLens-2.0-Backend/test_risk_presentation.py` | Display boundaries/states, PDF consistency, authorization and safe comparison tests. |
| `FraudLens-2.0-Backend/test_report_pdf.py` | Pins legacy reader regression tests to v3 and extends historical retention to v1–v3. |
| `FraudLens-2.0-Backend/scripts/build_visual_report_samples.py` | Authored offline samples; no real analysis. |
| `FraudLens-2.0-Backend/scripts/verify_visual_report_layout.py` | Every-page extraction/rasterization, bounds/aspect checks, contact sheets and check crops. |
| `FraudLens-2.0-Backend/scripts/verify_risk_visual_browser.py` | Fully intercepted before/after UI, state, responsive and saved-PDF checks. |
| `FraudLens-2.0-Frontend/src/experience/RiskIndicator.tsx` | Accessible categorical header display from the server contract. |
| `FraudLens-2.0-Frontend/src/experience/risk-indicator.css` | Shared risk colors, categorical marker, neutral states and responsive wrapping. |
| `FraudLens-2.0-Frontend/src/experience/Admin.tsx` | Places the indicator beside registration. |
| `FraudLens-2.0-Frontend/src/experience/shared.tsx` | Passes the persisted report presentation to the case-detail UI. |
| `ANALYSIS_REPAIR_HANDOVER.md` | Documents v4, display rules, history, verification and limitations. |
| `docs/visual_review/README.md` | Artifact index, acceptance evidence and reproduction steps. |
| `docs/visual_review/.gitignore` | Excludes reproducible full-size intermediate page renders. |
| `docs/visual_review/.gitattributes` | Preserves PDF/PNG bytes across checkout and keeps JSON line endings stable. |

The remaining files in this directory are controlled PDF/PNG/JSON deliverables,
not application data. The earlier staged documentation, local connectivity and
Claims-loading edits, and pre-existing mentor documents are preserved separately
and are not part of the focused visual implementation commit.

## Generated deliverable manifest

| Exact path below `docs/visual_review/` | Purpose |
|---|---|
| `browser-after.json` | Machine-readable verification record. |
| `browser-before.json` | Machine-readable verification record. |
| `claims-high-all-pages.png` | Every-page contact sheet. |
| `claims-high.pdf` | Controlled v4 PDF sample. |
| `claims-incomplete-all-pages.png` | Every-page contact sheet. |
| `claims-incomplete.pdf` | Controlled v4 PDF sample. |
| `claims-low-all-pages.png` | Every-page contact sheet. |
| `claims-low.pdf` | Controlled v4 PDF sample. |
| `claims-medium-all-pages.png` | Every-page contact sheet. |
| `claims-medium.pdf` | Controlled v4 PDF sample. |
| `fixtures.json` | Fictional saved report inputs. |
| `pdf-inspection.json` | Machine-readable verification record. |
| `screenshots/after-claims-high-1440.png` | Controlled admin header screenshot. |
| `screenshots/after-claims-high-390.png` | Controlled admin header screenshot. |
| `screenshots/after-underwriting-medium-1440.png` | Controlled admin header screenshot. |
| `screenshots/after-underwriting-medium-390.png` | Controlled admin header screenshot. |
| `screenshots/before-claims-high-1440.png` | Controlled admin header screenshot. |
| `screenshots/before-claims-high-390.png` | Controlled admin header screenshot. |
| `screenshots/before-underwriting-medium-1440.png` | Controlled admin header screenshot. |
| `screenshots/before-underwriting-medium-390.png` | Controlled admin header screenshot. |
| `screenshots/check-billing-pattern.png` | Representative rendered check graphic. |
| `screenshots/check-experimental.png` | Representative rendered check graphic. |
| `screenshots/check-image-reuse.png` | Representative rendered check graphic. |
| `screenshots/check-metadata.png` | Representative rendered check graphic. |
| `screenshots/check-registration.png` | Representative rendered check graphic. |
| `screenshots/check-relationships.png` | Representative rendered check graphic. |
| `screenshots/check-unavailable.png` | Representative rendered check graphic. |
| `screenshots/claims-high-grayscale.png` | Grayscale readability check. |
| `screenshots/underwriting-medium-grayscale.png` | Grayscale readability check. |
| `underwriting-incomplete-all-pages.png` | Every-page contact sheet. |
| `underwriting-incomplete.pdf` | Controlled v4 PDF sample. |
| `underwriting-medium-all-pages.png` | Every-page contact sheet. |
| `underwriting-medium.pdf` | Controlled v4 PDF sample. |
