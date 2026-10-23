# Upload admission repair — 23 October 2026

Baseline: `27a8c39512a56d42c5ee2ade8a246f08c143e62b`, on the existing repair
branch. Unrelated staged documents, API/CORS and frontend transport/evidence edits
are preserved. No dependency, database schema, risk policy or provider control
change is part of this repair.

## Confirmed cause

The running v3 validator accepted six genuine corpus car photographs in
`vehicle_overview`, then withheld **all twelve** applications of those same
photographs to `damage_overview` and `damage_closeup` (ten rejected, two uncertain).
These were HTTP 200 semantic results, with no timeout, duplicate or slot-mapping
error. Damage-slot prompts described damaged panels and interiors without the
exterior prompts used by Vehicle overview.

For example, `data/curated/whole/whole_0001.jpg` scored **0.2620** as an exterior
against **0.2060** competing similarity: accepted. In either damage slot it scored
**0.1287** against that same **0.2060** competitor: rejected. The unchanged
thresholds are **0.175** absolute similarity and **0.020** positive margin.
These measurements are CLIP cosine similarities, not probabilities.

The frontend also mapped validator/network errors to `needs_replacement`.
That incorrectly suggested replacing valid evidence when validation had not run.

## Implemented behavior

Policy **`initial-photo-admission-2026-10-23-v4`** gives both damage slots the
existing exterior prompts as well as damaged/undamaged part and interior prompts.
Visible damage is assessed after submission. Neither threshold is reduced.
Explicit document competitors are retained, but an authored printed-car-page
control still passes; this limitation is recorded in the verification results.
No filename, applicant or fixed-image exception exists.

Mounted plates and dashboards retain their dedicated positive prompts. Their
acceptance does not require a whole vehicle or readable OCR. Text, damage, angle,
identity, EXIF, capture date and authenticity remain separate review questions.
An off/unreadable odometer is not a verified mileage reading. Damage admission
now explicitly returns `damage_verified=false` and `slot_label_verified=false`.

Both authenticated prevalidation and final intake call the same server
`photo_admission.validate`. Cache reuse still binds actor/session, case type,
slot, immutable bytes and the new policy version. Old v3 decisions cannot be
reused under v4. Expired/missing cache entries run the same policy again.

The frontend distinguishes `unavailable` (keep the photo and recheck) from
semantic uncertainty/rejection. Final validator outages identify the affected
slot without clearing other accepted files. Revision guards remain; changing case
type remounts the form so old slot results cannot cross into a different form.

Exactly four Claims and six Underwriting photographs remain mandatory. MIME,
actual decoding, 5 MiB/25-megapixel limits, minimum dimensions, normalized duplicate
hashes, EXIF orientation, RGB conversion, authentication, ownership, idempotency,
atomic persistence and supplementary-evidence requirements remain in force.

## Changed implementation files

| Path | Purpose |
|---|---|
| `FraudLens-2.0-Backend/src/photo_admission.py` | Relevant exterior/part prompts for damage slots, document competitors, v4 cache isolation and honest reasons |
| `FraudLens-2.0-Backend/test_photo_admission.py` | Controlled damage/exterior behavior, unchanged cutoffs, color-mode and invalid-file regressions |
| `FraudLens-2.0-Backend/scripts/verify_photo_admission_repair.py` | Native offline recognition across every slot; actual isolated API prevalidation and four/six acceptance with receipt replay |
| `FraudLens-2.0-Backend/scripts/verify_photo_admission_browser.py` | Controlled desktop/mobile outage, retry, stale replacement/removal and final-error checks |
| `FraudLens-2.0-Frontend/src/experience/photoSlots.ts` | Capture guidance distinguishes admission from damage assessment |
| `FraudLens-2.0-Frontend/src/experience/Intake.tsx` | Retryable unavailable state, retained photographs and case-type state isolation |
| `FraudLens-2.0-Frontend/src/experience/customer-api.ts` | Preserve HTTP status for accurate upload error presentation |
| `FraudLens-2.0-Frontend/src/experience/shared.tsx` | Preserve backend error code/status for final slot error presentation |

## Verification

Final measurements and sanitized receipts: [upload repair artifacts](upload_repair/README.md).
Real native recognition is reported separately from controlled API/UI edge cases.
Tests do not establish perfect classification, analysis accuracy, or successful AI.

Only licensed presentation photographs enter the native isolated submissions.
Other existing corpus images are recognition tests, not a same-vehicle photo set.
The mounted-plate crop is an actual crop of the archived licensed rear photograph;
it is not an independently captured new view. Original evidence is never modified.
[Photo provenance and limitations](presentation_assets/README.md).

## Running and repeatable checks

From `FraudLens-2.0-Backend`:

```powershell
.\venv\Scripts\python.exe -m pytest test_photo_admission.py test_customer_workflow.py test_pilot_workflow.py -q
.\venv\Scripts\python.exe scripts/verify_photo_admission_repair.py
.\venv\Scripts\python.exe scripts/verify_photo_admission_browser.py
```

Native qualification loads one local CLIP model, with offline model caches and no
OCR/Gemini call. Its API acceptance uses a disposable SQLite database, worker off,
fictional customer and exact real photo sets. It verifies durable ownership/job
records, cache consistency and idempotent replay, not case analysis. UI edge-case
tests intercept all API calls and label their screenshots as controlled fixtures.
Run model-heavy checks and frontend builds sequentially on this laptop.

The existing Panel launcher remains the supported startup path:

```powershell
.\scripts\start_review.ps1 -Dataset Panel -Service Api
.\scripts\start_review.ps1 -Dataset Panel -Service Worker
```

Start them in separate terminals; wait for API validator warmup before loading
worker OCR. Both select `fraudlens_validation_panel_20261022` and original shared
controls. Do not start a second API on an occupied port. From the frontend:

```powershell
npm run typecheck
npm run build
$env:NITRO_HOST='127.0.0.1'
$env:NITRO_PORT='5173'
node .output/server/index.mjs
```

Customer: <http://127.0.0.1:5173/dashboard>. Admin:
<http://127.0.0.1:5173/admin>. Validator warming/busy/unavailable requires a recheck,
not replacement. Gemini remains intentionally paused; the saved/manual-review
and partial-local-processing behavior from the prior patch is unchanged.
