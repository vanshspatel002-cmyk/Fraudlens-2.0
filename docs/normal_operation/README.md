# Normal local claims verification — 22 October 2026

**Claims: Live workflow verified. Underwriting: live validation deferred; shared software verified with controlled fixtures.**

The ordinary customer UI submitted one fictional case into the existing pilot,
not the earlier isolated validation schema. One initial HTTP 503 was retained as
a failed run. An explicit reviewer retry completed with fresh perception, two
real agent turns and one `get_claimant_history` tool exchange. It saved actual
findings, routing, receipts and a versioned report. No generic probe was repeated.

The completed run has an **incomplete assessment**: registration, external-image
comparison and scene/context evidence remain insufficient. Its risk display stays
neutral, with no invented score. The model escalated the expected duplicate of
this public sample in the pilot corpus; this is not evidence of detection accuracy
or a fraudulent applicant. A fictional reviewer requested more evidence, and the
customer received that update. Nobody approved or rejected an existing case.

| Artifact | Open |
|---|---|
| Actual saved claims PDF, nine pages | [PDF](claims-live.pdf) · [first page](claims-front.png) |
| Underwriting software fixture, nine pages | [PDF](underwriting-fixture.pdf) |
| Ordinary admin case detail | [Laptop](admin-claims-laptop.png) · [Mobile](admin-claims-mobile.png) |
| Underwriting fixture header | [Screenshot](underwriting-fixture-header.png) |
| Actual claims check graphics | [Registration and image reuse](claims-registration-and-reuse.png) · [Amount heuristic](claims-amount-comparison.png) |
| Underwriting fixture check graphics | [Metadata and relationships](underwriting-fixture-metadata-relationships.png) |
| Customer reviewer update | [Screenshot](customer-outcome.png) |
| Sanitized results and accounting | [Audit](audit.json) |

The claims photographs are authorized existing samples; all applicant declarations
and accounts in these artifacts are fictional. Underwriting uses authored
illustrations and controlled results, not a legitimate six-view live qualification.
Previously committed before/after header fixtures remain in
[the earlier visual review](../visual_review/README.md); they are dated software
fixtures, not screenshots of this new live case before it existed.

Renderer: `fraudlens-pdf-2026-10-22-v5`. Every page of these two PDFs was extracted,
rasterized and visually inspected. Automated checks found no text outside page
bounds or altered image aspect ratios. Desktop/mobile browser checks found no
overflow or JavaScript errors. Preview, inline response, attachment response and
download contain the same saved PDF bytes. The headless Chrome native viewer
opened but did not paint its pages; manual/native preview pixels remain unverified.

Four new generation attempts were used, preserving the previous eleven: one
HTTP 503, one successful perception and two successful agent turns. No metadata
request was needed. The task allowance closes at fifteen cumulative attempts;
the unused twenty-six are not a diagnostic or batch grant. Normal operation uses
the documented daily/per-case limits and remains separately controlled.

Final API/worker configuration matched, health/readiness/frontend returned 200,
and the queue was empty. The final API cold start took 663.875 seconds under
memory pressure, peaking around 1.56 GiB. This local startup bottleneck remains
open; no provider call or timeout increase was used to conceal it.

See [operating commands, limits and rollback](../NORMAL_OPERATION.md),
[the diagnostics](../../GEMINI_DIAGNOSTICS.md) and [implementation record](../NORMAL_OPERATION_WORKLOG.md).
