# Local latency investigation — 15 October 2026

These are individual observations on this Windows laptop (8 GB RAM, four logical
CPUs), not latency percentiles, a load test or measurements of successful Gemini.
The original approximately 563-second intake and 364-second underwriting run
lack complete stage profiles, so their entire causes cannot be reconstructed.
The old intake log does show cold CLIP initialization. OCR CPU work was previously
observed in underwriting. No inference or verdict was replaced to obtain speed.

New measurements use a consistent SQLite backup of the frozen demo, named
`outputs/pilot_validation/readiness_20261015/acceptance.db`. The original selected
demo and research databases were not used as writable benchmark targets.
Provider requests: **zero**; both original HTTP 503 records/stop remain intact.

| Observation | Seconds |
|---|---:|
| Process-cold first HTTP submission, deliberately using `-NoWarmup` | 296.641 |
| Second submission in that same API process | 1.203 |
| First admission vehicle gate (includes dependency/text/model initialization) | 290.486 |
| Warm admission vehicle gate | 0.554 |
| First CLIP model construction/weight loading within that gate | 86.660 |
| First indexing using the admission embedding; no second CLIP encoding | 3.283 |
| Warm indexing using the admission embedding | 0.049 |
| Separate API startup admission warmup, before readiness | 72.454 |
| First profile-case processing, after worker OCR warmup | 149.290 |
| Second profile-case processing, reusing legitimate OCR observations | 8.234 |
| First profile-case checks / second checks | 142.234 / 6.323 |
| First plate OCR check / same-photo cached check | 31.241 / 0.051 |
| First experimental AI check / warm check | 102.224 / 1.755 |
| Actual fallback adjudication, first / second | 0.049 / 0.002 |
| Dedicated worker OCR model initialization | 24.579 |

A later final-source API startup took **184.849 s** for admission warmup,
while focused database/API regressions were running in another process. Its
peak working set was 1.65 GiB with 1.46 GiB physical memory available at the
recorded endpoint. Earlier startup samples were 72.454 and 95.004 s. This
variation is another reason to warm before presenting and to avoid claiming a
controlled cold-start improvement from the individual measurements.

Both submissions were accepted and retained with their jobs, evidence and reports.
The first cold admission overlapped the beginning of a release attempt; that
attempt was stopped before completing ingestion to avoid further model contention.
Its completed runners/logs are retained and resumed separately. The cold-to-warm
comparison is not a controlled causal benchmark or an independent throughput result.
“Cold” means a fresh API process, not an empty disk/model cache or rebooted OS.

SQLite BEGIN/idempotency-lock spans were below one millisecond in these samples;
they do not explain the cold admission delay. PostgreSQL lock correctness was
tested separately in isolated schemas; these timings are not PostgreSQL timings.
The first API peaked near 1.70 GB working set, then about 1.13 GB resident, with
about 1.01 GB physical memory available. The profile worker later peaked near
1.15 GB, with about 0.50 GB available. These counters show resource pressure;
they do not isolate disk, antivirus or page-fault contributions to every wait.

The initial hypothesis of OCR thread oversubscription was **not confirmed**:
EasyOCR already settled at two threads. In a separate local single-photo reading,
imports took 8.531 seconds, Reader initialization 26.282, and readings 6.672 then
3.281. Both produced zero text observations. Explicitly setting two threads before
the second reading did not change the thread count; its improvement cannot be
attributed to that setting. That process peaked at 0.865 GB. Those readings had
no plate text; see the separate readable-photo comparison in the check matrix.
General plate accuracy remains unverified.

The API remained responsive while the dedicated worker initialized: three `/ready`
requests returned 200 in 0.156, 0.000 and 0.015 seconds. The rounded zero is below
the measurement precision, not a claim of zero latency. These are three probes,
not a concurrency/load result. Keep native processing in the separate worker.

The uninterrupted production-build SQLite browser run on current application
code then measured claims/underwriting admission at **5.969/3.687 s**. Backend
pipeline totals were **94.467 s** for the first claim and **9.356 s** with its
supplement; underwriting was **301.279/32.604 s**. The corresponding browser
poll observations were 92.562/9.172 and 300.234/33.157 s; polling starts after
acceptance/queue viewing and is not an exact execution duration. Six uncached
OCR readings alone took **256.878 s** in the underwriting check; one reading
took 125.377 s wall time versus 15.031 s CPU. Worker peak working set was
1.194 GB. These results expose a remaining cold/multi-photo limitation on this
host. Do not describe first-pass OCR as fast or the latency problem as fully
resolved. Warmup, genuine raw-observation reuse and the production frontend
improve the practical demonstration without lowering image/check coverage.

## PostgreSQL observations and redundant corpus reads

The uninterrupted `browser_postgres_qualified` run at `c917da5` used real
PostgreSQL, warmed OCR and the production frontend. Admission was 5.531 s for
one claim image and 16.843 s for six underwriting images. Backend execution
totals, first/supplement, were 132.286/122.922 s for claims and
134.960/176.819 s for underwriting. These are failed model runs, not successful
Gemini processing. Browser poll intervals were 92.485/116.219 s and
84.875/175.343 s; polling begins after intake and viewing the queue.

Cached plate checks took 0.321/0.431/1.072/1.322 s across those four runs.
The full-corpus internal duplicate check instead took
30.362/68.693/71.074/113.702 s, with only 1.031/3.641/7.078/7.281 s of
process CPU. Inspection found that every image reread and decoded every stored
embedding, rebuilt the same matrix and recalculated the same corpus norms.
The available counters do not distinguish network waiting from paging/other IO.

`df19797` replaces these repeated reads with one complete run-local comparison
snapshot. Every new invocation reloads it; no global cache or historical verdict
is reused. Candidate ordering, float64 arithmetic, top-k selection, thresholds
and submission-order attribution remain unchanged. The comparison count now
comes from that same snapshot rather than a separate count query.

A read-only observation on seven existing PostgreSQL images loaded/prepared
1,446 comparison images in **8.332 s**. All seven searches plus independent
copies of the original calculation took **0.341 s**; ordered matches and exact
scores agreed for every image. This is a single diagnostic, not a controlled
speedup estimate. It does not remove the cost of one full cloud corpus read,
initial local model loading or uncached OCR. Private result:
`readiness_20261015/similarity-postgresql.json`.

Reproduce without writes or provider calls, using a new output file:

```powershell
Set-Location D:\projects\FraudLens-2.0\FraudLens-2.0-Backend
.\venv\Scripts\python.exe -X utf8 scripts/profile_similarity.py --db postgresql --case-id '<existing-case-id>' --output '<new-output.json>'
```

## Operational changes and reproduction

The existing admission embedding reuse and raw OCR cache were preserved.
Duplicate-pool counting now uses the one comparison snapshot. Focused tests verify a cached OCR observation is compared
against the current case's registration, and that cache writes release the lock
before another connection reports progress. This investigation adds a lock around
Reader initialization, explicit offline weight-loading behavior, opt-in timing
spans and resource counters. No check weight, threshold or retired status changed.

Every check has a separate timing span. UI stages group fast evidence checks,
show plate OCR separately and distinguish agent adjudication, avoiding a new
cloud write for every fast check. A failed run stays failed despite stored local
findings or subsequent human review. New run metadata records perception-cache,
request-cache, fresh-provider and unavailable observations separately.

Set `$env:FRAUDLENS_PROFILE_STAGES='1'` before the pilot helper to log content-free
JSON timings. Leave it unset for normal operation. Logs contain milliseconds,
CPU time and process/host memory counters, never applicant bodies or credentials.
PowerShell 5 redirected logs can be UTF-16; use `Get-Content`, or detect their BOM.

For a new diagnostic, back up the selected SQLite demo with Python's backup API
into a **new** file, then use:

```powershell
Set-Location D:\projects\FraudLens-2.0\FraudLens-2.0-Backend
$env:FRAUDLENS_PROFILE_STAGES='1'
.\scripts\start_pilot.ps1 -Database sqlite -SqlitePath '<new-isolated-copy.db>' -Port 8001 -NoWorker -NoWarmup
```

In another terminal, use `profile_demo_http.py --database-name <copy-filename>
--output <new-output.json>`. It creates two fictional cases and preserves them;
it does not delete test submissions. Never use the original demo for this write.

For presenting, omit `-NoWarmup`, wait for **Application startup complete**, then
start the helper with `-WorkerOnly` against the same copy and wait for its OCR
readiness. This moves the expensive initialization before applicant submission;
it does not eliminate cold-start cost. Do not build or run ML evaluations during
the demonstration. See DEMO_RUNBOOK.md for the latest browser acceptance result.
