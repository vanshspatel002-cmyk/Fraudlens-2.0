# Final presentation artifacts — real saved cases, 23 October 2026

**Both initial photo submissions, local checks, PDFs and reviewer/customer updates
were verified. Fresh live AI completion is blocked by Gemini HTTP 503.** Neither
report is proof of successful fresh model execution or a fraud determination.

- [Claims PDF — 11 pages](claims.pdf), [first page](claims-front-page.png),
  [native Chrome preview](claims-pdf-dialog.png), [verification](claims-verification.json).
- [Underwriting PDF — 11 pages](underwriting.pdf), [first page](underwriting-front-page.png),
  [native Chrome preview](underwriting-pdf-dialog.png), [verification](underwriting-verification.json).
- [Claims admin](claims-admin-assessment.png), [mobile](claims-admin-mobile.png),
  [customer outcome](claims-customer-outcome.png), [authorized original](claims-original-evidence.png).
- [Underwriting admin](underwriting-admin-assessment.png), [mobile](underwriting-admin-mobile.png),
  [customer outcome](underwriting-customer-outcome.png), [authorized original](underwriting-original-evidence.png).
- [Claims OCR](claims-ocr-graphic.png), [metadata](claims-metadata-graphic.png).
  Underwriting [OCR](underwriting-ocr-graphic.png), [metadata](underwriting-metadata-graphic.png).
- All claims pages: [1–4](claims-pages-01-04.png), [5–8](claims-pages-05-08.png),
  [9–11](claims-pages-09-11.png). All underwriting pages:
  [1–4](underwriting-pages-01-04.png), [5–8](underwriting-pages-05-08.png),
  [9–11](underwriting-pages-09-11.png).

Renderer `fraudlens-pdf-2026-10-23-v9`. All 22 pages were rendered and visually
inspected, with text/bounds/privacy checks. Preview/download bytes match and
earlier artifacts retain their original hashes. No analysis reruns on PDF access.
The two new cases are stored in isolated `fraudlens_validation_panel_20261022`;
the final running service is restored to `fraudlens_pilot`. The handover explains
how to inspect saved isolated cases without enabling generation there.

Photographs in these PDFs/screenshots are by **Milkmandan~commonswiki**,
Wikimedia Commons Chevrolet Classic series, licensed **CC BY-SA 3.0**. Source
photographs are unmodified; reports contain resized derivatives. Preserve this
attribution/license when sharing. [Exact source/license/file mapping and
limitations](../presentation_assets/README.md), [provenance](../presentation_assets/provenance.json).
Same-car support comes from the published series and visual details, not verified
ownership/identity/current condition. Dashboard is off; the fictional declarations
do not authenticate the public US registration or establish an insured loss.

No credentials, receipt secrets or real applicant details are published. All
applicant/reviewer actions in these new cases are explicitly fictional.

Operational receipts: [requests](request-accounting.json), [same-context sessions](sessions-verification.json),
[native local admission](native-final.json), [frontend checks](frontend-checks.json),
[final release checks](release-checks.json), [original data](original-data-verification.json),
[final services](operational-state.json), [restored startup](normal-startup.json).

Read the [handover](../FINAL_PRESENTATION_HANDOVER.md) and
[verification/limitations](../FINAL_PRESENTATION_VERIFICATION.md). For a provider
outage, the unchanged [earlier successful claims report](../normal_operation/claims-live.pdf)
is explicitly a historical saved-case fallback. There is no successfully completed
live underwriting fallback. No bulk reprocessing was started.
