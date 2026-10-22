# Corrected Gemini perception probe - 22 October 2026

**Status: corrected live perception verified; full pipeline NOT verified.**
Exactly ONE corrected-schema generation reached Google: HTTP 200, ten valid
observation fields, no cache, zero transport/application retries and zero
metadata requests. The application now records **7/15 attempts, 8 remaining
slots, and zero additional generation permission**. Ordinary generation remains
stopped. No claims/underwriting job, agent execution or report was run here.

Starting commit: `8a534bf5388769c0eed8281de5da184f2bf3572d` on
`repair/analysis-pipeline-20261020`. This document and the original
[operator-recovery-audit.json](docs/gemini_diagnostics/operator-recovery-audit.json)
were read first. That audit and the earlier configuration audit are unchanged.
No applicable AGENTS.md was found. Unrelated staged/working edits remain separate.
Current evidence: [corrected-schema-audit.json](docs/gemini_diagnostics/corrected-schema-audit.json).
The preceding task's complete record is retained below as historical evidence.

## Actual request and observation evidence

The authorized request ran on **22 October, 06:58:51-06:59:05 IST**
(01:28:51-01:29:05 UTC), using the unchanged `gemini-3.5-flash` identifier,
`gemini3_defaults_v2` profile, Google SDK 2.18.1, actual decoded JPEG bytes,
`PERCEPTION_PROMPT`, and all ten fields/enums of
`fraudlens-visible-observations-2026-10-20-v1`.
It used `data/curated/damaged/damaged_0045.jpg`, the previously authorized,
visually inspected dataset image. No people or readable registration are visible.

| Evidence | Actual result |
|---|---|
| HTTP attempts / status | 1 / 200; ledger attempt 7 |
| Provider error code / invalid field paths | None returned on this successful response |
| Structured output | Valid ten-field JSON; adapter and local Pydantic validation passed |
| Wire contract | `json_schema_v1`: `responseJsonSchema`, JSON MIME, full schema preserved |
| Image SHA-256 | `c23e423cba25e054ef448bfa92dc7b489c57d025f120128f3a275f4728b762a8` |
| Exact serving-model version / response ID | Not retained; explicitly null |
| Literal finish metadata / provider latency | Not retained; explicitly null |
| Finish validation | Adapter requires STOP and passed validation before recording HTTP success |
| Scope | Fresh image perception only; no agent or case-pipeline qualification |

Actual retained observations describe severe glass damage with multiple holes,
unknown weather, daylight, no clear directional shadow, an empty plate string,
and an outdoor close-up. These broadly match the photograph. The model's **rear**
orientation and **paved ground** description are not independently established
from this small crop and remain uncertain. These observations do not establish
cause, capture date, fraud, calibrated severity or general accuracy.

### Local diagnostic persistence error, repaired without another request

The live adapter returned successfully and `observations.json` was saved. The
new artifact writer then attempted to JSON-serialize a dataclass containing
`PerceptionRecord.created_at` as a datetime and raised TypeError. The original
command therefore exited 1. Its original `probe-result.json` is retained, including
its misleading generic post-request failure classification; it is not overwritten.
This was a **local artifact error after HTTP success**, not a provider rejection
or response-schema failure. The exact failure was reproduced offline.

The writer now encodes the timestamp explicitly, saves a safe response receipt
before later artifact work, and classifies persistence errors separately. Controlled
tests cover successful persistence and a forced write failure. No second live
request was made to test this fix.

The actual observation file was revalidated offline and combined with the original
request contract, image hash and append-only ledger into:

- `<backend>/outputs/corrected_schema_20261022/probe/observations.json`: preserved actual observations.
- `.../observation-record.json`: repaired record, full schema, request/model/image provenance and timing.
- `.../reconciled-result.json`: audited reconciliation; original command exit remains disclosed.
- `.../probe-result.json`: unchanged original diagnostic receipt.

These artifacts are ignored private outputs, not application case records or
provider caches. Exact serving version, response ID, provider latency and literal
finish metadata were lost before receipt persistence; they cannot be recovered
without inventing data. The reconstructed artifact records that limitation and
uses the real ledger completion timestamp rather than pretending it is provider
latency. STOP is a validated code-path fact, not retained literal metadata.

## Correction-specific recovery and configuration

`src/session_budget.py::authorize_schema_correction` appends a new, named operator
grant for the recorded HTTP 400 at attempt 5. It records its previous recovery,
original stop, correction commit `8a534bf5388769c0eed8281de5da184f2bf3572d`,
registered correction ID, `json_schema_v1`, schema version, reason, expected attempt
count and **one-request allowance**. It never clears or resets the circuit.

The transport and gate share `src/provider_contract.py`: the exact full schema,
prompt, image hash, model and profile must match. Generic chat, a changed image,
legacy wire format, mismatched schema/model/profile, stale attempt counts,
quota/manual stops, in-flight operations and repeated grants of this same
correction are refused. Shared locking serializes the grant/reservation.
The one allowance is consumed; the latest recovery is `probe_succeeded` and the
original stop remains. A separately authorized bounded validation action would
be required to permit future workflow calls; it was NOT performed here.

The existing corrected SDK implementation was checked against actual HTTP payloads
using MockTransport: `responseJsonSchema` equals the complete Pydantic JSON schema,
`additionalProperties` is preserved, legacy `responseSchema` is absent, JPEG MIME
and decoded bytes match, and SDK attempts=1 / redirects=false. Local JSON/enum
validation remains inside the controlled request before success is recorded.
No SDK/model/key changes were needed. The prior field-level 400 explanation
remains unconfirmed; the successful corrected request establishes that this
schema route works for this perception request.

Strict pilot configuration was read from the running API and compared with the
worker in memory: PostgreSQL `fraudlens_pilot`, Gemini, unchanged model/profile,
original `outputs/pilot_validation/live_calls.json` and `quota_budget.json`, and
matching credentials (presence/equality only; never printed or hashed). The API's
in-process worker was disabled. Zero queued/running jobs were checked before
pausing the dedicated worker; zero leadership locks were confirmed before the
probe. Both controls were consistently backed up before authorization. All six
original session events, both previous recoveries, quota event prefixes and
quota history remain unchanged. The request appended attempt 7; cap remains 15.

## Offline verification and changed files

- Full regression after the persistence fix: **208 passed, 10 live-dependent tests skipped**, 75.52 seconds.
- Final follow-up after preserving the separately authorized validation path: **138 passed**, 69.21 seconds.
- These runs overlap; do not add their totals. All tests used isolated controls and external-HTTP guards. Zero offline Google calls.
- Tests inspect real SDK wire serialization, required fields/enums, byte/MIME equality, validation failures and sanitized details, concurrent correction grants, history/cap retention, mismatched requests, single use, and artifact write failures.
- Frontend files were not changed by this task; frontend checks were not required.

| File | Focused change |
|---|---|
| `FraudLens-2.0-Backend/src/provider_contract.py` | Registered correction/wire version and non-secret schema/image/prompt fingerprints. |
| `FraudLens-2.0-Backend/src/session_budget.py` | One-use HTTP 400 correction gate; exact request scope; existing explicit validation path retained. |
| `FraudLens-2.0-Backend/src/llm.py` | Pass transport contract through normal controls; retain safe local validation issue codes. |
| `FraudLens-2.0-Backend/scripts/recover_provider.py` | Explicit correction flags; observation/receipt artifacts; timestamp serialization and truthful persistence-error handling. |
| `FraudLens-2.0-Backend/test_schema_correction.py` | SDK payload, gate/concurrency, persistence and failure regressions. |
| `GEMINI_DIAGNOSTICS.md`, `ANALYSIS_REPAIR_HANDOVER.md`, `docs/gemini_diagnostics/corrected-schema-audit.json` | Current evidence, limitations and unexecuted validation plan. |

## Prepared workflow plan - NOT executed

Use a new isolated PostgreSQL schema, fictional accounts and authorized sample
photographs: one claims image and six real views of the same underwriting vehicle.
Select fresh image hashes absent from that schema's perception/request caches;
the already used probe image or any cached result must not qualify as fresh.
Photo-slot names alone cannot prove vehicle identity. No case acceptance,
processing, agent follow-up or report generation is authorized in this task.

| Stage | Absolute minimum | Bounded maximum |
|---|---:|---:|
| Fresh perception, 1 claims + 6 underwriting images | 7 | 14 including at most one schema retry per image |
| Agent generation across both cases | 2 final-answer turns | 16, existing 8 iterations per case |
| Total new workflow generations | **9** | **30** |

To demonstrate an actual tool exchange in each case, budget at least **11**:
seven images plus a tool-request turn and final-answer follow-up in each case.
Local check/tool execution itself costs zero generations. Tool-result follow-ups,
invalid-answer correction turns and final answers all count within each agent's
8-turn cap. The 30-call ceiling assumes all SDK/application transport retries are
disabled, no additional evidence/requery inference, no metadata requests, and an
explicit overall allowance. It is a stopping bound, not a promise of convergence.

Only **8** application slots remain: neither the 9-call floor nor the 11-call
tool-exchange plan fits. This application's lifetime cap and its daily quota
ledger are local controls; they are not Google's account/project RPM/TPM/RPD,
entitlement or billing state. Actual Google headroom is unknown. This task made
no metadata/quota-console request and changed no billing setting.

**Proposed development-budget revision, NOT applied:** explicitly authorize and
review a new `isolated-two-case-validation-budget-v1` policy with cumulative
ceiling **37 = 7 retained attempts + up to 30 new workflow calls**, plus a separate
30-call validation grant restricted to the new schema/run IDs and an expiry.
Append operator, reason, old/new ceilings, time and scope to the existing audit;
preserve every previous event, provider limit and key. The current hard-coded
15 ceiling exists in multiple controls and rehearsal guards, so changing an
environment value alone must not bypass it. A smaller 11-call plan needs a
cumulative ceiling of 18 but may stop before agent convergence. Neither revision
was implemented or authorized by this probe task. No reset, billing enablement
or key rotation is proposed.

After new explicit budget/workflow authorization: validate the Google account's
limits without assuming that this successful request reserves future capacity;
prepare the new schema and legitimate photo set; grant a bounded validation
allowance separately; start API/worker with shared controls; submit one case of
each type serially. Verify fresh observations, schema-valid agent decisions,
recorded tool actions, real checks, saved explanation, report/run consistency and
authorization in customer/admin views. Stop at the call ceiling or on a
non-transient/repeated transient failure. Cache/fallback/partial runs do not pass.

Read-only next command from the backend directory (`<API_PID>` is the current
Python API process, not its launcher):

```powershell
.\venv\Scripts\python.exe -X utf8 scripts/diagnose_gemini.py --process-id <API_PID> --plan-validation
```

Do not rerun `--execute` or metadata for this spent task authorization. The same
registered correction cannot be granted twice. Original ledgers and private
response files must not be edited to manufacture another allowance.

Services were restarted using the original pilot launcher and same stopped
controls. Health/readiness returned 200; OCR warmed; one worker leadership lock
and zero queued/running jobs were verified. API/worker settings match and the
ledger remains at seven attempts; final evidence is in the current audit.
API `http://127.0.0.1:8001`; admin `http://127.0.0.1:5173/admin`.
No application case, report or decision was created or reprocessed. No push,
deployment, cap increase, credential change or historical reprocessing occurred.

---

# Historical record from the preceding task (retained unchanged)

The following section describes the state before the corrected probe above.
Its attempt counts, spent authorizations and unverified status are historical.

# Gemini operator recovery - 21 October 2026

**Status: policy/configuration repaired; live perception is NOT verified.**
The one authorized generation reached Google and returned **HTTP 400 /
INVALID_ARGUMENT**. No observations or finish reason were returned. A separately
authorized model-metadata GET succeeded. An SDK/schema wire-format defect was
then reproduced and repaired **offline only**. There was no second generation,
no claims/underwriting run, and no claim that the pipeline is fixed.

Starting branch: `repair/analysis-pipeline-20261020`; starting commit:
`e91fd4cf424949531a3b35b50d65cf54322436cb`. The previous version of this document
and [configuration-audit.json](docs/gemini_diagnostics/configuration-audit.json)
were inspected first. That earlier audit remains unchanged. No applicable
`AGENTS.md` was found in the repository or parent directories. Existing staged
documentation, connectivity/loading edits and mentor documents remain separate.

Current evidence: [operator-recovery-audit.json](docs/gemini_diagnostics/operator-recovery-audit.json).
It contains sanitized configuration, operation results, counts and preservation
checks, without credentials, credential hashes, prompts, images or private
absolute paths. Private controls/backups/logs remain ignored under
`FraudLens-2.0-Backend/outputs/operator_recovery_20261021/`.

## Actual request results and remaining budget

| Operation | Original-ledger attempt | HTTP | Outcome | Remaining lifetime headroom |
|---|---:|---:|---|---:|
| Before this task | 4 recorded attempts | n/a | Earlier failed recovery retained | 11 |
| ONE full-perception generation | 5 | 400 | `INVALID_ARGUMENT`; `provider_configuration`; non-retryable unchanged request | 10 |
| ONE configured-model metadata GET | 6 | 200 | Model metadata readable; no generated content | 9 |

Generation started on **21 October at 18:11:28 UTC** and failed at approximately
18:11:32 UTC; exact timestamps are in the audit. Metadata inspection ran at
18:18:45-18:18:47 UTC. Each operation made one observed HTTP dispatch. SDK/outer
transport retries and credential rotation were disabled. Totals this task:
**1 generation request, 1 metadata GET, 0 retries**.

Generation used the unchanged `gemini-3.5-flash` identifier,
`gemini3_defaults_v2` profile, original first configured key, original controls
and full `fraudlens-visible-observations-2026-10-20-v1` observation schema.
The existing sample `data/curated/damaged/damaged_0045.jpg` was visually inspected:
it shows a damaged windscreen, with no people or readable registration plate.
It is dataset evidence, not a private applicant submission.

Schema validation was **not run on generated content**, because Google rejected
the request. There is no returned finish reason, serving version, usable
observation, agent result, case assessment or live report to claim.

The metadata GET advertised `generateContent`, `countTokens`,
`createCachedContent` and `batchGenerateContent`, with input/output limits
1,048,576 / 65,536. It proves account-visible metadata access at that time. It
does not prove generation entitlement, current generation quota, image inference
success, agent execution or complete workflow success.

The lifetime cap remains **15**. There are now **6 recorded attempts**, including
the separately typed metadata operation, and **9 headroom**. Additional currently
authorized generation calls are **zero**. Metadata was conservatively counted in
both normal application budgets. No cap or recovery allowance was expanded.
The generation circuit remains stopped and the new recovery is `failed` with
`failure:400`; metadata success did not change that state or failure counters.

## What changed in the failed-recovery policy

`prior_recovery_already_recorded` came from application code in
`src/session_budget.py`, introduced by the earlier repair. Handovers described
that code; no repository instruction required an immutable permanent block.
The user's current authorization explicitly permitted this focused policy change.

Policy `operator-transient-recovery-2026-10-21-v2` now supports an explicit
**named operator** requesting another half-open probe after a failed transient
recovery. It keeps the original stop and appends a new recovery record rather
than resetting anything.

- Cooldown: **30 minutes** from the preceding failed recovery's recorded finish.
  It is a fixed policy value, not a shell override. Missing/untrusted timestamps
  fail closed. Clock rollback cannot shorten the wait.
- Eligible failures: recorded HTTP 500/502/503/504 or known transient network/
  timeout outcomes. Access, model/request configuration, quota, billing and
  explicit manual stops cannot receive an automatic transient exception.
- Each operator grant authorizes **one** request. The operator label, reason,
  policy version, preceding recovery, cooldown, base attempt count, allowance
  and timestamps are retained.
- A shared file lock serializes authorization/reservation across processes. Any
  in-flight reservation prevents a new recovery. A prior recovery cannot spend
  the latest grant. Concurrent operators/workers were tested.
- Expected-attempt checks reject races against the backed-up state. Failed
  probes close their grant; successful probes consume it and still require a
  separately authorized validation allowance. Neither outcome opens ordinary
  background generation.
- No background retry loop or timer grants permission. An operator must act
  explicitly after cooldown. A process crash with an unresolved reservation
  fails closed for audit rather than assuming a request did not happen.

The original four session events and original failed recovery remain unchanged.
The new generation is appended as attempt 5. The metadata read is appended as
attempt 6 with `kind=model_metadata`, no generation-recovery grant, and its own
operator/reason. Read-only metadata is restricted to the configured model's GET,
uses the original cap/daily controls, and cannot reopen or qualify generation.
Stop transitions are append-only when the stop category actually changes.

The earlier accidental test request remains disclosed in its separate private
historical audit. It was not repeated or merged away. The older quota
reservation/session-event discrepancy is retained; a reservation alone does
not prove outbound inference.

## Configuration alignment

`src/pilot_config.py::load_pilot_environment` now requires the **complete effective
pilot environment**. Diagnostic/recovery commands can read it directly from the
running API process using `--process-id`; credential values only pass through
memory. No SQLite/default selection, alternate quota file, guessed model or
partial `--pilot` preview is accepted.

| Setting | Verified API and worker / probe |
|---|---|
| Database/schema | PostgreSQL / `fraudlens_pilot` |
| Provider | Gemini |
| Perception and agent model | `gemini-3.5-flash` (same provider configuration) |
| Request profile | `gemini3_defaults_v2` |
| Session ledger | `<backend>/outputs/pilot_validation/live_calls.json` |
| Quota ledger / consumer | `<backend>/outputs/pilot_validation/quota_budget.json` / `pilot` |
| Lifetime cap | 15; lower inherited caps are retained |
| SDK | Installed/pinned `google-genai==2.18.1`; unchanged |
| Credentials | Present; API/worker settings compared equal in memory |

Missing schema, database URL, provider/model/profile, credentials, cap or original
ledgers produces a clear setting-name error. No values are echoed. Alternate
ledgers and higher caps are refused. The adapter is constructed with explicit
model/profile values after alignment, avoiding module-import-time shell defaults.
Numbered keys absent from the reference are removed from the diagnostic process;
credentials are never rotated. The normal pilot launcher already sets these
values and was not changed.

## Official model/API check and concrete correction

Google documents `gemini-3.5-flash` as a deprecated alias routed to
`gemini-3.6-flash`, with image input, function calling and structured output.
The alias was not guessed or changed. The one model GET additionally established
that this configured identifier is account-visible; generation still failed.
[Official model guide](https://ai.google.dev/gemini-api/docs/models/gemini-3.5-flash)

The request used decoded JPEG bytes, the full current perception prompt/schema,
JSON output, default Gemini 3 sampling, a 60-second timeout and one SDK attempt.
No malformed safety setting or tool schema was added to this image-only probe.
[Official image input guide](https://ai.google.dev/gemini-api/docs/generate-content/image-understanding)

**Definite offline defect:** the pinned SDK serialized Pydantic's
`extra='forbid'` through the legacy `response_schema` conversion as
`generationConfig.responseSchema.additional_properties=false`. Google's legacy
`Schema` protocol does not define that field. The same observation schema is
valid JSON Schema, where `additionalProperties` is supported. This is a concrete
protocol mismatch and the likely cause of the 400. The provider's field-level
error was not retained on that first request, so its exact attribution is not
claimed as confirmed. [Official generation/Schema reference](https://ai.google.dev/api/generate-content)

**Correction now applied offline:** send
`response_json_schema=PerceptionObservation.model_json_schema()` with JSON MIME,
then explicitly validate returned JSON against the same Pydantic type before
recording a successful adapter outcome. The corrected wire contains
`responseJsonSchema.additionalProperties`, without legacy `responseSchema`.
Required fields and enums still come from the existing perception contract.
The request-cache key records the changed wire contract; old entries are retained.
[Official structured-output guide](https://ai.google.dev/gemini-api/docs/generate-content/structured-output)

Actual SDK serialization was inspected and strict controlled transports now
reject the old route. The corrected request was **not sent live**. No arbitrary
SDK upgrade, model substitution, key change, billing action or second generation
was used to test it. Future failures retain only safe ErrorInfo reason enums,
BadRequest field paths and fixed hints; raw error bodies remain omitted.

The initial historical HTTP 503 failures are still historical. This task's fresh
response is HTTP 400. It is not evidence of a fresh service outage or quota
exhaustion. Successful metadata access narrows the issue but does not substitute
for a corrected generation response.

## Offline verification and changed files

Final focused result: **184 passed, 10 live-dependent tests skipped**, 52.99 seconds.
Earlier overlapping runs passed 179, 110 and 113 cases; do not sum those counts.
No offline test contacted Google. The existing before-collection HTTPX/Requests/
aiohttp guard and disposable controls remain active even with a developer key.

Tests cover cooldown boundaries, original-history retention, cap/in-flight
refusal, concurrent operators and probe reservations, failure reclosure, separate
validation permission, HTTP dispatch counting, full schema/enum equality, MIME,
strict wire format, failed structured replies, metadata GET scope/budgets,
unchanged generation stops, sanitized errors and missing/mismatched pilot settings.
Frontend sources were not changed; no frontend checks were required.

| Repository-relative file | Purpose |
|---|---|
| `FraudLens-2.0-Backend/src/session_budget.py` | Audited cooldown recovery; latest-grant coordination; typed, capped metadata reads; stop history. |
| `FraudLens-2.0-Backend/src/pilot_config.py` | Strict reference-environment alignment; original controls only. |
| `FraudLens-2.0-Backend/src/llm.py` | One-dispatch counters, disabled redirects/retries, fixed model-metadata GET, corrected JSON Schema transport and local validation. |
| `FraudLens-2.0-Backend/src/perception.py` | Shared ten-field Pydantic contract derived from existing fields/enums. |
| `FraudLens-2.0-Backend/src/analysis_diagnostics.py` | Safe provider reason/field extraction without raw message retention. |
| `FraudLens-2.0-Backend/scripts/diagnose_gemini.py` | Require complete pilot configuration; report schema/operator eligibility. |
| `FraudLens-2.0-Backend/scripts/recover_provider.py` | Explicit operator probe, consistent backups, real perception schema, precise sanitized results and separate metadata mode. |
| `FraudLens-2.0-Backend/scripts/prepare_analysis_rehearsal.py` | Require the current full-schema probe before future live validation. |
| `FraudLens-2.0-Backend/test_operator_recovery.py` | Controlled policy, SDK wire, concurrency, metadata and configuration regressions. |
| `FraudLens-2.0-Backend/test_gemini_diagnostics.py` | Update fixtures to the actual perception schema. |
| `GEMINI_DIAGNOSTICS.md`, `ANALYSIS_REPAIR_HANDOVER.md`, `docs/gemini_diagnostics/operator-recovery-audit.json` | Current handover and sanitized evidence. |

## Next commands and validation budget

From the backend directory, inspect the running pilot API without a network
model request. Replace `<API_PID>` with its current Python process ID:

```powershell
.\venv\Scripts\python.exe -X utf8 scripts/diagnose_gemini.py --process-id <API_PID> --plan-validation
.\venv\Scripts\python.exe -X utf8 scripts/recover_provider.py --process-id <API_PID> --operator local-operator --output outputs/recovery-not-executed --reason "Read-only control inspection"
```

The second command has **no `--execute`**. Do not repeat metadata or generation
under this task's spent authorization. The latest HTTP 400 is intentionally
ineligible for an unchanged transient retry. A future corrected-request probe
requires new explicit authorization and an audited correction-specific gate;
retyping `--operator`, waiting out cooldown or editing/resetting ledgers is not
permission to bypass a configuration failure.

After a future successful corrected perception probe, the prior rehearsal shape
requires seven fresh image calls (one claims, six underwriting) plus at least two
agent final-answer calls: **9 case calls minimum**. One tool follow-up per case
raises that to **11**; existing schema/iteration caps allow up to **30** case calls.
The remaining headroom is 9. It could fit only the bare minimum case calls if
qualification already existed, with no follow-up/retry margin. Qualification
currently does not exist. Another probe plus both fresh cases needs at least
**10**, so that complete plan does not fit the retained headroom. Do not raise
caps automatically or represent cached observations as fresh case inference.

No claims, underwriting, report, decision or historical processing was run here.
Normal startup retains the same configuration and stopped controls:

```powershell
.\scripts\start_pilot.ps1 -Database postgresql -Schema fraudlens_pilot -Port 8001 -NoWorker
.\scripts\start_pilot.ps1 -Database postgresql -Schema fraudlens_pilot -WorkerOnly
```

API: `http://127.0.0.1:8001`; admin: `http://127.0.0.1:5173/admin`.
The dedicated worker was paused only after checking zero running/queued jobs;
other provider consumers were absent and the API's in-process worker was off.
Consistent original-control backups preceded each authorized operation. The API
and worker were restored with repaired code and the same stopped controls.
Health/readiness returned 200; OCR warmed; one leadership lock and zero active
jobs were verified. The operator audit records matching effective settings and
unchanged attempt counts after restoration. Restarting cannot
authorize generation. No push or deployment is part of this work.
