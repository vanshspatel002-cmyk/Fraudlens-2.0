# Actual isolated claims validation - 22 October 2026

**Claims: Live workflow verified; assessment incomplete. Underwriting: evidence-blocked.**

These are actual artifacts from `case-03dd3c967b5b`, run
`64dcf803f54c43dd8f13a7c039ed7924`, schema `fraudlens_validation_20261022`.
Declarations/applicant details are fictional; the single inspected damage image
is an authorized dataset sample. Four fresh Gemini calls were used. No cache or
manual-review fallback is counted as fresh live processing. Two genuine tools
were requested and executed. No human approval/rejection was submitted.

- [Saved claims PDF - 9 pages](claims-live.pdf)
- [PDF front page](claims-front-page.png)
- [Admin laptop](admin-laptop.png)
- [Admin mobile](admin-mobile.png)
- [Customer status](customer-status.png)
- [Sanitized audit](../live-workflow-audit.json)
- [Diagnostics](../../../GEMINI_DIAGNOSTICS.md)

The processing job completed; missing required context leaves the assessment
neutral/incomplete. The saved agent clear/approve output does not become human
approval or a calibrated fraud score. No underwriting PDF was manufactured:
a legitimate six-view same-vehicle set including odometer/plate was unavailable.

Preview blob and API/browser download hashes match. Every saved PDF page was
extracted, rasterized and visually inspected without clipping/overlap. Headless
Chrome loaded its native PDF frame but native document pixels were not confirmed;
independent PDF rendering of the same saved bytes was visually verified.

The task grant is closed. All 26 unused requests were revoked; original pilot
services remain stopped for normal Gemini generation. These artifacts do not
demonstrate general analysis accuracy or complete underwriting validation.

Local `.gitattributes` treats the PDF/images as binary so Git preserves the exact
saved report bytes and checksum across Windows checkouts.
