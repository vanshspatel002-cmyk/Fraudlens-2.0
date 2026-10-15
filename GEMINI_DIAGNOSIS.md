# Gemini diagnosis — 15 October 2026

No provider requests were made during this continuation. The original ledger
`outputs/pilot_validation/live_calls.json` remains stopped, with two failures:

| Attempt | UTC | Configured model | Recorded outcome |
|---|---|---|---|
| 1 | 2026-10-14 07:25:22 | gemini-3.5-flash | HTTP 503 |
| 2 | 2026-10-14 12:49:41 | gemini-3.5-flash | HTTP 503 |

Both reached the vision GenerateContent path. The first is corroborated by
`backend8001-v4.stderr.log`; the second by `live_verification.json`. Neither
record establishes successful vision, parsing, persistence or adjudication.
The sanitized records do not retain Google's complete error body/request ID.
They cannot distinguish temporary overload from a model/project-specific
availability problem. There is no recorded 429 in these two attempts.

Google describes 503 as temporary service overload/unavailability and 429 as
resource exhaustion. Calling these 503s “quota exhaustion” is unsupported.
[Official API errors](https://ai.google.dev/gemini-api/docs/api-errors).

The current official historical model guide says `gemini-3.5-flash` is deprecated
and automatically routed to `gemini-3.6-flash`. Its GenerateContent example uses
the same `v1beta/models/...:generateContent` endpoint as this application.
This documents API compatibility, not access for this project's key or free-tier
entitlement. No key/model/account was changed or probed.
[Official model guide](https://ai.google.dev/gemini-api/docs/generate-content/whats-new-gemini-3.5).

The guide recommends default sampling for Gemini 3.x. The existing adapter
explicitly set temperature 0. The pilot helper now explicitly selects
`FRAUDLENS_GEMINI_REQUEST_PROFILE=gemini3_defaults_v2`; that profile uses default
sampling for Gemini 3 models. Research/default `legacy` behavior and older
models keep their existing setting. The correction is not an established
cause or cure for HTTP 503. Changed requests use distinct raw LLM cache namespaces
ending `_gemini3_defaults_v2`; old entries and all legitimate content-hash
perception observations remain untouched. Research prompts, policies, thresholds,
datasets and historical outputs are unchanged. Production routing remains v3.

Installed google-genai 2.18.1 serializes the PIL image as inline image data and
chat as Content/Part objects. Offline MockTransport tests exercise that actual
SDK serialization without contacting Google. They verify the endpoint, MIME
type and omitted sampling override. They do not establish server acceptance.
[Official Python SDK](https://googleapis.github.io/python-genai/).

The adapter sets a 60,000 ms request timeout and SDK `HttpRetryOptions(attempts=1)`;
automatic function execution is disabled. Application retries reserve the shared
ledger before each actual request. Vision in the pilot uses one application
attempt; a malformed response can require a second, separately budgeted request.
The session stop persists across days/restarts. SDK defaults otherwise contain
automatic retries, so retaining the explicit one-attempt setting matters.
[Official troubleshooting](https://ai.google.dev/gemini-api/docs/troubleshooting).

Agent tool results currently return as explicit textual observations in the next
user turn; this is a manual application loop, not native function-response
continuation. Native thought-signature/function-response handling has not been
live verified. No successful tool-using adjudication is implied by offline tests.

## Requirement for a separate live verification

An explicit new authorization must define a fresh bounded session, its request
ceiling, the unchanged or explicitly approved model, and what to do with the
current stop. Preserve this ledger and both failure records as immutable history;
do not silently replace it to recover unused allowance. No such new session is
authorized by this continuation.

Before sending requests, verify project/model availability in the owner's Google
console without exposing credentials, retain free-tier-only settings and approve
the representative non-private evidence. Suggested ceiling: at most four actual
requests initially, including every retry, with no key/account rotation and stop
on 429 or two consecutive provider failures. Do not run the unbounded research
perception/ablation scripts as that verification.

Success requires a real vision response parsed and persisted with its image
hash/source, followed by a real agent response persisted against the correct run,
findings, policy and trace. Test the next tool turn if the model requests a tool;
stop and diagnose actual failures rather than generating a success substitute.
Report request counts and remaining gaps. Deterministic checks, cached observations,
mock replies and human decisions cannot stand in for successful fresh model work.
