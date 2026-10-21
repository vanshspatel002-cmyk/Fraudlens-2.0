# Gemini integration diagnosis — 21 October 2026

**Status: Partially fixed; fresh claims and underwriting processing remain
unverified because the existing failed-recovery control forbids another probe.**
No generation, model-listing or other Google API request was made in this task.
Passing offline tests and working manual review/PDFs do not establish live AI
completion. No application cases were submitted, reprocessed or decided.

Inspected branch: `repair/analysis-pipeline-20261020`, starting commit
`4be7c603de4e358e52d773aa5e3f26e4b5e11bb2`. Existing staged documentation,
connectivity/loading edits and mentor documents were included in inspection and
preserved separately. No applicable `AGENTS.md` was found in the repository or
its parent directories. The analysis repair handover and its verification record
were checked against current source, controls and bounded read-only database
queries. No full research suite was run.

## Findings and evidence

The immediate blocker is an **application circuit**, not a newly observed
provider outage. Its original stop string is broad, but its events are specific:

| UTC | Original session attempt | Recorded outcome | Meaning |
|---|---:|---|---|
| 14 October, 07:25:22 | 1 | HTTP 503 | Historical outbound vision failure. |
| 14 October, 12:49:41 | 2 | HTTP 503 | Second historical failure opened the circuit. |
| 20 October, 14:22:48 | 3 | Success | Earlier generic-text recovery probe; not image or workflow qualification. |
| 20 October, 16:20:54 | 4 | HTTP 503 | Earlier claims validation request failed; recovery became `failed` at 16:21:08 UTC. |

The ledger does not have an explicit timestamp on its original `stopped` field.
The original stop time is inferred from the second recorded failure. No event
was rewritten to add missing historical detail.

`src/session_budget.py::authorize_recovery` permits one initial recovery only.
It rejects a ledger that already contains a recovery. The existing recovery is
failed, and both running processes have no recovery allowance selected. This
is an explicit existing control; this task preserved it. The pure
`recovery_eligibility` audit now reports `prior_recovery_already_recorded`.

The newest three saved pilot jobs were read in a read-only PostgreSQL
transaction. All three are `failed` / `needs_review`, with
`provider_circuit_open`, `attempted_network=false`, no HTTP status, and zero fresh
responses. Their unavailable-photo counts were three, two and three. They did
not observe a fresh 503. Older jobs with incomplete diagnostics cannot establish
an outbound request from their status alone.

The previously unintended test call is retained in the private audit
`outputs/analysis_repair_20261021/accidental-test-transport-audit.json`. It records
one temporary-ledger transport reservation and a reported nonempty response.
The serving version/response were not retained. It is separate from the four
original session attempts and is not claims/underwriting proof. That earlier
request was not repeated here.

The original daily ledger contains eleven reservations on 14 October and two
on 20 October. A reservation is not proof of outbound HTTP: older controls could
reserve quota before a later local rejection. Do not equate those totals with
the session transport events or erase the discrepancy.

## Safe configuration audit

[Machine-readable configuration evidence](docs/gemini_diagnostics/configuration-audit.json)
was captured from the actual local API and worker process environments, with
credential comparisons performed only in memory. It contains no credential
values, credential hashes, connection strings or raw environment dump.

| Setting | Running API | Running worker | Ordinary diagnostic shell |
|---|---|---|---|
| Provider | Gemini | Gemini | Gemini |
| Agent model | `gemini-3.5-flash` | Same | Same |
| Perception model | `gemini-3.5-flash` | Same | Same |
| Key present | Yes | Yes | Yes |
| Installed/pinned SDK | `google-genai==2.18.1` | Same environment | Same environment |
| Request profile | `gemini3_defaults_v2` | Same | `legacy` |
| Session control | `<backend>/outputs/pilot_validation/live_calls.json` | Same | Unconfigured |
| Daily control | `<backend>/outputs/pilot_validation/quota_budget.json` | Same | `<backend>/outputs/quota_budget.json` |
| Database | PostgreSQL pilot | Same pilot schema | SQLite/default selection |
| In-process worker | Disabled | Dedicated worker enabled | Default setting only |
| Recovery selected | No | No | No |

API/worker provider, model, key configuration, control paths, consumer, request
profile, cap and database/schema settings matched. Their credentials matched the
backend `.env` in memory. No SDK endpoint override was present. The API passes
the same provider instance to perception and adjudication; there are no separate
production perception/agent model settings to conflate.

The shell is not equivalent to the launcher configuration. Importing `src.llm`
loads `.env` without overriding inherited environment variables, while
`scripts/start_pilot.ps1` explicitly selects pilot controls/profile/database.
Do not run an ad hoc provider request from the ordinary shell as a workaround.
The new audit command previews the pilot settings without changing controls.

**Remaining budget:** original lifetime cap 15, recorded attempts 4, numerical
headroom 11, **currently authorized additional calls 0**. The accidental request
has its separate retained record; 11 is stored-ledger headroom, not a claim that
all historical traffic is reconciled. The daily control last records a 100-call
application pool on 20 October with two reservations. This audit did not roll it
forward. Actual current Google quota, account entitlement and service health
remain unknown. No billing requirement or invalid-key response was observed here.

Stable copies of both original control files were retained in private Git
metadata before work. Byte comparisons verify their original contents were
preserved. Backups, locks and credential-bearing configuration are not committed.

## SDK and API compatibility

Google documents the configured `gemini-3.5-flash` alias as deprecated but still
routed to `gemini-3.6-flash`, with image input, function calling and structured
output support. This supports its candidacy, not account inference access. The
alias, keys and package versions were not changed. [Official model reference](https://ai.google.dev/gemini-api/docs/models/gemini-3.5-flash)

The installed SDK accepts the adapter's `Client`, `models.generate_content`,
`GenerateContentConfig`, disabled automatic function execution, and
`HttpOptions(timeout=60000, retry_options=HttpRetryOptions(attempts=1))` usage.
Controlled HTTP transports exercised actual SDK serialization/parsing; they do
not prove a live model response. [Official Python SDK](https://googleapis.github.io/python-genai/)

Image validation now decodes the immutable bytes before budget reservation and
sends those exact bytes using `Part.from_bytes` with the decoded MIME type.
PNG, JPEG and WebP serialization were checked, including misleading filename
extensions. No invented observations or overlays are generated locally.
[Official image input guide](https://ai.google.dev/gemini-api/docs/generate-content/image-understanding)

The optional image recovery probe uses a Pydantic schema for a visible-vehicle
flag and at most three short observations. SDK parsing must produce a schema
object. Normal perception retains its existing prompt/application validator;
agent final decisions retain their existing JSON validator and manual tool
loop. No production decision schema or policy was changed. Structured probe
mode is separate from the agent's tool configuration. [Official structured output guide](https://ai.google.dev/gemini-api/docs/generate-content/structured-output)

Original model content, function-call IDs and opaque thought signatures remain
preserved across parallel tool replies. Signatures are continuation data, never
displayed as private reasoning. Tools read saved evidence; `requery_perception`
does not make another vision call. [Official continuation protocol](https://ai.google.dev/gemini-api/docs/generate-content/thought-signatures)

Fresh generations must now contain candidates, usable text or function calls,
an explicit `STOP` finish reason, and no prompt block. Truncation, safety blocks,
empty candidates, malformed function calls, unspecified finish reasons and
invalid structured probe output fail validation before being cached. Known
truncated/blocked/empty older request-cache entries are ignored without deleting
them. Compatible saved perception is still attributed as cached, never fresh.
[Official response fields](https://ai.google.dev/api/generate-content)

The per-request timeout is 60 seconds and SDK retries are disabled. The existing
outer ordinary policy has at most five attempts, subject to earlier circuit and
budget rejection. Recovery mode forces one attempt with no key rotation.
Durable perception requests one transport attempt; its existing JSON repair may
need a second generation. Agent iterations remain capped at eight per case.
No unchanged access/model/request error is automatically retried. HTTP 503 is
classified as a historical transient response, not proof of current outage.
[Official troubleshooting guide](https://ai.google.dev/gemini-api/docs/troubleshooting)

Provider SDK calls in first-party runtime code remain centralized in `src/llm.py`.
The worker releases optional perception/tool/cache transactions before network
work. PostgreSQL worker leadership deliberately retains its separate heartbeat
connection; application case/result transactions do not span provider calls.

## Repairs and persistence

| File | Focused change |
|---|---|
| `FraudLens-2.0-Backend/src/llm.py` | Explicit image bytes/MIME; optional structured probe; finish/block/empty validation; reject unusable caches; retain cumulative attempt history and safe response identifiers. |
| `FraudLens-2.0-Backend/src/analysis_diagnostics.py` | Fixed safe messages; model, provider status/code/identifier and finish metadata; distinguish network, timeout, busy/invalid controls and response failures. |
| `FraudLens-2.0-Backend/src/perception.py` | Persist safe schema/finish diagnostics; omit failed response text; replace raw batch tracebacks with sanitized records. |
| `FraudLens-2.0-Backend/src/agent/engine.py` | Propagate safe schema provenance and replace unusable-response previews with a fixed omission marker. |
| `FraudLens-2.0-Backend/src/api.py` | Attach case/run identity to newly saved stage diagnostics. Earlier unrelated CORS edits remain separate. |
| `FraudLens-2.0-Backend/src/session_budget.py` | Expose pure recovery eligibility; distinguish corrupt control history. Existing one-recovery policy and original cap remain enforced. |
| `FraudLens-2.0-Backend/src/quota_budget.py` | Enforce aggregate and selected-key daily limits; a lock timeout fails closed instead of deleting a possibly live writer's lock. |
| `FraudLens-2.0-Backend/conftest.py` | Before collection, block real external HTTPX/Requests/aiohttp transport and isolate inherited provider controls. Mock transports/local TestClient remain usable. |
| `FraudLens-2.0-Backend/test_perception.py` | Move live opt-in onto callable test wrappers, covering pytest/direct invocation as well as its custom runner. |
| `FraudLens-2.0-Backend/test_llm.py` | Mark the cache-statistics assertion as dependent on its live/cache fixtures; it no longer assumes other suites supplied a live cache hit. |
| `FraudLens-2.0-Backend/test_demo_readiness.py` | Give the controlled SDK response its actual required `STOP` metadata. |
| `FraudLens-2.0-Backend/test_gemini_diagnostics.py` | Controlled SDK, error, MIME, schema, quota, concurrency, restart, privacy, legacy guard and persisted run-diagnostic regressions. |
| `FraudLens-2.0-Backend/scripts/diagnose_gemini.py` | Read-only shell/running-process/control inspection and request planning. |
| `FraudLens-2.0-Backend/scripts/recover_provider.py` | Future eligible probe requires explicit sample image and validated structured observation; keeps lower inherited caps and backs up controls. Generic text no longer qualifies. |
| `FraudLens-2.0-Backend/scripts/prepare_analysis_rehearsal.py` | Require current bounded recovery, matching successful image probe, sufficient minimum allowance and explicit photographs before creating a new namespace; reject existing schemas. |
| `ANALYSIS_REPAIR_HANDOVER.md` | Link current diagnosis and retained failed-recovery boundary. |
| `GEMINI_DIAGNOSTICS.md` and `docs/gemini_diagnostics/configuration-audit.json` | Sanitized evidence, limitations, commands and final status. |

Failed-stage records retain stage, timestamp, case/run, admitted attempt count,
attempted-network flag, error category, retryability and model where a provider
was selected. Returned HTTP codes/status enums and safe request/response IDs are
retained when available; absent values are not fabricated. A local stop after
earlier attempts includes their count and error history rather than claiming no
request occurred. Processing failure remains separate from automated risk.

HTTP failures consume both application attempt reservations. A request blocked
by the session precheck consumes neither. Cross-ledger races may conservatively
reserve daily quota before session admission loses a race; such a reservation
is not outbound evidence. The single half-open allowance is serialized by the
session file lock. A failed or invalid probe closes its recovery allowance.
Malformed ledgers and abandoned quota locks fail closed; do not delete them to
obtain capacity. Original provider events and recovery history were not reset.

## Verification

The first focused regression set passed **218 tests**, covering provider/recovery,
engine, readiness, durable jobs, saved explanations, live-evidence verification
and report/history behavior. Subsequent guard/diagnostic changes were checked by
the final provider-focused run recorded below. These runs overlap; do not add
their counts as distinct coverage. All model/SDK replies were controlled fixtures.

Final provider/legacy-isolation result: **146 passed, 10 skipped** in 46.14 seconds.
The ten skips are live-dependent tests, not successful inference. The earlier
guard run exposed a legacy cache-statistics test that assumed live fixtures;
its explicit live-dependent classification was repaired before this final pass.
Logs and exact commands are retained locally under
`FraudLens-2.0-Backend/outputs/gemini_diagnostics_20261021/` (ignored).

Covered cases include transient failure then one permitted successful recovery,
failed recovery reopening the circuit, concurrent processes competing for one
probe, restart retaining a failed control, exhausted session/daily/key caps,
concurrent quota writers, busy/corrupt controls, HTTP access/config/quota/server
errors, network timeouts, empty/blocked/truncated responses, structured schema
failure, sanitized logs, zero external transport and both case types retaining
case/run diagnostics in reviewer reports. Ordinary legacy live tests skip.
Frontend sources were not changed; frontend checks were not required.

**Live outcomes this task:** 0 requests; claims not live-verified; underwriting
not live-verified; no fresh agent/tool/PDF chain qualified. PDF regression tests
use fixtures and cannot change this status. Existing reports and human decisions
remain preserved.

## Request plan and resumable operation

For the existing rehearsal shape (one claims photograph and six underwriting
photographs), with all required perception fresh:

| Stage | Generation requests |
|---|---:|
| Initial structured sample-image probe | 1 |
| Fresh perception for the two applications | 7 minimum |
| Agent final answers | 2 minimum |
| One tool-result follow-up per application | 2 additional |
| Minimum including probe | 10 |
| Including one tool follow-up for each case | 12 |
| Upper bound with one schema retry per photo and eight agent turns per case | 31 |

Parallel local tool calls can share a follow-up turn; tool execution itself
does not consume a generation request. Actual model choices may require fewer
or more turns. Ten calls fit numerical headroom only; they do not guarantee both
tool traces. Twelve exceeds the retained 11-call headroom. The permitted
allowance is currently zero, so none of this plan was executed. The diagnostic
request cap of three was respected with zero used; it is not a substitute for
the separate application cap. No bulk processing is authorized.

From the repository root, use the backend directory. Safe read-only commands:

```powershell
Set-Location .\FraudLens-2.0-Backend
.\venv\Scripts\python.exe -X utf8 scripts/diagnose_gemini.py
.\venv\Scripts\python.exe -X utf8 scripts/diagnose_gemini.py --pilot --plan-validation
# Substitute the actual API/worker Python process ID; no environment dump:
.\venv\Scripts\python.exe -X utf8 scripts/diagnose_gemini.py --process-id <PID>
.\venv\Scripts\python.exe -X utf8 scripts/recover_provider.py --output outputs/recovery-not-executed --reason "Read-only control inspection"
```

Normal startup, separate terminals, same preserved controls (no probe):

```powershell
.\scripts\start_pilot.ps1 -Database postgresql -Schema fraudlens_pilot -Port 8001 -NoWorker
.\scripts\start_pilot.ps1 -Database postgresql -Schema fraudlens_pilot -WorkerOnly
```

API: `http://127.0.0.1:8001`; existing frontend:
`http://127.0.0.1:5173/admin`. Do not start a second listener on an occupied port.
The idle API and worker were reloaded after testing with those same settings.
Health/readiness returned 200, OCR warmup completed, one pilot leadership lock
was held, and zero queued/running pilot jobs remained. The post-reload audit
confirmed matching settings, byte-identical controls and zero authorized Gemini
calls. Restarting does not reopen the circuit. No database migration is required.

Repeat the relevant offline checks, never with live opt-in:

```powershell
.\venv\Scripts\python.exe -X utf8 -m pytest -q test_gemini_diagnostics.py test_analysis_recovery.py test_engine_reliability.py test_demo_readiness.py test_llm.py test_perception.py
.\venv\Scripts\python.exe -X utf8 -m pytest -q test_durable_pilot.py test_report_pdf.py test_assessment_explanation.py test_verify_live_analysis.py
```

Under pytest, real external HTTP requires **both** `--live-gemini` and
`FRAUDLENS_TEST_LIVE=1`. Neither authorizes circumventing provider controls.
Standalone legacy runners also require the explicit environment opt-in. Do not
enable these tests to diagnose the failed circuit or spend its remaining cap.

### Exact unresolved action

There is no permitted current command that reopens this already-failed recovery.
The project/control owner must review the retained failures and explicitly
approve a separate change to the one-recovery policy before a further probe can
be allowed. This task's instruction to respect existing explicit controls
precludes making that exception automatically. Keep the same ledgers and cap;
do not delete recovery records, select a fresh ledger or rotate keys.

After that separately reviewed policy operation exists, first pause provider
consumers while retaining unrelated jobs, take consistent control backups, and
allow one half-open image probe through the original budget adapter. The existing
probe command is ready for an **eligible** circuit, but currently refuses:

```powershell
.\venv\Scripts\python.exe -X utf8 scripts/recover_provider.py --execute --image "<authorized non-sensitive vehicle photograph>" --output "outputs/<new-private-probe-directory>" --reason "<reviewed recovery authorization>"
```

If it returns an access, invalid-model/request or quota/billing response, stop
and address that exact provider/account issue without retries or purchases.
If it returns another transient failure, retain the failed recovery and stop.
No fresh provider response in this task identifies such an external account issue.

Only a successful image probe and an explicitly authorized, sufficient bounded
validation allowance can unlock rehearsal preparation:

```powershell
.\venv\Scripts\python.exe -X utf8 scripts/prepare_analysis_rehearsal.py --schema "fraudlens_repair_<new_suffix>" --directory "outputs/<new-private-runtime>" --recovery-result "outputs/<successful-image-probe>/probe-result.json" --claims-photo "<claims photograph>" --underwriting-photo "<front view>" --underwriting-photo "<rear view>" --underwriting-photo "<left view>" --underwriting-photo "<right view>" --underwriting-photo "<dashboard view>" --underwriting-photo "<engine-bay view>"
```

The source must establish legitimate authorized photographs; slot labels alone
cannot establish one vehicle. Both isolated API and worker must then use that
same new schema/runtime directory and the existing approved recovery allowance,
while normal provider consumers remain unable to spend it. The existing
`FraudLens-2.0-Frontend/scripts/verify_analysis_browser.py --config <private-rehearsal.json> --resume`
can resume accepted cases without replacement; omit `--resume` for a new empty
checkpoint. Do not pass `--allow-incomplete` as live qualification. Human actions
in that harness are explicit fictional reviewer workflow steps, not model output.
Finally use the backend read-only saved-run verifier:

```powershell
.\venv\Scripts\python.exe -X utf8 scripts/verify_live_analysis.py --schema "fraudlens_repair_<new_suffix>" --accepted-cases "outputs/<new-private-runtime>/browser/accepted-cases.json" --output "outputs/<new-private-verification-directory>"
```

It requires distinct successful original-ledger perception and agent requests
for both cases. Never unlock historical reprocessing with a manual-review
manifest. These gated steps were documented, not executed here.
