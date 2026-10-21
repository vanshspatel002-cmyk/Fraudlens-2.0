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
