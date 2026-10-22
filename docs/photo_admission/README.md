# Admission verification artifacts

These artifacts verify upload admission, not live automated assessment accuracy.
No Gemini requests were made.

- `real-local-results.json`: native CPU CLIP v2 smoke, individual scores/states and warm batch throughput.
- `real-local-results-v1.json`: earlier development failure evidence; not the active policy.
- `startup-warmup.json`: complete cold CLIP/text/OCR readiness, if available.
- `controlled-timings.json`: actual isolated SQLite/API persistence with controlled semantic inference.
- `browser-results.json`: both forms at 1365 px and touch-enabled 390 px; all API traffic intercepted.
- `verification.json`: final regression/build/accounting summary.

Screenshots carry a visible CONTROLLED BROWSER FIXTURE label. They contain
fictional form values and placeholder pixels, with simulated admission results:

| Form | Desktop upload panel | Narrow mobile upload panel |
| --- | --- | --- |
| Claims | [four slots](claims-photos-1365.png) | [four slots](claims-photos-390.png) |
| Underwriting | [six slots](underwriting-photos-1365.png) | [six slots](underwriting-photos-390.png) |

Full-page captures use the corresponding names without `-photos`.
The cropped panels hide sticky navigation only during the screenshot so its
overlay cannot obscure the fixture caption; application behavior is unchanged.

See [policy/API guide](../PHOTO_ADMISSION.md) and [handover](../PHOTO_ADMISSION_HANDOVER.md).
