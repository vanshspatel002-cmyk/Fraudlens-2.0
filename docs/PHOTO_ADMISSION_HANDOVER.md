# Current upload repair — 23 October 2026

Policy **initial-photo-admission-2026-10-23-v4** supersedes the v3 admission
prompts below. Undamaged exteriors now qualify for both damage slots without
lowering the 0.175 similarity floor or 0.020 margin. Validator outages are
retryable UI states; accepted photos are retained. Exactly four/six photos,
backend admission, duplicates, ownership and submission safeguards remain.

Native checks: 55/55 positive image-slot cases accepted; all 70 unrelated
negative slot cases withheld (68 rejected, 2 uncertain/retake). The authored printed-car-page control remains a
documented false acceptance, so no perfect authenticity/classification claim is
made. Actual Chrome accepted all ten slots at desktop/mobile widths plus a real
portrait part crop (21 uploads). Native disposable API acceptance passed for
both counts, final cache reuse and UUID4 receipt replay. These are admission
checks, not successful AI analysis. Backend regressions: 70 passed; frontend
typecheck/build passed. Gemini use: zero; controls unchanged.

See [repair, exact files and commands](UPLOAD_VALIDATION_REPAIR.md) and
[receipts/screenshots/limitations](upload_repair/README.md).
The earlier documentation below is retained as dated history.

---

# Current photo-admission result — 23 October 2026

Policy `initial-photo-admission-2026-10-22-v3` supersedes the v2 limitation below.
Real four-photo claims and six distinct same-car underwriting submissions passed
the authenticated server-side local gate. Final native smoke: 64/64 expected
results, zero generation, unchanged similarity floor 0.175 and margin 0.020.
Relevant mounted plates/dashboard/parts can pass without readable OCR; responses
explicitly withhold identity, independent slot verification and text completeness.
The licensed same-car dashboard is off: readable mileage remains unverified and
a required material assessment gap, not a reason to claim a non-vehicle image.
Classifier acceptance is not accuracy, authenticity or view-identity proof.

API loads CLIP during visible background warmup; worker loads OCR separately.
Outage/warming/busy gives retryable 503. Exact 4/6 counts, supplementary requirements,
actor/slot/hash cache binding, duplicate protection and stale UI guards remain.
Original JPEGs are preserved; embedded NUL padding is sanitized only in extracted
JSON to prevent the actual PostgreSQL failure. Severe blur has a conservative
detail floor. No Gemini relevance request was needed.

See [current policy](PHOTO_ADMISSION.md), [real evidence provenance](presentation_assets/README.md),
[native results](final_presentation/native-final.json) and
[complete verification](FINAL_PRESENTATION_VERIFICATION.md). Live AI completion
is blocked by two provider 503s, not by photo count/admission. Prior evidence below
is historical and retained.

---

# Photograph admission handover — 22 October 2026

Starting point: `d8bb8a741c86c885070b158b01d1a71faaa7d471`, current repair branch.
Policy: `initial-photo-admission-2026-10-22-v2`. No package installation, schema
migration, provider request, pilot data change, report rewrite or decision change.

## Inspection, dependencies and side effects

Inspected initial intake, multipart mapping, the existing at-least-one vehicle
gate, shared CLIP loader, OCR reader, image ingestion, receipt fingerprinting,
atomic commit/recovery, supplements and workflow fixtures. Reused installed
Pillow, NumPy, OpenCLIP, EasyOCR, FastAPI, React and existing customer-session
transport. Existing user CORS/transport edits and staged documents were excluded
from the focused commit.

The intended behavior change is strict admission for new initial cases. Real
photos can request retakes; unavailable models fail closed. Native model startup
is slow on this machine. Prevalidation is customer-authenticated and rate-limited.
The cache is process-local, not a durable promise or cross-worker certificate.
Original evidence bytes remain intact. Historical initial receipts can replay;
new under-count submissions cannot. Supplement requests retain their original
specific count rules. No persistent control/database modification needed a
backup; the original Git index and overlapping working files were privately
copied before edits.

## Exact changed implementation and verification files

| Repository path | Purpose |
| --- | --- |
| `FraudLens-2.0-Backend/src/photo_admission.py` | Four/six slots; local slot-aware classifier, decode/normalise/hash, OCR quality, bound cache, shared warmup and inference semaphore |
| `FraudLens-2.0-Backend/src/api.py` | Authenticated prevalidation; final all-file admission before atomic persistence; committed-receipt replay; rate bucket and opted-in warmup |
| `FraudLens-2.0-Frontend/src/experience/photoSlots.ts` | Explicit claims and preserved underwriting labels/instructions |
| `FraudLens-2.0-Frontend/src/experience/Intake.tsx` | Slot previews/progress/reasons/recheck/remove, exact counts, stale-response invalidation and combined form readiness |
| `FraudLens-2.0-Frontend/src/experience/shared.tsx` | Paired slot/image multipart values and structured final error details only; unrelated transport edits preserved |
| `FraudLens-2.0-Backend/test_photo_admission.py` | Controlled deterministic admission, cache, outage, MIME/decode/orientation, counts, duplicates, OCR and receipt tests |
| `FraudLens-2.0-Backend/test_pilot_workflow.py` | Genuine four/six-file initial fixtures and unchanged workflow intent |
| `FraudLens-2.0-Backend/test_customer_workflow.py` | Owned submissions use the new contract; one supplement follows four initial photos |
| `FraudLens-2.0-Backend/test_durable_pilot.py` | Valid initial fixtures for retries/history/caches; preserve original run evidence and supplement counts |
| `FraudLens-2.0-Backend/test_postgres.py` | Controlled gate fixtures and four-file concurrency/uncertain-commit assertions in disposable schemas |
| `FraudLens-2.0-Backend/scripts/verify_photo_admission_local.py` | Actual local classifier smoke, warm throughput and optional complete warmup measurement; no provider calls |
| `FraudLens-2.0-Backend/scripts/verify_photo_admission_browser.py` | Completely intercepted API fixtures, desktop/touch/keyboard/stale-response checks and labelled screenshots |
| `docs/PHOTO_ADMISSION.md` | Slot/API contract, policy, limitations, commands and measured latency |
| `docs/PHOTO_ADMISSION_HANDOVER.md` | This implementation and verification record |
| `docs/photo_admission/*` | Sanitized local results, controlled timing/browser records and fixture-labelled screenshots |
| `ANALYSIS_REPAIR_HANDOVER.md` | Pointer to this current admission handover |

## Verification record

Verification uses three explicitly different kinds of evidence: controlled
semantic model fixtures for actual API transactions, intercepted browser API
fixtures for UI state, and native CPU CLIP smoke images for classifier behavior.
None establishes live Gemini underwriting or perfect image classification.
Final check results are recorded alongside the published artifacts:

| Check | Result |
| --- | --- |
| Admission tests plus customer supplementary-evidence regression | 43 passed, 368.17 s |
| Pilot/customer/durable-worker/report regressions | 85 passed, 774.27 s |
| Focused real PostgreSQL recovery/concurrency regressions | 5 passed, 76.48 s |
| Frontend `npm run typecheck` | Passed on final source |
| Frontend `npm run build` | Passed; rebuilt forms exercised in browser |
| Intercepted browser fixtures | Both case types at 1365/390 px; touch, keyboard, stale replies, exact counts and preserved fields passed |
| Full local validator warmup | 131.487 s, CLIP/texts/OCR ready in a new process; Python/API startup excluded, OS caches may be warm |

The standalone v2 smoke measured CLIP readiness at 293.195 s under different
load. These are separate observations, not a startup guarantee. An overlapping
warmup measurement was cancelled to reduce memory contention, then repeated
separately. No timeout was increased. The full native warmup is successful;
complete native four/six-slot acceptance remains unverified without appropriate
real plate/dashboard photos. Controlled persistence timing is in
`docs/photo_admission/controlled-timings.json`.

Zero generation requests; the original provider ledger still records 15 attempts.
Its original history prefix, normal-operation mode and closed task grant remain
intact. No normal worker was started. No push or deployment was performed.

Five actual PostgreSQL regressions passed in disposable schemas (76.48 s), covering
focused acceptance/idempotency/concurrency and before/after-commit recovery paths.
No pilot schema was used for fixture writes. Existing ordinary-test network
isolation remained enabled; no live opt-in was passed.

Representative screenshots explicitly say CONTROLLED BROWSER FIXTURE. The
placeholder images in them are not accepted by the actual model; the semantic
response is simulated to isolate UI behavior. Native smoke results report the
genuine-photo false retakes and missing plate/odometer positives plainly.

## Operations and rollback

Existing pilot startup commands and provider controls are unchanged. This task
did not start an API or worker, process queued jobs, enable generation or alter
the ledger. The temporary frontend used for browser verification is stopped at
handover. Restart an existing API to load the changed admission implementation;
rebuild/restart the frontend together, since old forms lack required slot IDs.

For rollback, revert this focused commit after reconciling any later edits and
rebuild/restart both services. Do not restore an older provider ledger or delete
accepted evidence. Earlier cases/reports/decisions need no data rollback.

Next evidence work: evaluate legitimate mounted plates and labelled dashboard
photos, more tight damage crops, unsupported heavy vehicles, cropped screenshots
and broader exterior conditions. Use held-out images before changing thresholds.
The absence of those real positives is a verification limitation, not permission
to bypass OCR or accept uncertain content. Six-view live underwriting remains
deferred, as requested.
