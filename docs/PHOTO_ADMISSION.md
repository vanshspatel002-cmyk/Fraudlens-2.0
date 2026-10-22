# Initial photograph admission

Inspected on 22 October 2026, branch `repair/analysis-pipeline-20261020`, starting
commit `d8bb8a741c86c885070b158b01d1a71faaa7d471`. Existing staged documentation
and unrelated frontend/API transport edits were preserved. No dependencies were
added. This policy applies to new initial applications, not historical records
or supplementary-evidence requests.

## Required photographs

Each row needs one distinct accepted photograph. The `photo_slots` multipart
values must accompany `images` in the same order. Extra, unknown, repeated and
missing slots fail the whole initial submission.

| Case | Slot identifier | Customer label / capture guidance |
| --- | --- | --- |
| Claims | `vehicle_overview` | Vehicle overview: whole passenger vehicle from a corner |
| Claims | `front_registration` | Front registration view: readable mounted plate and surrounding bodywork |
| Claims | `damage_overview` | Damage overview: affected area and neighbouring vehicle panels |
| Claims | `damage_closeup` | Damage close-up: recognisable damaged vehicle part; whole car unnecessary |
| Underwriting | `front_left` | Front left |
| Underwriting | `front_right` | Front right |
| Underwriting | `rear_left` | Rear left |
| Underwriting | `rear_right` | Rear right |
| Underwriting | `odometer` | Odometer: readable mileage with ODO/km/miles label and dashboard context |
| Underwriting | `registration_plate` | Registration plate: readable mounted plate and bodywork |

Underwriting retains the existing six view labels. The four exterior labels
remain applicant declarations: this classifier does not verify camera angle or
same-vehicle identity. Passing admission proves neither ownership, authenticity,
current condition nor capture date. Missing EXIF does not fail admission.

## Local classifier and honest uncertainty

`src/photo_admission.py` reuses the existing `vehicle_gate._default_embedder`:
CPU CLIP ViT-B-32 / `laion2b_s34b_b79k`. One process-local model instance serves
all slots. Positive prompts distinguish passenger exteriors, vehicle damage,
mounted plates and dashboards. Competing prompts cover motorcycles, heavy
vehicles, people, animals, food, scenery, documents, screens and unrelated objects.
There is no Gemini request in upload admission.

Policy `initial-photo-admission-2026-10-22-v2` requires the best positive cosine
similarity to reach the existing **0.175** floor and exceed the best competing
similarity by **0.020**. These are similarity measurements, not probabilities.
The original broad gate's negative margin allowance is not used by new initial
admission. A competing category ahead by more than 0.020 produces `rejected`;
other insufficient evidence produces `needs_replacement`. Neither can submit.

The margin is a conservative abstention operating point, not calibrated accuracy.
The first local argmax-only experiment incorrectly admitted the printed-car
document (margin 0.00362) and heavily blurred car (0.01875). Requiring 0.020
withheld both on the repeat smoke test. This small development set is not an
independent evaluation set; three of six genuine exteriors also needed retakes.
Do not loosen the policy simply to make a submission succeed.

Plate/dashboard candidates additionally use the existing shared EasyOCR reader.
Plates must produce a recognisable Indian-registration pattern using the existing
observed-prefix parser. Mileage needs a labelled ODO/mileage number or a multi-digit
km/miles reading; speed/RPM and unlabelled numbers do not establish mileage.
Unreadable content requests a retake. These heuristics do not verify registration
ownership or the true mileage. Unsupported formats may need replacement. OCR
unavailability returns a retryable service error, never silent acceptance.

No suitable legitimate mounted-plate or odometer positive fixture was located.
Their parsing, unreadable-state and endpoint behavior have controlled verification,
but real positive recognition remains unverified. Trucks/buses are competing
categories but had no dedicated real smoke image. The damage set includes vehicle
damage crops; an independent tightly cropped part-only evaluation is still needed.
Printed-photo/screen rejection remains heuristic; a cropped screenshot can evade
CLIP. A successful gate is not image-authenticity verification.

## File safety, duplicate protection and model reuse

Every image must be nonempty, at most 5 MiB, actually decode as JPEG/PNG/WebP,
match its declared MIME, have both dimensions at least 64 pixels, and contain at
most 25 megapixels. Exact solid blanks fail. EXIF orientation is applied before
RGB inference and duplicate hashing. The hash includes oriented dimensions and
pixels. Original bytes and EXIF are preserved for downstream analysis.

Exact normalised duplicate content cannot satisfy two slots. Metadata-only
changes do not evade that rule. Recompressed near duplicates are not guaranteed
pixel-identical; embedding similarity alone does not reject legitimate angles.

Cache keys bind customer identity, a non-exported session digest, case type,
slot, original-byte SHA-256 and policy version. In-memory entries expire after
600 seconds; at most 256 are retained. Final submission decodes/checks MIME again
and reuses only a compatible entry. Changed bytes/session/slot/version, eviction,
expiry, another process or restart require revalidation. Client `valid=true`
and returned hashes are never authority. Full warmup prepares all slot text
embeddings and the existing OCR reader. A process-local semaphore permits one
inference at a time; busy inference returns 503. Multiple API processes still
have their own model/cache; no cross-process cache is claimed.

## API and acceptance transaction

| Method / path | Contract |
| --- | --- |
| `POST /v1/photos/validate` | Customer Bearer session required; multipart `agent_type`, `slot`, `image`; no case/job/receipt creation |
| `POST /v1/cases` | Existing form fields plus exactly four/six `images` and corresponding `photo_slots`; server enforces every admission rule |
| `POST /v1/cases/{case_id}/evidence` | Existing authorised supplementary-evidence contract, one to twelve files; initial counts do not apply |

Prevalidation returns `slot`, `state`, `accepted`, `reason`, `validation_version`,
content/normalised hashes, similarity/quality measurements where available, and
`cached`. State is `accepted`, `rejected`, or `needs_replacement`; frontend adds
`checking`. Accepted classification is not an assessment or fraud result.

Malformed files/slots return 422. Final semantic/duplicate failures return
`PHOTO_ADMISSION_FAILED` with `details: [{field: slot_id, reason: ...}]`.
Unavailable/busy models return 503 `VALIDATOR_UNAVAILABLE`, with slot details.
Existing rate limiting gives prevalidation a separate 30 requests/minute/IP
bucket; intake retains its existing smaller limit. A 429 requires waiting,
not bypassing the gate. Cache use never bypasses size/content checks.

Database transactions are rolled back before expensive inference. Every file is
checked before entering existing atomic case/image/ownership/job/receipt creation.
Any rejected batch creates none of these records. Inference embeddings are reused
by ingestion. Existing upload cleanup, durable queue and uncertain-commit
reconciliation remain in place. A matching already-committed idempotent receipt
returns its original response without inference; legacy replay may omit slots.
A changed request using the same key still conflicts. This exception cannot
create a new under-count application.

The initial endpoint retains existing optional-customer authentication for
legacy API clients; anonymous clients receive no authenticated prevalidation
cache and must satisfy the full server gate. Browser forms require customer
login. Existing ownership controls on later case access are unchanged.

## Frontend behavior

`Intake.tsx` renders four/six explicit slots with wrapping instructions, preview,
filename, live text state/reason, replace, recheck and remove controls. Accepted
progress is separate from form validity. Submit requires every required slot
accepted and all required form fields valid. Replacing a locally invalid file
rechecks form readiness as well as image admission.

Prevalidation is serialised so selecting six files does not load six models.
Each slot has a revision counter: replacement, removal and unmount invalidate
older responses. Removed preview URLs are revoked. Rejections retain all other
files and entered fields. Final server slot errors mark affected slots unresolved
without clearing the form. Changing case type uses the route's own slot set.

## Verification and measurements

The evidence files and screenshots are in [photo_admission](photo_admission/README.md).
Endpoint/browser tests use explicitly controlled semantic responses; they do not
establish that placeholder pixels are vehicles or that Gemini processing works.

Real local v2 smoke: **3/6** genuine exteriors accepted, **3/6** requested retakes;
**4/4** damage photographs accepted; **7/7** packaged real negatives rejected
(person, animal, food, scenery, motorcycle, document, unrelated object). Authored
blur, printed-car document and screenshot controls needed replacement. Blank,
tiny and corrupt controls failed decoding/quality. No plate/dashboard native
positive, complete native four/six-slot acceptance, or same-vehicle set was verified.

| Measurement | Observed basis |
| --- | --- |
| Cold CLIP readiness | 293.195 s in the recorded v2 process; full OCR readiness measured separately |
| Full validator warmup | 131.487 s in a separate fresh process: shared CLIP, all slot texts and OCR ready; excludes Python/API startup and may benefit from OS file cache |
| Warm exterior validation | about 0.50–0.63 s per ordinary photo in that run |
| Warm four-image inference | 2.274 s, heterogeneous generic exterior inputs, not a complete claims set |
| Warm six-image inference | 3.203 s, heterogeneous generic exterior inputs, not underwriting acceptance |
| Durable acceptance | Claims 0.892 s; underwriting 0.380 s: actual isolated SQLite transaction, controlled semantic model, all prevalidated entries reused with zero final model calls; not native full-slot acceptance timings |

Cold starts are a material local limitation, affected by dependency/model loading
and available memory. Timings are observations, not service guarantees. No timeout
was increased. Full warmup results, final test counts and frontend checks are in
the handover; `/ready` still checks its existing DB/storage dependencies and does
not certify OCR readiness.

## Running and repeatable checks

From the backend directory, these run isolated tests/local models only:

```powershell
.\venv\Scripts\python.exe -m pytest test_photo_admission.py -q
.\venv\Scripts\python.exe -m pytest test_pilot_workflow.py test_customer_workflow.py test_durable_pilot.py test_report_pdf.py -q
.\venv\Scripts\python.exe scripts/verify_photo_admission_local.py
.\venv\Scripts\python.exe scripts/verify_photo_admission_local.py --warmup-only
```

PostgreSQL regressions require explicit `FRAUDLENS_TEST_POSTGRES=1` and create
their own disposable schema. Do not point fixture writes at the pilot schema.
Ordinary pytest blocks external model HTTP even when a key exists.

For normal operation, the existing `scripts/start_pilot.ps1 -Database postgresql`
loads the pilot API configuration on `http://127.0.0.1:8001` and warms local models.
Its existing separate-worker command uses `-WorkerOnly`. Starting a normal worker
can process genuine queued jobs; this task did not start it. Model caches must
already exist when using the launcher's offline settings.

From the frontend directory, `npm run typecheck`, `npm run build`, and
`npm run dev` (local port 5173) retain their existing roles. Browser fixture
verification expects frontend port 5173 and intercepts **all** API requests:
run `scripts/verify_photo_admission_browser.py` with the backend Python.
The tested pages are `/apply/claims` and `/apply/underwriting`.

Underwriting live AI validation remains deferred. This change validates initial
upload requirements and admission behavior; it does not improve or establish
analysis accuracy.
