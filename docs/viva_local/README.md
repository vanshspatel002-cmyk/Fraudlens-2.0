# FraudLens local viva

- Customer: http://127.0.0.1:5173/dashboard
- Admin: http://127.0.0.1:5173/admin

Use the existing private presentation accounts. Choose Claims or Underwriting
from the customer workspace. The Panel API now queues **Local rules assessment**
jobs by default. Gemini stays paused and is not called. No key or provider probe
is needed by this mode. The installed validator and worker must finish warming;
http://127.0.0.1:8001/ready then returns HTTP 200 even with Gemini paused.

The shared saved band is **review priority**, not a fraud probability:

| Band | Exact local policy |
|---|---|
| HIGH | Completed eligible registration-mismatch **and** image/history concern findings. Investigate both sources independently. |
| MEDIUM | Another completed eligible concern, or material evidence gaps prevent LOW. |
| LOW | Applicable required evidence is sufficient, at least one required local check completed, and no eligible concern remains. |

Gaps alone mean: **“Review required because evidence is insufficient; this is
not a finding of fraud.”** Repeated image/history matches count as one domain.
Garage-only alerts and zero-weight experiments cannot establish claimant risk.
Policy: `local-rules-review-priority-2026-10-27-v1`, implemented in
`FraudLens-2.0-Backend/src/local_rules.py`. The saved contract carries the run,
supporting finding IDs and attribution, coverage, gaps, recommendation and reason.
Frontend and PDF do not calculate a new band. All local priorities retain the
manual desk queue; approval/rejection requires an authorized, acknowledged human
review and written rationale. Technical execution/storage failures remain errors.

## Verified presentation records

| Workflow | Case | Result | Material evidence | PDF |
|---|---|---|---|---|
| Claims, 4 photographs | `case-f400641b2afe` | Completed local rules, MEDIUM | 2/7 sufficient | [Claims](Claims-local-rules.pdf) |
| Underwriting, 6 photographs | `case-4cd077553172` | Completed local rules, MEDIUM | 2/5 sufficient | [Underwriting](Underwriting-local-rules.pdf) |

Both completed on the first worker attempt. The actual local findings include
reuse of archived presentation photographs and recorded editing metadata; both
also have unresolved material evidence. No genuine result was changed to obtain
a desired band. The reviewer requested specific evidence and the owning customer
saw the public outcome. These PDFs include that review. API/worker restart checks
preserved bands, actions, selected run IDs and PDF bytes. Desktop/mobile layouts
and PDF preview/download agreement passed. All 20 report pages rendered and were
visually inspected. Earlier reports and decisions remain untouched.

The earlier underwriting timeout had a 45-second generation deadline. Generation
now has a separate bounded 180-second deadline; metadata and PDF download retain
45 seconds. A simulated 60-second generation succeeds and over-limit operations
still time out. Both real previews opened without a retry in this rehearsal.

Native admission accepted all ten final submission photographs and four further
damaged-car examples; one real animal photograph was withheld across all ten
slots. This small sample is not a calibrated recognition-accuracy claim. LOW,
MEDIUM and HIGH were separately checked with labelled controlled scenarios and
saved-value PDF tests. Gemini generation and successful AI execution are not
claimed. Photographs are by Milkmandan~commonswiki, CC BY-SA 3.0; retain the
[original attribution and source links](../presentation_assets/README.md),
including for the cropped rear mounted-plate detail. The archived US vehicle
does not establish current ownership, fictional Indian registration or mileage.

## Restart

Use separate terminals. From the backend directory:

```powershell
.\scripts\start_review.ps1 -Dataset Panel -Service Api -AssessmentMode local_rules
```

Then, in another backend terminal (the worker inherits the API's configuration):

```powershell
.\scripts\start_review.ps1 -Dataset Panel -Service Worker
```

From the frontend directory, after the existing production build:

```powershell
$env:NITRO_HOST='127.0.0.1'
$env:NITRO_PORT='5173'
& 'D:\tools\FraudLens-node22\node-v22.23.3-win-x64\node.exe' .output/server/index.mjs
```

Rebuild with `./scripts/node22.ps1 build` only when frontend source changes, then
restart the owned frontend process. Do not start a second listener on the same
port. Both backend services use the existing `fraudlens_validation_panel_20261022`
PostgreSQL schema and `outputs/final_presentation/rehearsal` evidence paths.
The original 800-case pilot was not processed. No provider ledger, grant or budget
was changed. Cold model warmup and cloud-database latency still require time;
wait for `/ready` before presenting.

The focused regression runs passed: 119 backend checks, two real disposable
PostgreSQL workflows plus local readiness, final LOW/MEDIUM/HIGH policy/PDF
checks, explicit human-action and idempotency checks, owner-disclosure checks,
frontend production build/TypeScript, real intake browser regressions and report
deadline checks. Suites overlap. Private accounts, tokens and browser logs stay
in ignored backend outputs; [verification.json](verification.json) is sanitized.
