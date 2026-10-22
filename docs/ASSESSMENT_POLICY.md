# Assessment policy — production and candidate

Baseline inspected: `f35aa755db6d5cc88c7746a3672a1aa118761ea1`, branch
`repair/analysis-pipeline-20261020`, 22 October 2026. Existing staged documentation,
API CORS and frontend transport/evidence edits were preserved. No AGENTS.md found
in the repository or parent directories. Existing handovers and normal-operation
documents were read first. No generation, batch processing or provider-control
mutation is part of this audit.

Production remains model-selected routing with the material-evidence guard.
The historical additive baseline and frozen research results are unchanged.
`grouped-two-axis-2026-10-22-v1` is **SHADOW ONLY**, not promoted. It cannot change
the production risk indicator, model recommendation or human decision.

For each check, e is 1 only when at least one completed, eligible, positive-weight
concern is saved, otherwise 0. This intentionally avoids treating heuristic model
confidence as calibrated strength or multiplying reliability/confidence twice.
Repeated images/findings cannot increase a check's strength. Each group uses
q = max(a × e); R = 1 − product(1 − q). R is a bounded concern index, not a
probability or an independence claim. Missing evidence itself adds no concern.

| Group | Checks and candidate a |
|---|---|
| Image reuse | internal_duplicate .8; external_corpus .8 |
| Identity | plate_ocr .6; entity_graph .4 |
| Incident | scene_consistency .6; damage_plausibility .4 |
| Vehicle history | baseline_linkage .4; severity_progression .4 |
| Provenance | exif_metadata .3; c2pa_credentials .3 |

These are conservative authored policy parameters, not fitted accuracy weights.
All other checks have a=0. Zero-weight experiments remain excluded. Garage-level
concerns are retained separately and can request documentary review without
raising the claimant index. PASS resolves usable requirements but earns no
arbitrary negative credit to cancel concerns.

Every applicable material requirement has coverage weight b=1. C is the number
with sufficient usable evidence divided by the applicable material denominator.
The material requirements come from the saved, case-type-specific production
check policy and `coverage_policy.assess`; claims includes amount/history rules,
underwriting excludes claims economics and includes its own view/baseline checks.
Zero-weight view/baseline experiments cannot verify same-vehicle identity or
fabricated baselines. Submission-file acceptance is distinct from genuine
view/vehicle authentication, an unsupported capability. No applicable material
denominator yields not assessable, never 100% coverage.

Candidate clear requires a recorded finding basis, a nonzero denominator, every
applicable mandatory requirement sufficient, C≥.60 and R<.20, with no garage
alert. Gaps request evidence; R≥.20 requests desk review; R≥.75 investigation.
These operating points (.20/.45/.75 categories and .60 coverage) are **unvalidated**.
All mandatory gaps override the average, making a high C insufficient to clear.
Insufficient inputs always abstain regardless of model approval.

A simpler group maximum was compared alongside product pooling. It avoids
cross-group accumulation but loses the distinction between one and several
different supported concern groups. Neither is independently validated here.
Authored safety/duplication tests support implementation invariants, not promotion.
There is no calibrated prior, log odds, measured likelihood ratio or fraud score.

New explanations persist the complete candidate under `shadow_assessment`:
version/status, case/run/evidence references, checks, finding IDs/attribution,
exclusions/thresholds, e/a/group maxima, coverage terms/mandatory gaps, candidate
recommendation, original model recommendation and effective production routing.
Existing audit/report JSON persistence carries this without a database migration.
Frontend and PDF read this saved object, never recompute it. Old snapshots have
no reconstructed candidate. Renderer v6 adds labelled candidate tables; v1–v5
artifacts and rendering paths are preserved.

Historical assertions corrected: the pilot is PostgreSQL (Supabase database),
not Supabase Auth or production SQLite; the active Gemini profile omits explicit
temperature, uses the full JSON schema, bounded shared quota controls and no
normal key rotation. Missing EXIF/C2PA is inconclusive, not verified authenticity.
Installed packages are not all active integrations. Check weights belong to the
research baseline; production does not add them. Slots do not authenticate six
views of one vehicle. Actual tools are listed in `src/agent/policy.py`, with garage
history excluded for underwriting. Exact weights/default thresholds appear in
[the check matrix](CHECK_VERIFICATION_MATRIX.md).

Performance: prior measured acceptance 42.765 s, processing 164.601 s and final
cold warmup 663.875 s. Admission already passes its embedding to ingestion;
there is no second mandatory embedding to remove. API CLIP and worker OCR are
different model roles; splitting them does not itself prove duplication. Cold
imports, memory pressure and a 78.248 s experimental classifier remain material.
No safe speedup is claimed from inspection alone. This audit adds no timeout
increase, check removal, stale result serving or speculative concurrency change.
Performance optimization remains open pending a controlled resource profile.
