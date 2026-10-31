# Demonstration readiness — 15 October 2026

Use this alongside PILOT_HANDOVER.md and DEMO_RUNBOOK.md. This is a local pilot,
not production SaaS or an accuracy certificate.

- [x] Preserve migrated PostgreSQL, frozen SQLite/research data, evidence and backups.
- [x] Preserve individual reviewer roles, receipt authorization, durable jobs and report history.
- [x] Keep the original API on 8000 untouched.
- [x] Keep the original stopped Gemini ledger and both HTTP 503 records intact.
- [x] Diagnose SDK/request compatibility offline; see GEMINI_DIAGNOSIS.md.
- [x] Add content-free per-check timings and visible processing stages.
- [x] Record vision provenance for new runs; retain unknown freshness for older runs.
- [x] Explain underwriting view labels as unverified applicant declarations.
- [x] Install portable, checksum-verified Node 22.23.3 without changing global Node.
- [x] Bounded backend release: 272 passed, 0 failed, 11 skipped (ten live tests;
  one unchanged corpus sweep). Latest PostgreSQL selection: 11 passed, 68 deselected; separate count compatibility: 1 passed, 78 deselected.
- [x] Uninterrupted SQLite-copy browser workflows, including all four mobile views.
- [ ] Final PostgreSQL browser run with the corrected paper background: in progress.
- [ ] Successful fresh Gemini vision, adjudication and tool continuation: unavailable;
  requires a separately authorized bounded session, not resetting the stopped ledger.
- [ ] Authorized consistent six-view photographs of one vehicle: missing input.
- [x] Actual local OCR match/mismatch comparison and raw-cache reuse on one existing
  visually inspected project photo. It contains two vehicles; identity attribution
  and general accuracy remain unverified. A separate Wikimedia download returned 403.
- [ ] Signed C2PA example: no local signed fixture or installed bindings.
- [ ] Independent detection accuracy, calibrated probabilities and claimant intent:
  unsupported. Historical synthetic examples and mock replies do not establish them.
- [ ] Manual OS print dialog, screen reader and exhaustive device/security coverage:
  unverified. Headless PDFs verify rendered content only.
- [ ] Production tenancy, identity recovery/MFA, least-privilege DB login, shared
  evidence/budgets, supervision/alerts, security/load/privacy review and independent
  validation: outstanding; see the main handover.

Historical failed jobs remain failed after deterministic findings or human actions.
Report history stays immutable. A human's fictional demo approval is not a successful
agent run, a real coverage determination or a detector validation result.
