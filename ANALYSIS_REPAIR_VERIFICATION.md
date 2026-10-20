# Analysis repair verification — 20 October 2026

This record distinguishes controlled fixtures from actual PostgreSQL, browser,
installed SDK and live provider execution. Overlapping test runs are not summed.
Final live claims/underwriting AI validation is blocked. The retained claims
vision request returned a real HTTP 503 and closed the audited recovery;
successful live underwriting analysis has not been demonstrated. The 21 October
read-only saved-state verification emitted a blocked audit and no validation
proof, with zero model requests and zero database writes.

| Verification | Recorded outcome | Boundary |
| --- | --- | --- |
| Initial provider recovery/control tests | 9 passed | Temporary ledgers and controlled transport; no external call |
| Recovery + SDK serialization/profile checks | 12 passed, 24 deselected | Controlled HTTP transport, real SDK serialization |
| Final recovery/scoring/PDF/batch regression | 38 passed, 390.72 s | Isolated SQLite/temporary controls; real PDF rendering; before the final extra report-basis boundary test |
| Snapshot basis idempotence | 1 passed, 12 deselected, 31.05 s | Unrelated corpus changes preserve PDF bytes; human/run/template changes create new versions |
| Exact baseline threshold/rounding provenance | 8 passed, 20 deselected, 38.28 s | Below/exact 0.3 and 1.0, sequential floating-point addition, mismatch detection, real PDF text; no policy change |
| Initial engine contracts | 23 passed | Controlled model/check fixtures, installed unsigned-image C2PA verifier |
| Legacy agent runner | 16 passed, 0 failed | Offline; no provider request |
| Final engine + affected durable variants | 36 passed, 93.09 s | 27 engine contracts plus nine affected durable variants, fresh imports |
| Actual PostgreSQL engine qualification | 2 passed, 104 deselected, 67.14 s | Newly allocated/dropped isolated schema; temporal matching, fencing, diagnostics, explanation and transaction release |
| Frontend Node 22 typecheck and production build | Passed | Frozen source hashes and build log retained privately |
| Production browser layout/role/action regression | 7 grouped checks passed; zero JS errors | Clearly marked fictional HTTP fixtures, both types at 1365/768/390 px, current/history PDFs, all four action payloads, legacy/partial/failure and human-basis states |
| One real audited recovery probe | Success, one uncached request, 20.718 s | Normal Gemini adapter; no retries/rotation; model alias 3.5 served by 3.6; original session attempts 2→3 |
| Qualified original-corpus audit | 822 cases, 1,465 valid evidence references, 130 compatible perception rows | Repeatable-read PostgreSQL inventory, filesystem hashing after transaction release |
| Original-row preservation before historical enqueueing | Passed, all 24 tables | Every original row still identical, including all 58 snapshots, PDF bytes, 911 decisions and 27 human actions |
| Full historical dry run | Refused enqueueing; all 822 budget-deferred | Minimum 2,060 requests versus 11 authorized at planning boundary; no database/provider writes |

The first broad post-edit regression recorded 96 passed / 6 failed; the failures
were stale mock signatures and raw-only fake perception records that the stricter
guard correctly rejected. A concurrent older-import durable run later recorded
39 unaffected passes and nine mixed-import failures. The final fresh-process
36-test qualification covers all nine affected variants and the final engine
contract; product guards were not weakened to accommodate old fixtures.

Known retained warnings: installed Starlette TestClient/httpx deprecation and
PyMuPDF SWIG deprecations; frontend Nitro/Vite compatibility warning. They do not
establish model accuracy or change the recorded exit codes.

Private controlled browser evidence:
`FraudLens-2.0-Frontend/.browser-check/admin-review-20261020` contains before
screenshots, final `frozen-build.log`/`frozen-source.json`, and the complete
`after-frozen-b/manifest.json` plus both-type screenshots at all three widths.
Earlier harness-only action-label and cold-load timeouts remain preserved and
are not counted as complete runs.

Controlled PDF fixtures exercised grouped six-photo claims and underwriting
reports; all pages were rasterized and inspected. Old eleven-page legacy stress
rendering was retained. Real-service sample reports and their all-page inspection
will be recorded separately after the PostgreSQL browser rehearsal.

Installed C2PA SDK qualification used the official `contentauth/c2pa-python`
repository's reference images pinned to commit
`df6b819bc223a1721d6e982a5de2e1b47219be8c`, without remote manifests or OCSP.
Unsigned A.jpg returned ManifestNotFound and INCONCLUSIVE. Signed C.jpg was
content-valid but untrusted, so remained INCONCLUSIVE. A decoding-valid one-bit
scan mutation produced `assertion.dataHash.mismatch` and CONCERN. Exact URLs,
hashes, settings and results are private in backend
`outputs/engine_recovery_20261020/c2pa_references/audit.json`.

Original provider controls/configuration, consistent backups and read-only
before/qualified audits are under
`D:\projects\FraudLens-2.0-preservation\pipeline-before-20261020T140930Z-85cf36`.
The successful initial probe is private at `live-probe/probe-result.json`; the actual
historical planning artifacts are under backend
`outputs/analysis_repair_20261020/batch-all822-dryrun`.

## Resumed verification — 21 October 2026

The accepted isolated claims case is `case-c69f94bd810d`, run
`08f9400e8cb144f3a1c6099d934f0c1a`. It retained 13 findings, its exact-run
assessment explanation and a nonconverged human-review fallback. At resumption,
the original ledger contained four requests: the two original HTTP 503 failures,
the successful recovery probe, then this claim's HTTP 503. The audited recovery
is failed. Although eleven lifetime slots remain numerically, **zero additional
provider requests are currently authorized**. A quota-day reset does not reopen
the circuit or authorize a new probe.

The saved-state audit is private at backend
`outputs/analysis_repair_20261021/blocked-verification/audit.json`. It verifies
the failed exact claims run and absence of accepted underwriting at that
boundary. It deliberately contains no `live-validation.json`. Historical
enqueueing remains gated; neither a passing fixture nor an explicit human
decision can satisfy the live AI gate.

Resumption also repaired parallel tool-call transport, fail-closed validation of
structurally malformed session/quota ledgers, and severity ordering across UTC
offsets. The retrospective gate now checks the current recovery authorization
and each distinct successful vision/adjudication request in that recovery.
The browser harness can explicitly verify partial reports/manual review with
`--allow-incomplete`; its manifest separately records `live_ai_complete=false`.
Its default still stops after incomplete model processing.

| Resumption check | Outcome | Boundary |
| --- | --- | --- |
| Engine/recovery/legacy LLM pytest | 68 passed, 7 skipped, 5.71 s | `FRAUDLENS_TEST_LIVE=0`; seven live-dependent tests skipped; controlled transport/temporary controls |
| Legacy agent runner | 16 passed, zero failed | Explicit offline runner |
| Saved-state verifier + retrospective gate | 45 passed, 53.67 s | Controlled records, no provider/database requests |
| UTC-offset damage chronology | 3 passed, 12.08 s | Disposable SQLite, synthetic observations |
| PDF/explanation/durable regression | 76 passed, 522.65 s | Isolated SQLite, real PDF rendering; six retained deprecation warnings |
| Node 22 production build including typecheck | Passed, exit 0 | Current product sources match the earlier successful seven-group browser fixture hashes |
| Original PostgreSQL row preservation | All 24 tables unchanged | 822 cases, 1,465 images, all original findings/decisions/snapshots/PDFs; read-only audit |
| v3 pagination / template regression | 3 passed, 12 deselected, 39.14 s | Targeted rerun after the heading correction; historical v2 dispatch retained |

These runs are recorded separately from earlier overlapping tests. The final
report/durable log is `outputs/analysis_repair_20261021/final-report-durable-regression.log`;
the original-row audit is `original-row-preservation.json` in the same directory.

One resumption verification command mistakenly collected the legacy live LLM
tests through pytest before their custom-runner-only guard was recognized. One
uncached Gemini request returned a nonempty response using a temporary test quota
ledger and temporary SQLite database. The process was interrupted; one transport
reservation is retained and no second request is recorded. Serving version and
response text were not retained, and this is **not** claims/underwriting proof.
The original application control hashes and database were unchanged. A permanent
test-level opt-in guard now prevents live tests from executing under either
runner unless `FRAUDLENS_TEST_LIVE=1` is explicitly set. Private audit:
`outputs/analysis_repair_20261021/accidental-test-transport-audit.json`.

## Completed real partial-report rehearsal

The resumed two-tab Chrome rehearsal finished with exit 0, 15 recorded
observations and zero application JavaScript errors. It used actual PostgreSQL,
API, worker, original photographs and saved reports, with no HTTP/model mocks.
Its manifest explicitly records `live_ai_complete=false`. Claims approval and
underwriting rejection are explicit human decisions following failed processing;
they do not change operational status or assert a successful model assessment.

| Isolated case | Processing / human outcome | Server acceptance | Persisted worker duration |
| --- | --- | ---: | ---: |
| `case-c69f94bd810d` — claims | Failed / approved manually | 5.633 s | 137.526 s |
| `case-5beba174962a` — underwriting | Failed / rejected manually | 199.426 s | 170.511 s |

Acceptance is measured by server middleware; worker duration is terminal
`updated_at` minus `started_at`. Neither is a browser polling wait. Underwriting
admission included cold local CLIP startup after deliberately using `-NoWarmup`.
It exceeded the existing 180-second browser response wait. The case was actually
accepted, so its exact stored submission receipt was recovered read-only into
the private checkpoint, with no replacement submission. The normal documented
startup warms admission models before the server accepts applications. Timeouts
were not increased to hide the cold start.

Claims reused its original failed HTTP 503 run. Underwriting respected the
persisted circuit stop and made no provider request. Both original control
SHA-256 hashes remain identical and the application ledger remains at four
attempts. Both workflows have exact-run saved explanations, null production
scores, attributed human review bases and preserved evidence. The final
read-only live verifier still emits **only a blocked audit**, at
`outputs/analysis_repair_20261021/blocked-verification-final/audit.json`.

The full rehearsal's four v2 before/after PDFs contain 17 pages in total. All
pages were rasterized and visually inspected; there are zero text spans outside
page bounds. A cosmetic orphan photograph heading led to a v3 template revision.
The original v2 PDFs and exact v2 text/font/coordinate rendering are preserved.
The subsequent targeted browser check fetched v3 claims (four pages) and
underwriting (five pages) PDFs; all nine pages were inspected with no clipping,
overlap or orphan photograph heading. For every downloaded PDF the actual
preview blob, browser download and authenticated private API bytes matched.

Private evidence:

- `outputs/analysis_repair_20261020/pg-real-a/browser/manifest.json`: completed
  resumed workflow, outcomes, responsive screenshots and four v2 downloads.
- `outputs/analysis_repair_20261021/v3-browser/browser/manifest.json`: current-PDF
  browser regression, zero JavaScript errors, no additional cases or decisions.
- `outputs/analysis_repair_20261021/pdf-inspection/`: preserved v2 artifacts,
  all-page renders, `v3-layout-comparison.json` and
  `v3-current-inspection-result.json`.
- `outputs/analysis_repair_20261021/final-local-audit.json`: **41/41 checks
  passed**, covering all seven evidence hashes, six PDFs against database bytes,
  exact human-review/run bases, null production scores, no active jobs, original
  controls and every original row in all 24 pilot tables. Its repeatable private
  script is `final_local_audit.py`; the audit made zero API/model requests and
  zero database writes.

The initial Chrome launch exit was resolved with headless GPU acceleration
disabled. A test-only fetch of a blob URL was blocked by the real browser CSP;
the harness now observes/hashes the genuine preview Blob when its object URL is
created, without weakening the policy or intercepting any network response.
Failed attempts are retained in their private logs and are not counted as
successful rehearsals.

The final normal-runtime check is private at
`outputs/analysis_repair_20261021/runtime-final.json`: original `fraudlens_pilot`,
822 cases, 1,465 images, zero queued/running jobs, API health/readiness and both
dashboard routes HTTP 200, completed admission/OCR warmup, dedicated worker
leadership present, and unchanged provider control hashes. Provider reachability
was left unverified; no readiness/health probe spent a model request.
