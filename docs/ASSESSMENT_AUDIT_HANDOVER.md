# Dependency, input and assessment audit handover

Baseline: `f35aa755db6d5cc88c7746a3672a1aa118761ea1`, branch
`repair/analysis-pipeline-20261020`, 22 October 2026. No applicable AGENTS.md.
Original staged/working edits were backed up separately and excluded from this
commit. No generation request, metadata request, provider-control revision,
production data change, historical batch, deployment or push was performed.

| Requirement | Result and limits |
|---|---|
| Current architecture/history | Inspected; historical corrections and source references in assessment policy |
| Dependencies | Installed/version/import inventory and substantive offline model/image/OCR/solar/auth tests; untested/transitive references remain explicitly unconfirmed |
| Input use | Every multipart submission field indexed; coordinates now reject partial/nonfinite/out-of-bounds pairs; declarations remain unverified context where no authoritative integration exists |
| Applicable checks | Exact registered weights/defaults, case types and test references exported; scene prerequisites now produce explicit inconclusive results; independent accuracy is not established |
| Two-axis assessment | Implemented in shadow only, with deduplicated/grouped support, separate sufficiency and mandatory guards; no calibrated probability |
| Evaluation | 13 authored claims and 10 authored underwriting scenarios; unsafe gap clearance 0/8 and 0/5, equal to current guard on these authored tests; no independent precision/recall estimate or promotion justification |
| Persistence | New explanation JSON includes complete candidate calculation; normal audit/snapshot paths persist it without schema changes; old snapshots are not reconstructed |
| UI/PDF | Saved candidate shown separately from production risk; v6 reports use identical persisted object; replay/fixture samples rendered, all pages inspected |
| Performance | Previous latency evidence examined; no safe measured application speedup claimed. Intake already reuses admission embeddings. Cold model/import/memory/DB costs remain unresolved |
| Live verification | Not authorized in this task; no fresh claims run, underwriting live validation deferred |

Changed application files:

- `FraudLens-2.0-Backend/src/shadow_assessment.py`: pure candidate, bounded authored
  parameters, group maxima/product, coverage and exclusions, garage separation.
- `src/assessment_explanation.py`: version v3, case/run/evidence calculation frozen
  at assessment time. Model recommendation and effective route remain separate.
- `src/api.py`: focused coordinate validation only; original CORS changes preserved.
- `src/checks/scene_consistency.py`: explicit missing-coordinate/time finding.
- `src/report_pdf.py`, `src/report_visuals.py`: v6 with clear shadow labels and
  saved worked calculation; retained v1–v5 paths/artifacts.
- `FraudLens-2.0-Frontend/src/experience/reviewPresentation.ts`, `CaseReview.tsx`:
  optional saved shadow fields and reviewer panel; no frontend calculation.
- `scripts/build_assessment_audit.py`, `scripts/evaluate_shadow_assessment.py`:
  reproducible static/installed audit, authored comparison and offline replay.
- `scripts/verify_risk_visual_browser.py`, `test_shadow_assessment.py`,
  `test_dependency_smoke.py`: calculation agreement, boundaries, safety invariants,
  coordinate contract and actual cached dependency smoke tests.
- Five requested audit/policy documents, this handover and `docs/assessment_audit/`:
  downloadable replay/fixture PDFs and traceable evaluation/layout evidence.

Dependency smoke tests passed four tests in 726.71 s. They used cached CPU models
with downloads disabled, not imports alone: normalized repeatable 512D CLIP,
identical/different image ordering, Torchvision NMS, actual labelled EasyOCR plus
blank abstention, Pillow orientation/known EXIF/invalid image, hash transformation,
OpenCV edges, NumPy search and fixed solar/authentication checks. This tiny OCR
fixture is not an OCR accuracy benchmark. C2PA native signed valid/invalid samples
are missing; controlled verification-state regressions do not substitute for them.

Disposable PostgreSQL: three selected persistence/temporal tests passed, 107
deselected. Customer/engine/recovery suite: 81 passed. Latest candidate/coordinate/
PDF tests: 15 passed. Explanation/report/normal-control suite: 80 passed, 35
deselected. These overlap and must not be added as unique totals. Bounded check
results are recorded in the evaluation document. An initial older-suite attempt
was interrupted when its corpus-wide sweep was identified; that sweep used a
read-only source backed up into memory, preserving the research database. It is
excluded from the bounded run. A decorator helper named `test(fn)` is not a test;
`-o python_functions=test_*` avoids collecting it as a missing-fixture test.

Frontend typecheck and production build passed. Build warnings include installed
Vite 7.3.6 versus the Nitro builder's requested ^8 range and ignored dependency
`use client` directives; no broad upgrade was attempted. Fixture browser checks
passed all Low/Medium/High, missing/category-only, stale/historical, incomplete,
desktop/mobile states and saved R/C agreement, with zero JS errors/overflow.
Preview/download fixture bytes match and trigger no processing/action endpoint.
These are fixture UI tests, not a live pipeline qualification.

Native C2PA signed verification, authoritative identity/policy/police/RTO/repair
prices, independently authenticated same-vehicle six views and fabricated-clean
baseline detection remain unavailable/unestablished. Detector limitation strings
in the check matrix are code-declared historical research assertions, not newly
remeasured accuracy. No signed fixture or unavailable service is marked working.

Run from backend (ordinary tests block external models by default):

```powershell
.\venv\Scripts\python.exe -m pytest test_dependency_smoke.py -q
.\venv\Scripts\python.exe -m pytest test_shadow_assessment.py test_analysis_recovery.py test_engine_reliability.py test_customer_workflow.py -q
.\venv\Scripts\python.exe -m pytest test_checks.py -q -o python_functions=test_* --deselect=test_checks.py::test_duplicate_check_reuse_vs_clean_sweep
.\venv\Scripts\python.exe -X utf8 scripts/build_assessment_audit.py
.\venv\Scripts\python.exe -X utf8 scripts/evaluate_shadow_assessment.py
.\venv\Scripts\python.exe scripts/verify_visual_report_layout.py --output ../docs/assessment_audit
```

The isolated PostgreSQL tests require explicit `FRAUDLENS_TEST_POSTGRES=1` and the
existing private `.env`; the fixture creates/removes only its own random schema.
Never point fixture mutation code at the pilot schema.

Normal startup remains:

```powershell
# Backend: separate API and worker terminals; existing private configuration
.\scripts\start_pilot.ps1 -Database postgresql -Schema fraudlens_pilot -Port 8001 -NoWorker
.\scripts\start_pilot.ps1 -Database postgresql -Schema fraudlens_pilot -WorkerOnly
# Frontend directory
npm run dev
```

Customer `http://127.0.0.1:5173/dashboard`; reviewer `/admin`; API port 8001.
The fixture browser used a local production frontend only, with every API request
intercepted; no API/worker restart or new case was needed. Restart API/worker
normally to load these code changes before future authorized ordinary work.
Do not rerun old cases just to populate the shadow field. Rollback reverts this
focused code commit; it needs no ledger/database reset, and preserves saved v6
artifacts and original human decisions. Candidate promotion remains a separate
decision requiring independently justified evidence.

Final bounded check result: **33 passed, one corpus sweep deselected**. `test_checks.py` stale assertions were updated; absent native classifier measurements are now distinguished from an explicit controlled classifier fixture. `src/checks/ai_detection.py` persists only the exception type on model-load failure, protecting private cache paths/URLs. No native AI success is claimed. No measured application latency optimization was demonstrated; performance remains an open requirement.

Final candidate/coordinate/PDF/sanitized-loader regression: **16 passed** in
22.01 seconds, including the final safe-error change. It supersedes the earlier
15-test count above. Production/new-live persistence of shadow fields remains
implemented but not live verified; offline PostgreSQL fixtures exercised the
existing JSON persistence path. Independent policy promotion remains unapproved.
