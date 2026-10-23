# Emergency partial-review verification — 23 October 2026

**Useful local review while Gemini remains paused; zero new model requests.**
Both real saved presentation cases were opened in two ordinary Chrome tabs on
the actual application, without intercepted routes or simulated responses.

| Item | Claims | Underwriting |
|---|---|---|
| Saved findings/explanation | Available | Available |
| Main status | Ready for manual review — AI unavailable | Same |
| Stored historical job status | `failed`, unchanged | `failed`, unchanged |
| Derived review summary | `provider_partial`, proven by saved results/snapshot | Same |
| Automated assessment | Incomplete, neutral risk | Incomplete, neutral risk |
| Existing reviewer request/customer update | Verified in actual UI | Verified in actual UI |
| Native Chrome PDF preview and matching download | Verified, 11 pages | Verified, 11 pages |
| New live AI completion | Not performed | Not performed |

New `completed_partial` persistence, new approve/reject/request-evidence paths,
outage handling and actual local-check execution were verified with controlled
fixtures, including two real disposable PostgreSQL cases. No new business-schema
case was created. The photo gate's exact 4/6 contract remains unchanged and its
focused regressions passed; the earlier real-photo qualification remains dated
evidence, not a new submission claim.

- PDFs: [claims](claims.pdf) · [underwriting](underwriting.pdf).
- Native preview: [claims](claims-native-preview.png) · [underwriting](underwriting-native-preview.png).
- Admin: [claims](claims-admin.png) · [underwriting](underwriting-admin.png).
- Customer: [claims](claims-customer.png) · [underwriting](underwriting-customer.png).
- Mobile: [claims](claims-mobile.png) · [underwriting](underwriting-mobile.png).
- Every claims page: [1–4](claims-pages-01-04.png), [5–8](claims-pages-05-08.png), [9–11](claims-pages-09-11.png).
- Every underwriting page: [1–4](underwriting-pages-01-04.png), [5–8](underwriting-pages-05-08.png), [9–11](underwriting-pages-09-11.png).
- [Actual browser receipt](browser-verification.json), [running configuration](operational-state.json),
  [preservation checks](data-preservation.json), [frontend checks](frontend-checks.json).
- [Previously recorded successful claims PDF](../normal_operation/claims-live.pdf),
  [original saved-result receipt](recorded-claims.json).
- [Exact changes and tests](CHANGES.md), [running handover](../FINAL_PRESENTATION_HANDOVER.md).

Renderer `fraudlens-pdf-2026-10-23-v11`; all pages text-extracted, bounds/privacy
checked, rendered and visually inspected. First-page reviewer action is asserted
in the browser verifier. Earlier v9/v10 artifacts remain saved; no old failed run
or human decision is rewritten. The new first-page banner explicitly distinguishes
provider failure from fraud and asks for photo replacement only for a real gap.

Photographs: **Milkmandan~commonswiki**, Chevrolet Classic series, Wikimedia
Commons, **CC BY-SA 3.0**. Reports/screenshots contain resized derivatives.
[Exact attribution, source/license links and evidence limitations](../presentation_assets/README.md).
Retain attribution and license when sharing. All application/reviewer details are
fictional. These photos do not establish current condition, insured loss, readable
mileage, ownership or an Indian registration.

The running dataset is `fraudlens_validation_panel_20261022`; the original pilot
is separate. Use the documented `start_review.ps1 -Dataset Panel|Pilot` commands
and inspect the admin Active dataset banner. The previous successful claims
example remains explicitly **Previously recorded analysis**, with its original
date. There is no successful live underwriting example.

Remaining limitations: AI is paused after the earlier recorded 503s, live
underwriting is unverified, and material evidence gaps remain. Local application
budgets are not Google account entitlement. This patch makes review reliable
without claiming better analysis accuracy.
