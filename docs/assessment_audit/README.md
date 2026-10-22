# Assessment audit artifacts

- [Claims saved-result replay PDF](claims-saved-replay.pdf): ten pages, no fresh inference.
- [Underwriting authored fixture PDF](underwriting-fixture.pdf): ten pages, not live verification.
- [Authored evaluation rows](evaluation.json) and [PDF extraction/layout checks](pdf-inspection.json).

The candidate concern and material-coverage axes are labelled **shadow only**.
Production routing remains unchanged. The claims replay reuses previously saved
findings and the authorized submitted public sample; it does not update its
production snapshot, decision or PDF. Missing frozen reference thumbnails are
shown as unavailable rather than manufactured. Submitted image identity comes
from the saved finding references; the authorized sample thumbnail is supplied
explicitly by the offline replay tool. Underwriting illustrations are authored.

All pages were rendered and inspected. Full-size renders are reproducible with
`scripts/verify_visual_report_layout.py --output ../docs/assessment_audit`.
No native browser PDF painting or new live workflow is claimed in this task.
The browser check intercepts every API call with controlled fixtures and checks
the displayed saved R/C against the same values rendered by the PDF.

See [policy](../ASSESSMENT_POLICY.md), [evaluation](../ASSESSMENT_EVALUATION.md),
[dependency verification](../DEPENDENCY_VERIFICATION.md),
[parameter matrix](../PARAMETER_USAGE_MATRIX.md), and [handover](../ASSESSMENT_AUDIT_HANDOVER.md).
