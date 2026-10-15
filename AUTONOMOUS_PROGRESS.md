# Autonomous continuation — 15 October 2026

## Final PostgreSQL qualification

The local pilot is qualified on Supabase PostgreSQL at API port 8002, with the
existing frontend on 5173 and a separate local durable worker. Claims completed
across rehearsal 3 and its review continuation; underwriting completed its full
rehearsal. Both used actual uploads/HTTP/Chrome and existing stock photographs.
They verified validation, acceptance, queue/status, evidence, findings, trace,
secure requested evidence, controlled reprocessing, immutable report history,
human decisions and public tracking. Claims PDF: 9 pages/11,129 characters;
underwriting PDF: 22 pages/33,015. Continuation/underwriting runs also verified
logout, exact-session expiry, 390 px layout and zero JavaScript errors.

Final suites: **241 backend/SQLite passes, 0 failures, 10 intentional skips**;
**72 PostgreSQL passes plus 1 later external-worker regression pass, 0 failures,
0 skips**. The 241 include one integration flow. Repeated earlier runs are not
added to these totals. Offline model stubs are not proof of live AI reliability.
Frontend standalone type-check and final production build passed
(`frontend-refresh-typecheck.log`, `frontend-build-qualified.log`).

Post-rehearsal PostgreSQL: **816 cases, 1,443 images, 14,453 findings, 901 agent
decisions, 23 run results and 39 immutable reports**. All 23 jobs truthfully have
failed analysis; none is incorrectly marked completed. Four fictional submissions
were added: two retained from earlier failed UI rehearsals and the two completed
workflow demonstrations. Every one of 1,443 image paths and SHA-256 hashes passed;
there were zero missing/mismatched/unreferenced upload files. All 22 tables retain
RLS and no anonymous/authenticated browser privileges. Client TLS is active.

The selected 812-case SQLite boundary and all four research databases retain
every application row and schema. Eighteen original ablation/quota/performance/
threshold artifacts matched preservation. No research policy/check weight or
threshold changed. Local source commits: `81cfe49`, `79852be`, `f480874`,
`ce61f57`; final documentation/default-startup changes are committed separately.
No credentials, private data or backups were staged; no push/deployment occurred.

**Live AI remains blocked:** zero additional Gemini requests during migration;
the same two prior real vision requests failed HTTP 503 and the persistent stop
is intact. Browser analysis shows disclosed fallback, followed by explicitly
fictional human reviews. Detection accuracy and successful new live adjudication
are not established. Manual Chrome/OS print dialogs, screen readers and complete
frontend threat coverage remain unverified.

Production work remains: full tenant isolation, verified applicant identity/MFA/
recovery, a least-privilege database service login, shared/private evidence storage,
distributed provider/rate budgets, supervised services/central monitoring,
security/load/privacy review, full project/PITR backup procedures and independent
model/detection validation. This is one local organization, not production SaaS.

Final preservation: private `20261015-postgresql-qualified` logical backup
restored into new `fraudlens_restore_qualified_20261015`, with every application
row/ordering ID matched, zero run-reference issues and private grants/RLS intact.
Filesystem backup `20261015-qualified-files` contains **5,134 files**; frontend
configuration is separately preserved in `20261015-frontend-config`. Existing
backup destinations and original data were never replaced. A reimport attempt
against the now-expanded pilot correctly refused (exit 1) without changing data.
Migration validation is a frozen-source comparison, not an instruction to merge
new PostgreSQL submissions back into SQLite. No disposable test schema remains.

Final HTTP smoke after the production build/dev restart passed frontend `/admin`,
API readiness, anonymous private-route denial, both public trackers' final human
status and field privacy, and the external worker's database leadership. There
are zero queued/running jobs. The live ledger's bytes match initial preservation;
no additional provider request occurred. The final public-build scan checked
18 artifacts and found no configured secret values. Installed `pip check` passed.

## Earlier migration observations, in order

## PostgreSQL migration continuation — 15 October 2026

Work continues on `migration/supabase-postgresql-20261015`, from clean `38ca5ac`.
The audit, handover/runbook/matrix and repository instructions were inspected.
No applicable AGENTS file was found. The original port-8000 service remains
untouched; the isolated SQLite pilot was stopped for a consistent preservation
boundary. Private backup `20261015-before-postgresql` contains 5,038 files.

Implemented the optional PostgreSQL DB-API bridge, bounded connection pool,
versioned private schema, explicit import/dry-run/validation, logical backup and
new-schema restore, cluster job leadership, SKIP LOCKED claiming, case/key locks,
stale-worker fencing and dialect-specific check/report SQL. Existing authentication,
applicant receipts, contracts, file paths, policies and research datasets remain.
The full scope and exact Windows rollback are in [POSTGRES_MIGRATION.md](POSTGRES_MIGRATION.md).

The selected 812-case SQLite demo was imported into new `fraudlens_pilot` only.
Every application row/column/ordering ID matched, with 1,432 images, 895 agent
decisions, 17 run records and 29 report snapshots. All image paths resolve;
all historical reports parse. Source integrity/FKs and target run references
passed. All 22 target tables have RLS enabled and no anonymous/authenticated
browser grants. Client TLS was verified through libpq; pg_stat_ssl behind the
pooler describes its separate backend hop and is not the client TLS measurement.

Initial import comparison failed due to shorter floating-point serialization;
its new schema rolled back. Explicit binary64 types/float output fixed it, and
both the second import and independent read-only validation passed. Logical
backup `20261015-postgresql-before-workflows` restored and fully verified in
`fraudlens_restore_20261015a`. No source/target data was overwritten or merged.

Five storage-sensitive checks matched SQLite on ten selected representatives in
the restored copy, using recorded evidence with zero provider calls. This is
execution equivalence, not independent detection accuracy. SQLite's focused
workflow suite passed 54/54; later batching checks passed 5/5. The full offline
release rerun passed **241, failed 0, skipped 10**, using the correct runners.
Frontend standalone type-check and production build passed. The PostgreSQL
suite is still completing; later heartbeat/recovery/resource regressions passed
4/4 on the latest code. An initial slow
PostgreSQL test run was interrupted to reload the optimized implementation;
no final pass count is asserted for it, and only its generated test schema was
removed. A subsequent PostgreSQL run reported **46 passed, 1 failed, 1 setup/
cleanup error** when a connection disappeared. Its log is retained. A focused
run on the prior implementation was stopped after one failed case and four
setup errors. Fixes add borrow-time connection checks, bounded idle transactions,
safe rollback, monotonic recovery epochs, heartbeat leadership and attempt
fencing. COMMIT acknowledgement loss now preserves files; focused tests inject
actual connection loss before/after commit and verify replay/history safety.
The next PostgreSQL run passed **68/68**, and four later heartbeat/resource
regressions passed. Chrome then exposed a latency regression: one claim was
accepted, but overlapping ten-second refreshes kept the reviewer queue loading
until its 45-second harness timeout. That submission remains preserved. Cloud
round trips now use psycopg pipelining with transaction-local settings; frontend
queue/detail refreshes wait for their preceding request, pause queue polling in
a case and debounce search. The worker's default heartbeat-protected idle limit
is now 120 seconds to tolerate cold Windows imports (tests use a shortened limit).
The latest 72-test PostgreSQL rerun and a new Chrome rehearsal are continuing.
The updated frontend passed type-check/build after correcting the browser timer
type. The qualification backend is on 8002; pilot promotion remains pending.

A second Chrome rehearsal again accepted a claim but encountered long API stalls
during cold native check work. Both cases remain. The local pilot now runs the
same durable worker/pipeline in a dedicated process, with OCR warmup before
leadership; the API uses `-NoWorker`, and another terminal uses `-WorkerOnly`.
An actual PostgreSQL regression verified that operations can observe this
external database leader (**1 passed**). This changes the execution boundary,
not checks, model responses, storage or frontend contracts. Browser qualification
continues after the dedicated worker warms. The earlier failures are retained
in `browser-run1.log` and `browser-run2.log`.

The final pipelined PostgreSQL suite completed **72 passed, 0 failed, 0 skipped**;
the separate external-leader test adds one pass. Corrected frontend type-check
and production build passed (`frontend-*-final2.log`). During dedicated worker
startup, three actual API readiness requests returned 200 in 3.328, 2.312 and
1.625 seconds. Chrome rehearsal 3 accepted a claim and opened its reviewer case;
remaining workflow steps are still running. No provider success is inferred.

Read-only full comparisons confirmed every application row and schema unchanged
in the four research DBs and selected SQLite demo. Eighteen ablation/quota/
performance/threshold artifacts matched their preserved hashes. The explicit
SQLite rollback served actual HTTP readiness, individual login, queue, report
and logout on temporary port 8003, then was stopped. No data was reverse-merged.

Claims qualification completed across Chrome rehearsal 3 and its continuation.
Observed: actual acceptance, queue/detail, accurate failed/fallback status,
13 findings, 640 px evidence, trace, readable 9-page/11,129-character PDF,
specific evidence request, receipt-authorized supplement, original preservation,
run-specific reprocessing, saved report and Escape dismissal, human decision,
public tracking, logout, exact-session expiry and 390 px mobile layout.
The continuation reported zero JavaScript errors. An automatic/manual refresh
race had left the decision control loading; a focused UI fix now prevents a
background request from invalidating manual loading state. The existing case
was resumed without another upload or processing job. Earlier failure logs remain.

Underwriting qualification is running independently with six genuine existing
stock photographs, without claiming they show six views of one vehicle. It has
passed required-field validation and actual six-photo acceptance. The local
pilot remains in qualification until the remaining underwriting steps complete.

Gemini usage is unchanged: **2 actual requests total**, both prior HTTP 503
failures; the original persistent stop remains. No successful new live vision
or agent adjudication is claimed. Current session outputs are private under
`outputs/pilot_validation/postgres/`. Earlier evidence below remains historical.

Branch: `autonomous-pilot-hardening-20261014`. Inherited implementation/audit preserved in `09d06e8`. No push, external deployment, paid service or credential commit. No applicable repository/parent/source `AGENTS.md` was found. The existing architecture, branding, corpus, historical policies and evaluation outputs were retained.

## Completed implementation

- Transactional submission, unique evidence storage, duplicate/type/size checks, receipt-protected jobs, UUID4 idempotency and rollback that never removes a preexisting directory.
- Specific evidence requests, case-scoped 30-day applicant receipts, validated/audited supplementary photographs, original preservation, request closure and controlled reprocessing.
- Persisted queued/running/completed/failed/interrupted jobs, partial unique active-job index, Windows worker exclusion, three-attempt restart recovery and failure-safe accepted evidence.
- Current-run finding/decision/trace/evidence selection, immutable report snapshots and explicit legacy limitations. New human actions record their reviewed run/decision/evidence/status; earlier actions are identified as history.
- Individual PBKDF2 admin/reviewer/viewer accounts, eight-hour revocable sessions, expiry/logout/disable/credential rotation, server attribution, service-versus-human permissions and protected private routes. One local organization is supported; multi-tenancy is not implemented.
- Shared persistent live-call cap and quota/repeated-failure stop, disabled hidden SDK retries, request-specific outcome attribution, legitimate cached-vision handling after a stop, and provider/image cleanup.
- Separate production policy versions v1/v2/v3: nonzero scenario integrations, corrected reliability/garage attribution, zero-weight findings made inconclusive, actual declarations preserved and unverified regulatory applicability disclosed. Research policies/weights/thresholds unchanged.
- Production raw OCR observation cache with case-specific identity recomparison and promptly released writer locks; SQL duplicate-pool counts avoid unnecessary embedding decoding. These preserve verdict rules. A separate real local OCR/cache execution was verified below.
- Existing frontend repaired for image mappings, finding categories, queue/status/risk/recommendation filters, asynchronous stale responses, session-expiry/logout state, full-resolution evidence, specific evidence uploads, report history and readable printing. Unsupported view-verification/legal/reliability claims were corrected.
- Readiness without provider calls, structured request/error/job information, authenticated operations/queue aging, private backup manifests and non-overwriting restore.

## Preservation evidence

Initial backup: `D:\projects\FraudLens-2.0-preservation\20261014T065436Z`. Four consistent SQLite backups passed integrity checks, with evidence/data/config/models/perception/research outputs and original patches/audit. Credentials remain outside Git; the Word lock file was preserved and ignored.

Final backup: `D:\projects\FraudLens-2.0-preservation\20261014-final-backup`; restore drill: `D:\projects\FraudLens-2.0-preservation\20261014-restore-drill`. **4,963 files** were copied and verified against the manifest; restored root/nested databases passed integrity checks. No original database/evidence directory was replaced. The drill verifies artifact integrity; stored evidence paths still need inspection/rebasing for relocation.

Latest handover backup: `D:\projects\FraudLens-2.0-preservation\20261014-handover-final`, **5,030 files**, including later demonstrations/verification artifacts. Only the generated demo reviewer password was subsequently rotated privately and prior sessions revoked; original credentials/configuration were untouched. Its current isolated DB/config/ledger/browser results are preserved in `20261014-post-rotation` alongside the earlier full evidence backup. No password was printed or committed.

Original database counts remained:

| Database | Cases | Images | Findings | Agent decisions | Perception |
|---|---:|---:|---:|---:|---:|
| Main | 800 | 1,395 | 13,839 | 878 | 130 |
| Scenarios | 800 | 1,395 | 13,350 | 841 | 130 |
| Ring | 800 | 1,395 | 13,803 | 876 | 130 |
| Repeat | 800 | 1,395 | 13,803 | 876 | 130 |

The original ablation report/JSONL, check-performance report and quota tracker matched preservation. A legacy mocked rotation test initially wrote two fake reservations to the original tracker; that changed tracker was archived at `outputs/pilot_validation/offline_rotation_quota_state.json` and the preserved original restored. It now uses temporary quota storage. Those reservations were not provider requests.

## Live integration: stopped

**2 actual Gemini requests / maximum 15**, both real vision HTTP **503** failures. No new successful vision or agent adjudication was observed. The persistent ledger `outputs/pilot_validation/live_calls.json` records two failures and a repeated-failure stop; all subsequent attempts were blocked before network access. It was not reset to consume the unused allowance. Original free-tier configuration/credentials were retained privately.

Representative successful live claims/underwriting vision and live agent adjudication remain blocked. Legitimate historical perception was reused; model failures/malformed evidence were never replaced with fabricated success. Mocks in offline tests are explicitly labeled and do not establish live reliability.

## Chrome verification

Installed headless Chrome **155.0.8059.41**, Playwright **1.64.0**, real frontend `127.0.0.1:5173` and isolated backend `127.0.0.1:8001`. Original port-8000 service was left untouched. No browser security bypass or network/model interception was used.

`browser_run13.log` verified both workflows using applicant/reviewer tabs: required-field validation, genuine existing-photo upload, immediate acceptance, queue/detail refresh, accurate terminal failed/fallback state, recorded findings, original-resolution viewing and Escape, trace/report views, PDF generation, specific requests, receipt-protected supplementary upload, preservation, saved-report dialog/keyboard dismissal, human approval of a fictional demonstration and public tracking. Claims used 1 original + 1 supplementary photo; underwriting used 6 original + 1 supplementary. Underwriting slots used distinct research photos, not validated views of one vehicle. Applicant tabs had no reviewer session.

Observed reports under production **v2**: claims **13 visible findings**, original width **640 px**, PDF **9 pages / 10,871 extracted characters**; underwriting **50 visible findings**, original width **490 px**, PDF **22 pages / 32,294 characters**. PDFs contained the correct case, declaration, findings and processing-run identification. The trace UI was checked in failure/fallback mode; successful model reasoning remains unverified.

That full-flow script failed after logout because its final mobile check passed `viewport` to an unsupported Playwright call. The call was corrected. `browser_post_review15.log` then passed logout, **expired session returning to login without reloading**, **390 px tracker without horizontal overflow**, and recorded **zero JavaScript errors for that continuation** (exit 0). Earlier failure records remain in the observation ledger. Full-run JavaScript-error aggregation was not reached after the mobile harness exception; no zero-error claim is made for the whole earlier script.

Earlier rehearsals exposed and repaired actual hydration/native-form, CORS, local CSP/blob-worker, image-mapping, hidden-finding category and logout-loading defects. Harness selectors/tab foregrounding were corrected separately. One underwriting run took about **364 seconds**, exceeding the old 300-second harness wait; it completed with evidence intact. Profiling confirmed CPU EasyOCR work. Harness wait is now 600 seconds. Late accepted cases from failed rehearsals remain in the isolated database.

Two attempted separate frontend launches on 5174 were rejected by automatic approval review as blocked by policy. Those commands were not bypassed; the standard authorized 5173 dev command succeeded after correcting its Vite/Nitro configuration.

Unverified: manual/visible Chrome and OS print dialogs, screen readers, all viewports/controls, genuine same-vehicle views, successful live agent traces and the latest v3 prompt/human-basis labels in a complete browser repeat. Final-source API regressions/type-check/build cover later changes; the v2 rehearsal is not presented as a live v3-model test.

Separate actual local OCR verification (`ocr-cache-release-final-verification.json`): one real reading **1.641 s**, same-image cache **0.015 s**, **0 provider calls**, identical INCONCLUSIVE results, zero plate observations, and a second connection obtained its writer lock. This verifies reuse and lock release, not OCR accuracy. Initial benchmark attempts exposed a legacy case-read compatibility regression and two helper-function naming errors; those logs/failed copies remain. Missing optional declaration columns now read as unknown without migrating originals; the model/database suite gained and passed a regression.

## Check and research verification

All **15 registered checks**, the retired vehicle check, all original workflow/archetype buckets and three injected scenario families are inventoried in [CHECK_VERIFICATION_MATRIX.md](CHECK_VERIFICATION_MATRIX.md). **367 case executions** on consistent copies of all four DBs produced **0 framework-caught check exceptions**. Inapplicable/missing/unsupported checks remained inconclusive. Uncached external lookups were intentionally disabled. Raw structured results are preserved privately.

Injected rule executions: ring members 18/18 concerned, six single-identifier controls inconclusive; baseline links 20/20 recent claims concerned, ten older controls PASS; eight oscillating sequences (24 constituent cases) concerned, monotone/repaired control sequences PASS. These are authored rule scenarios, not independent detection accuracy. A selected context mismatch was not detected; AI-generation/editing/signed-credential/plate accuracy remains uncovered.

Latest ablation remains incomplete: 58/99 eligible agent cases after 22 exclusions; existing integrity verifier verified 58/58 with no problems on a copy. Historical threshold result: 34/34 targets plus **91/410 clean claims** concerned, attributed to garage billing, never claimant guilt. No replacement threshold/zero-weight reactivation was adopted.

## Verification counts and environment

Python 3.12.8; installed `pip check` passed. Optional C2PA bindings/AI weights and usable OCR/vision coverage remain limited; successful suites include explicit inconclusive/unavailable handling. Node resolved 24.21.0/npm 11.19.0, outside the package's Node-22 engine. Fresh dependency installation was not rehearsed.

Earlier custom runners completed: models 81, baseline 14, agent 16, LLM 7 (+7 skipped), perception 2 (+3 skipped), ingest 6, checks 34, API 25 and one stubbed integration flow. Focused regressions last completed 49 passed before later cache/filter/human-basis additions. Intermediate genuine failures were fixed; they were not hidden or counted as final passes.

Final latest-suite counts: **241 passed, 0 failed, 10 skipped**. Correct custom runners, disabled live tests and isolated quota storage were used. The sequential release result is `outputs/pilot_validation/offline_release/results.json`; the later legacy-read regression rerun supersedes its models count (82 instead of 81) in `test_models_legacy_final.log`.

| Runner | Passed | Failed | Skipped |
|---|---:|---:|---:|
| `python test_models.py` (latest) | 82 | 0 | 0 |
| `python test_baseline.py` | 14 | 0 | 0 |
| `python test_agent.py` | 16 | 0 | 0 |
| `python test_llm.py` | 7 | 0 | 7 |
| `python test_perception.py` | 2 | 0 | 3 |
| `python test_ingest.py` | 6 | 0 | 0 |
| `python test_checks.py` | 34 | 0 | 0 |
| `python test_api.py` | 25 | 0 | 0 |
| `python scripts/verify_integration.py` | 1 flow | 0 | 0 |
| `pytest test_pilot_workflow.py test_durable_pilot.py` | 54 | 0 | 0 |

Skips: three live Gemini tests, three live Ollama tests, three live perception tests and one usage-stat test with no preceding live call. Optional missing C2PA/classifier coverage is disclosed as inconclusive behavior rather than asserted as functioning detection. The focused suite reports one Starlette/httpx deprecation warning; Torch quantization and pysolar dependency warnings also occurred.

The custom check sweep completed in 1,680 seconds: 35/35 authored REUSE cases concerned and 0/540 CLEAN cases concerned by internal duplicate. This does not establish independent accuracy. That process loaded the pre-optimization duplicate counter; the later SQL counter is covered by the final focused regression. Source secret-pattern scans and configured-value checks found no credential patterns, forbidden data/config candidates or private frontend values in built public JS; final staging is reviewed separately.

Frontend production build passed after type-checking (`frontend_build_release4.log`, exit 0). A temporary TS2304 failure in the new human-basis binding was corrected and the build rerun successfully. Final polish labels garage metrics as page-scoped, excludes an unknown repairer from garage aggregation, retains selected garage filters and uses IST declaration-day boundaries. An inherited Nitro/Vite peer warning remains. Build/dev were run sequentially after a concurrent build had disrupted an earlier rehearsal.

Latest-source browser smoke also opened the **same saved report twice**, with Escape dismissal and zero JavaScript errors (`saved_report_control_final.json`, exit 0). A selector-reset fix makes that control reusable. The report-control type-check and final production build passed (`frontend_build_release5.log`, exit 0).

## Blockers and production work still outstanding

- Real Gemini successful vision/adjudication: blocked by two observed HTTP 503 failures and required stop. New policy prompt effectiveness/detection accuracy remains unvalidated.
- Complete tenant isolation/cross-tenant tests, distributed/multi-host execution, billing and external deployment: not implemented or claimed.
- Verified applicant identity, MFA/recovery, receipt recovery, PDF/invoice/repair-document processing and actual same-vehicle multi-view validation: absent.
- Independent detection/adjudication evaluation, security/load review, privacy/storage lifecycle/encryption, durable external audit controls, centralized monitoring/alerts and deployment-specific regulatory checks: required before production SaaS.

The local queue/auth/evidence/report/UI foundation is implemented and verified within the limits above. [PILOT_HANDOVER.md](PILOT_HANDOVER.md) contains exact Windows commands and backup/restore procedures; [DEMO_RUNBOOK.md](DEMO_RUNBOOK.md) contains both workflows. Local commit identifiers and final preservation state are recorded below.

## Local commits

- `09d06e8`: original implemented patch/audit preservation.
- `2bdb644`: durable backend, evidence/auth/report changes and regression suites.
- `38298f2`: applicant/reviewer interface, truthful statuses/limits and report history.
- `1d3304a`: reusable saved-report selector, verified twice in Chrome.
- This document and reproducible verification tools are committed together separately; use `git log -4 --oneline` for that commit's identifier.

No provider attempts beyond the two recorded failures, no remote push and no deployment were performed. All original database counts and preserved research outputs were checked again before handover.

Final-source backend restarted on 8001, completed in-process warmup and passed real HTTP readiness/health, new individual credentials, old-password rejection after rotation, private route denial, report/run association, public tracking field privacy, operations and logout checks (`final_runtime_smoke.json`). It reports 17 failed jobs accurately; no queued/running work was hidden or marked successful. Original port-8000 service remains untouched. Frontend dev is restarted on 5173 after the final sequential build for local review; no external deployment was made.
