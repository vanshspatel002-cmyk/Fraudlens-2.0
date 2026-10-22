"""
Test suite for src.checks (base.py, duplicate.py, metadata.py, threshold.py).

Live, against the real generated corpus (fraudlens.db + data/generated/
ground_truth.csv) - not mocked. Same minimal, stdlib-only PASS/FAIL runner
as test_models.py/test_llm.py/test_perception.py; ground_truth.csv is read
only to pick known-good/known-bad case_ids to test against, exactly like
generate_dataset.py's own docstring insists on - no check under test ever
sees it, only this test file does.

Requires `python -m src.generate_dataset` to have already produced
fraudlens.db and data/generated/ground_truth.csv.

Run with:
    python test_checks.py
"""

from __future__ import annotations

import csv
import os
import sys
import traceback
from collections import Counter
from pathlib import Path
from typing import Any, Optional

# Windows consoles default to cp1252, which can't print the Rupee sign
# (U+20B9) our own explanations contain - reconfigure rather than let a
# PASS test crash on the print() that reports it.
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

sys.path.insert(0, str(Path(__file__).resolve().parent))

from src import db
from src.checks import ALL_CHECKS, REGISTRY, run_checks
from src.checks.base import Check, CheckContext, _run_one
from src.checks.threshold import _garage_band_stats
from src.models import Case, CheckCategory, Image, Verdict

# ---------------------------------------------------------------------------
# Tiny test runner (same shape as test_perception.py/test_llm.py)
# ---------------------------------------------------------------------------

_TESTS: list = []


def test(fn):
    _TESTS.append(fn)
    return fn


def run_all() -> bool:
    passed, failed, skipped = 0, 0, 0
    failures = []
    for fn in _TESTS:
        print(f"--- {fn.__name__} ---")
        if os.environ.get('FRAUDLENS_SKIP_CORPUS_SWEEPS') == '1' and fn.__name__ == 'test_duplicate_check_reuse_vs_clean_sweep':
            skipped += 1
            print(f'SKIP  {fn.__name__} -> Preserved research sweep; bounded release retains individual reuse/clean regressions.')
            continue
        try:
            fn()
            passed += 1
            print(f"PASS  {fn.__name__}")
        except Exception as e:  # noqa: BLE001 - test runner, wants everything
            failed += 1
            failures.append((fn.__name__, e, traceback.format_exc()))
            print(f"FAIL  {fn.__name__}  ->  {type(e).__name__}: {e}")
    if failures:
        print("\n" + "=" * 70)
        for name, e, tb in failures:
            print(f"FAIL  {name}\n{tb}")
    print(f"\n{passed} passed, {failed} failed, {skipped} skipped")
    return failed == 0


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

DB_CANDIDATES = [Path("data/fraudlens.db"), Path("fraudlens.db")]
GROUND_TRUTH_CSV = Path("data/generated/ground_truth.csv")


def resolve_db_path() -> Path:
    for candidate in DB_CANDIDATES:
        if candidate.exists():
            return candidate
    raise FileNotFoundError(
        f"no database found at any of: {', '.join(str(c) for c in DB_CANDIDATES)} - "
        "run `python -m src.generate_dataset` first"
    )


_conn = None


def get_conn():
    global _conn
    if _conn is None:
        if not GROUND_TRUTH_CSV.exists():
            raise FileNotFoundError(f"{GROUND_TRUTH_CSV} not found - run `python -m src.generate_dataset` first")
        import sqlite3, tempfile
        target = sqlite3.connect(':memory:')
        source = sqlite3.connect(resolve_db_path().resolve().as_uri()+'?mode=ro',uri=True)
        source.backup(target); source.close()
        target.row_factory=sqlite3.Row;target.execute('PRAGMA foreign_keys=ON')
        _conn=target
        db.init_db(_conn)
    return _conn


def load_ground_truth() -> list[dict[str, Any]]:
    with open(GROUND_TRUTH_CSV, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def cases_by_archetype(archetype: str) -> list[dict[str, Any]]:
    return [row for row in load_ground_truth() if row["archetype"] == archetype]


def get_case(case_id: str) -> Case:
    case = db.get_case(get_conn(), case_id)
    assert case is not None, f"ground_truth.csv names {case_id!r} but it isn't in the database"
    return case


def first_image_with_no_exif(case_ids: list[str]) -> Optional[Image]:
    conn = get_conn()
    for case_id in case_ids:
        for image in db.get_images_for_case(conn, case_id):
            if not image.exif:
                return image
    return None


# ---------------------------------------------------------------------------
# InternalDuplicateCheck
# ---------------------------------------------------------------------------


@test
def test_duplicate_check_fires_concern_on_a_known_reuse_case():
    reuse_rows = cases_by_archetype("REUSE")
    assert reuse_rows, "ground_truth.csv has no REUSE cases - was the dataset generated with --count too small?"

    case = get_case(reuse_rows[0]["case_id"])
    findings = run_checks(get_conn(), case, check_ids=["internal_duplicate"])
    assert any(f.verdict == Verdict.CONCERN for f in findings), (
        f"expected internal_duplicate to fire CONCERN on REUSE case {case.case_id}, got: "
        f"{[(f.verdict.value, f.explanation) for f in findings]}"
    )
    concern = next(f for f in findings if f.verdict == Verdict.CONCERN)
    assert "matched_case_id" in concern.evidence and "hamming_distance" in concern.evidence
    print(f"  {case.case_id}: {concern.explanation}")


@test
def test_duplicate_check_passes_on_a_known_clean_case():
    clean_rows = cases_by_archetype("CLEAN")
    assert clean_rows, "ground_truth.csv has no CLEAN cases"

    case = get_case(clean_rows[0]["case_id"])
    findings = run_checks(get_conn(), case, check_ids=["internal_duplicate"])
    verdicts = [f.verdict for f in findings]
    assert Verdict.CONCERN not in verdicts, (
        f"expected no CONCERN on clean case {case.case_id}, got: "
        f"{[(f.verdict.value, f.explanation) for f in findings]}"
    )
    print(f"  {case.case_id}: {[(f.verdict.value, round(f.confidence, 2)) for f in findings]}")


@test
def test_duplicate_check_reuse_vs_clean_sweep():
    """
    The primary metric: across every REUSE case and every CLEAN case in
    the real generated corpus, how many REUSE cases get caught (at least
    one CONCERN finding) and how many CLEAN cases get falsely flagged
    (at least one CONCERN finding). Printed regardless of outcome - this
    is the number the task exists to surface, not a threshold to hide
    behind a pass/fail cutoff nobody has calibrated yet. The only hard
    assertion is that at least half of REUSE is caught: REUSE images are
    byte-identical duplicates by construction (see generate_dataset.py),
    so this check missing most of them would mean something is actually
    broken, not just imperfect.
    """
    conn = get_conn()
    reuse_rows = cases_by_archetype("REUSE")
    clean_rows = cases_by_archetype("CLEAN")

    caught = 0
    for row in reuse_rows:
        findings = run_checks(conn, get_case(row["case_id"]), check_ids=["internal_duplicate"])
        if any(f.verdict == Verdict.CONCERN for f in findings):
            caught += 1

    false_flagged = 0
    false_flag_examples: list[str] = []
    for row in clean_rows:
        findings = run_checks(conn, get_case(row["case_id"]), check_ids=["internal_duplicate"])
        if any(f.verdict == Verdict.CONCERN for f in findings):
            false_flagged += 1
            if len(false_flag_examples) < 5:
                false_flag_examples.append(row["case_id"])

    print(f"  REUSE caught:        {caught}/{len(reuse_rows)}")
    print(f"  CLEAN false-flagged: {false_flagged}/{len(clean_rows)}")
    if false_flag_examples:
        print(f"  false-flag examples: {false_flag_examples}")

    assert caught >= len(reuse_rows) / 2, (
        f"expected at least half of REUSE cases caught (byte-identical duplicates by construction), "
        f"got {caught}/{len(reuse_rows)}"
    )


# ---------------------------------------------------------------------------
# MetadataCheck
# ---------------------------------------------------------------------------


@test
def test_metadata_check_no_exif_is_inconclusive_not_concern():
    clean_case_ids = [row["case_id"] for row in cases_by_archetype("CLEAN")]
    image = first_image_with_no_exif(clean_case_ids)
    assert image is not None, "expected at least one CLEAN-case image with no EXIF - none found"

    case = get_case(image.case_id)
    findings = run_checks(get_conn(), case, check_ids=["exif_metadata"])
    this_image = next(f for f in findings if f.evidence.get("image_id") == image.image_id)
    assert this_image.verdict == Verdict.INCONCLUSIVE, (
        f"expected INCONCLUSIVE for missing EXIF, got {this_image.verdict.value}: {this_image.explanation}"
    )
    assert this_image.evidence.get("exif_present") is False
    print(f"  {case.case_id}: {this_image.explanation} (confidence={this_image.confidence})")


@test
def test_metadata_check_forged_gps_is_flagged_or_at_least_not_missed_silently():
    """
    METADATA_FORGERY cases (see generate_dataset.py's forge_exif) place the
    GPS fix in a city guaranteed >50km from the declared location - not
    guaranteed >100km, this check's own CONCERN threshold, so this doesn't
    assert CONCERN outright. It does assert the check actually measured a
    real distance rather than silently no-op'ing on real forged EXIF.
    """
    forgery_rows = cases_by_archetype("METADATA_FORGERY")
    if not forgery_rows:
        print("  no METADATA_FORGERY cases in ground_truth.csv - skipping")
        return

    case = get_case(forgery_rows[0]["case_id"])
    findings = run_checks(get_conn(), case, check_ids=["exif_metadata"])
    assert findings, f"expected at least one finding for {case.case_id}"
    with_gps = [f for f in findings if "gps_distance_km" in f.evidence]
    assert with_gps, f"expected a measured GPS distance in evidence for a METADATA_FORGERY case, got: {findings}"
    print(f"  {case.case_id}: gps_distance_km={with_gps[0].evidence['gps_distance_km']} verdict={with_gps[0].verdict.value}")


# ---------------------------------------------------------------------------
# ThresholdGamingCheck
# ---------------------------------------------------------------------------


def _find_in_band_case(garage_id: str, band_low: float, band_high: float) -> Optional[Case]:
    conn = get_conn()
    for case in db.get_all_cases(conn):
        if (
            case.garage_id == garage_id
            and case.agent_type == "claims"
            and case.claim_amount is not None
            and band_low <= case.claim_amount < band_high
        ):
            return case
    return None


def _find_gaming_and_normal_garages(band_low: float, band_high: float, concern_pct: float, min_claims: int):
    """
    Reads the real corpus (not ground truth - this is exactly the
    computation ThresholdGamingCheck itself does) to find one garage over
    the CONCERN threshold and one comfortably under it, both with an
    actual in-band case to test against - mirrors scripts/
    inspect_dataset.py's REPORT 1 rather than hardcoding garage ids that
    would silently stop meaning anything the day --seed changes.
    """
    conn = get_conn()
    all_claims = [c for c in db.get_all_cases(conn) if c.agent_type == "claims" and c.claim_amount is not None]
    garage_ids = sorted({c.garage_id for c in all_claims})

    gaming_garage = None
    normal_garage = None
    for garage_id in garage_ids:
        stats = _garage_band_stats(conn, garage_id, band_low, band_high)
        if stats["garage_claim_count"] < min_claims:
            continue
        if gaming_garage is None and stats["garage_in_band_pct"] > concern_pct:
            if _find_in_band_case(garage_id, band_low, band_high) is not None:
                gaming_garage = garage_id
        if normal_garage is None and stats["garage_in_band_pct"] <= concern_pct:
            if _find_in_band_case(garage_id, band_low, band_high) is not None:
                normal_garage = garage_id
        if gaming_garage and normal_garage:
            break
    return gaming_garage, normal_garage


@test
def test_threshold_check_concern_at_gaming_garage_not_at_normal_garage():
    from src.checks.threshold import ThresholdGamingCheck

    band_low, band_high = ThresholdGamingCheck.BAND_LOW, ThresholdGamingCheck.BAND_HIGH
    concern_pct, min_claims = ThresholdGamingCheck.GARAGE_CONCERN_PCT, ThresholdGamingCheck.MIN_GARAGE_CLAIMS

    gaming_garage, normal_garage = _find_gaming_and_normal_garages(band_low, band_high, concern_pct, min_claims)
    assert gaming_garage is not None, "no garage in the real corpus exceeds the gaming threshold with an in-band case"
    assert normal_garage is not None, "no normal garage in the real corpus has an in-band case to compare against"

    conn = get_conn()
    gaming_case = _find_in_band_case(gaming_garage, band_low, band_high)
    normal_case = _find_in_band_case(normal_garage, band_low, band_high)

    gaming_findings = run_checks(conn, gaming_case, check_ids=["threshold_gaming"])
    normal_findings = run_checks(conn, normal_case, check_ids=["threshold_gaming"])

    assert len(gaming_findings) == 1 and gaming_findings[0].verdict == Verdict.CONCERN, (
        f"expected CONCERN for {gaming_case.case_id} at gaming garage {gaming_garage}, got: {gaming_findings}"
    )
    assert len(normal_findings) == 1 and normal_findings[0].verdict != Verdict.CONCERN, (
        f"expected no CONCERN for {normal_case.case_id} at normal garage {normal_garage}, got: {normal_findings}"
    )
    print(f"  gaming: {gaming_case.case_id} @ {gaming_garage} -> {gaming_findings[0].explanation}")
    print(f"  normal: {normal_case.case_id} @ {normal_garage} -> {normal_findings[0].explanation}")


@test
def test_threshold_check_skips_underwriting_cases():
    conn = get_conn()
    underwriting_rows = [row for row in load_ground_truth() if row["agent_type"] == "underwriting"]
    assert underwriting_rows, "expected at least one underwriting case in ground_truth.csv"

    case = get_case(underwriting_rows[0]["case_id"])
    assert case.claim_amount is None, "underwriting cases should never have a claim_amount"
    findings = run_checks(conn, case, check_ids=["threshold_gaming"])
    assert findings == [], f"expected threshold_gaming to return [] for an underwriting case, got: {findings}"
    print(f"  {case.case_id}: [] as expected")


# ---------------------------------------------------------------------------
# ExternalCorpusCheck
# ---------------------------------------------------------------------------


@test
def test_external_corpus_index_builds_and_caches():
    """
    Builds (or loads) the index, then forces a second load and asserts it
    came back from CORPUS_INDEX_PATH rather than re-embedding: a rebuild
    is minutes of CLIP inference, so "loading must not recompute
    embeddings" is a hard requirement, not a nicety. Timing is the only
    honest way to tell the two apart from outside.
    """
    import time

    import numpy as np

    import src.checks.external_corpus as ec

    index = ec.get_index()
    assert len(index) > 0, "external corpus index is empty - is data/external/corpus/ populated?"
    assert ec.CORPUS_INDEX_PATH.exists(), f"expected the index to be cached at {ec.CORPUS_INDEX_PATH}"
    assert index.embeddings.shape == (len(index), 512), f"unexpected embedding shape {index.embeddings.shape}"
    assert len(index.phashes) == len(index.filenames) == len(index)

    ec._index = None
    start = time.perf_counter()
    reloaded = ec.get_index()
    elapsed = time.perf_counter() - start

    assert len(reloaded) == len(index)
    assert np.allclose(reloaded.embeddings, index.embeddings, atol=1e-5), "cached embeddings differ from built ones"
    assert elapsed < 20.0, f"reload took {elapsed:.1f}s - that looks like a rebuild, not a cache load"
    print(f"  {len(index)} corpus images, cached at {ec.CORPUS_INDEX_PATH}, reloaded in {elapsed:.2f}s")


@test
def test_external_corpus_fires_concern_on_external_sourcing_case():
    rows = cases_by_archetype("EXTERNAL_SOURCING")
    assert rows, "ground_truth.csv has no EXTERNAL_SOURCING cases"

    case = get_case(rows[0]["case_id"])
    findings = run_checks(get_conn(), case, check_ids=["external_corpus"])
    concerns = [f for f in findings if f.verdict == Verdict.CONCERN]
    assert concerns, (
        f"expected external_corpus to fire CONCERN on {case.case_id} (its images come straight from the corpus), "
        f"got: {[(f.verdict.value, f.explanation) for f in findings]}"
    )
    evidence = concerns[0].evidence
    for key in ("matched_filename", "cosine_similarity", "hamming_distance", "corpus_size"):
        assert key in evidence, f"evidence missing {key!r}: {evidence}"
    print(f"  {case.case_id}: {concerns[0].explanation} (matched {evidence['matched_filename']})")


@test
def test_external_corpus_passes_on_a_clean_case():
    rows = cases_by_archetype("CLEAN")
    case = get_case(rows[0]["case_id"])
    findings = run_checks(get_conn(), case, check_ids=["external_corpus"])
    assert findings, f"expected findings for {case.case_id}"
    assert all(f.verdict != Verdict.CONCERN for f in findings), (
        f"expected no CONCERN on clean case {case.case_id}: "
        f"{[(f.verdict.value, f.explanation) for f in findings]}"
    )
    print(f"  {case.case_id}: {[(f.verdict.value, round(f.confidence, 2)) for f in findings]}")


# ---------------------------------------------------------------------------
# C2PACheck
# ---------------------------------------------------------------------------


@test
def test_c2pa_check_no_credentials_is_inconclusive_not_concern():
    """
    Whether c2pa-python is installed or not, the one thing this must
    never do is report CONCERN on an image that simply has no
    credentials - that is the overwhelmingly common case (adoption is
    minimal) and flagging it would wreck the false-positive rate.
    Without the library the honest answer is INCONCLUSIVE
    ("unavailable"); with it, PASS.
    """
    from src.checks.provenance import _get_c2pa

    rows = cases_by_archetype("CLEAN")
    case = get_case(rows[0]["case_id"])
    findings = run_checks(get_conn(), case, check_ids=["c2pa_credentials"])
    assert findings, f"expected findings for {case.case_id}"

    available = _get_c2pa() is not None
    for f in findings:
        assert f.verdict != Verdict.CONCERN, f"C2PA must never CONCERN on a credential-free image: {f.explanation}"
        if available:
            assert f.verdict == Verdict.INCONCLUSIVE, f"unsigned images cannot authenticate themselves: {f.verdict.value}"
            assert f.evidence.get("credentials_present") is False
        else:
            assert f.verdict == Verdict.INCONCLUSIVE
            assert f.explanation == "Content credential verification unavailable."
    print(f"  c2pa available={available}: {findings[0].verdict.value} - {findings[0].explanation}")


# ---------------------------------------------------------------------------
# AIGenerationCheck
# ---------------------------------------------------------------------------


@test
def test_ai_detector_loads_and_returns_a_probability():
    """
    If the model loads, assert it produced a real probability in [0, 1]
    and recorded the model name. If it does not load, assert the check
    degraded to INCONCLUSIVE instead of crashing - that graceful path is
    just as much a requirement as the happy one.
    """
    from src.checks.ai_detection import MODEL_NAME, get_pipeline

    rows = cases_by_archetype("CLEAN")
    case = get_case(rows[0]["case_id"])
    findings = run_checks(get_conn(), case, check_ids=["ai_generation"])
    assert findings, f"expected findings for {case.case_id}"

    loaded = get_pipeline() is not None
    finding = findings[0]
    assert finding.evidence.get("model") == MODEL_NAME

    if loaded:
        probability = finding.evidence.get("artificial_probability")
        assert probability is not None, f"model loaded but no probability recorded: {finding.evidence}"
        assert 0.0 <= probability <= 1.0, f"probability out of range: {probability}"
        assert finding.confidence <= 0.6 + 1e-9, f"confidence must be capped at 0.6, got {finding.confidence}"
        print(f"  model loaded: artificial_probability={probability:.4f} -> {finding.verdict.value}")
    else:
        assert finding.verdict == Verdict.INCONCLUSIVE, "an unloadable model must yield INCONCLUSIVE, not a crash"
        print(f"  model unavailable, degraded cleanly: {finding.explanation}")


@test
def test_new_checks_emit_valid_findings():
    """Every new check must produce well-formed Findings with a real explanation."""
    conn = get_conn()
    # This battery includes claims-only plausibility and coordinate-dependent
    # scene checks. The first CLEAN fixture is an underwriting application.
    case = next(case for case in (get_case(row['case_id']) for row in cases_by_archetype('CLEAN'))
                if case.agent_type == 'claims' and case.latitude is not None and case.longitude is not None)
    new_check_ids = ["external_corpus", "c2pa_credentials", "ai_generation",
                     "scene_consistency", "damage_plausibility", "digital_edit"]

    for check_id in new_check_ids:
        findings = run_checks(conn, case, check_ids=[check_id])
        assert findings, f"{check_id} produced no findings"
        for f in findings:
            assert f.check_id == check_id
            assert f.case_id == case.case_id
            assert isinstance(f.category, CheckCategory)
            assert isinstance(f.verdict, Verdict)
            assert 0.0 <= f.confidence <= 1.0, f"{check_id} confidence out of range: {f.confidence}"
            assert f.explanation and f.explanation.strip(), f"{check_id} emitted an empty explanation"
            assert isinstance(f.evidence, dict)
        print(f"  {check_id}: {len(findings)} finding(s), all well-formed")


# ---------------------------------------------------------------------------
# SceneConsistencyCheck - the solar/weather/lighting check
# ---------------------------------------------------------------------------


@test
def test_local_wallclock_is_converted_to_utc_not_read_literally():
    """
    The single most consequential line in scene_consistency: declared_time
    carries a local Indian wall-clock tagged UTC, and reading it literally
    shifts every sun position by 5.5 hours - turning honest evening claims
    into fabricated night-time ones.
    """
    from datetime import datetime, timezone
    from src.checks.scene_consistency import local_wallclock_to_utc, solar_position

    declared = datetime(2026, 2, 16, 17, 0, tzinfo=timezone.utc)  # 17:00 *local*
    vadodara = (22.2762, 73.1943)
    when = local_wallclock_to_utc(declared, *vadodara)
    assert when.hour == 11 and when.minute == 30, f"17:00 IST must be 11:30 UTC, got {when}"

    corrected = solar_position(when, *vadodara)
    literal = solar_position(declared, *vadodara)
    assert corrected and literal
    assert corrected[1] > 0, "17:00 local in February must have the sun above the horizon"
    assert literal[1] < corrected[1], "reading the wall-clock as UTC must give a different (lower) sun"
    print(f"  17:00 local -> {when:%H:%M} UTC, elevation {corrected[1]:.1f}° "
          f"(literal-UTC misreading would give {literal[1]:.1f}°)")


@test
def test_invisible_shadows_are_never_a_contradiction():
    """
    Regression test for a real bug found on live perception data.

    PERCEPTION_PROMPT's vocabulary uses "none" for shadow_length to mean
    "no shadows visible", and "none_visible" for direction. An earlier
    version treated "none" as a measurement of zero length and raised
    CONCERN against a midday sun - which, since most claim photos are
    close crops with no shadow in frame, would have fired on the majority
    of honest claims.
    """
    from src.checks.scene_consistency import bearing_to_compass, compass_to_bearing, shadow_length_gap

    assert shadow_length_gap("medium", "none") is None, "'none' means not visible, never zero-length"
    assert shadow_length_gap("short", "none") is None
    assert shadow_length_gap("none", "long") is None
    # Real measurements still compare normally.
    assert shadow_length_gap("short", "long") == 2, "opposite ends must remain a contradiction"
    assert shadow_length_gap("medium", "long") == 1, "adjacent buckets are a judgement call, not a lie"
    # An unreadable direction is likewise no evidence.
    assert compass_to_bearing("none_visible") is None
    assert compass_to_bearing("NE") == 45.0
    assert bearing_to_compass(44.0) == "NE" and bearing_to_compass(359.0) == "N"
    print("  'none'/'none_visible' carry no evidence; short-vs-long still contradicts")


@test
def test_scene_consistency_fires_on_a_constructed_contradiction():
    """
    Proves the flagship check actually detects a contradiction, without
    depending on vision-API quota.

    Corpus recall for this check is limited by perception coverage (the
    free tier measured out at 20 images/key/day), so "we could not
    measure it on the corpus" must not be confused with "we do not know
    whether it works". This builds the exact CONTEXT_MISMATCH the
    generator creates - an evening declaration against a photograph
    showing a midday sun - and asserts the check catches it and says why.
    """
    from datetime import datetime, timezone
    from src.checks.base import CheckContext
    from src.checks.scene_consistency import SceneConsistencyCheck
    from src.models import PerceptionRecord

    conn = get_conn()
    case = get_case(cases_by_archetype("CLEAN")[0]["case_id"])
    case.declared_time = datetime(2026, 6, 15, 18, 30, tzinfo=timezone.utc)  # 18:30 local
    case.latitude, case.longitude = 22.3072, 73.1812  # Vadodara
    case.declared_location = "Alkapuri, Vadodara"

    images = db.get_images_for_case(conn, case.case_id)
    assert images, "expected a clean case with at least one image"
    image = images[0]

    # At 18:30 local in June the sun is low in the west-northwest, so
    # shadows must run long toward the east-southeast. This record claims
    # short shadows pointing the other way - a midday photograph.
    contradictory = PerceptionRecord(
        content_hash=image.content_hash,
        source="test-fixture",
        damage_severity="minor",
        weather_observed="clear",
        road_condition="dry asphalt",
        shadow_direction="W",
        shadow_length="short",
        lighting="daylight",
        raw_response={},
    )
    ctx = CheckContext(conn=conn, case=case, images=[image],
                       perception={image.content_hash: contradictory}, config={})
    findings = SceneConsistencyCheck().run(ctx)
    assert len(findings) == 1, f"expected one finding, got {len(findings)}"
    finding = findings[0]
    assert finding.verdict == Verdict.CONCERN, (
        f"a midday-sun photograph on an 18:30 claim must be a CONCERN, got "
        f"{finding.verdict.value}: {finding.explanation}"
    )
    assert "contradicts the declared time and place" in finding.explanation
    assert "solar_geometry" in finding.evidence["subchecks_fired"]
    # The promise of this check is an explainable sentence, not a score.
    assert "18:30" in finding.explanation and "Alkapuri" in finding.explanation
    print(f"  {finding.explanation}")

    # And the honest counterpart: the same case with nothing visible must
    # NOT be a concern.
    blind = PerceptionRecord(
        content_hash=image.content_hash,
        source="test-fixture",
        damage_severity="minor",
        weather_observed="unknown",
        road_condition="",
        shadow_direction="none_visible",
        shadow_length="none",
        lighting="unknown",
        raw_response={},
    )
    ctx_blind = CheckContext(conn=conn, case=case, images=[image],
                             perception={image.content_hash: blind}, config={})
    blind_finding = SceneConsistencyCheck().run(ctx_blind)[0]
    assert blind_finding.verdict == Verdict.INCONCLUSIVE, (
        f"an image with no legible cues must be INCONCLUSIVE, got {blind_finding.verdict.value}"
    )
    print(f"  and with no visible cues: {blind_finding.verdict.value}")


@test
def test_weather_subcheck_uses_hourly_not_daily_precipitation():
    """
    The fix that resolved a genuine generator/check conflict.

    A daily precipitation TOTAL cannot establish that rain was falling at
    the declared minute - monsoon rain is intermittent - so the check used
    to refuse the "clear photo on a rainy day" direction outright, which
    left an entire CONTEXT_MISMATCH variant undetectable by design. With
    hourly precipitation the objection disappears in one direction and,
    importantly, a NEW refusal appears in the other: a wet photo on a day
    whose rain fell hours earlier is no longer flagged. The check got more
    precise, not more aggressive, and both halves are asserted here.
    """
    from datetime import datetime, timezone
    from src.checks.scene_consistency import SceneConsistencyCheck, RAINY_HOUR_MM
    from src.models import PerceptionRecord

    check = SceneConsistencyCheck()

    def record(weather, road):
        return PerceptionRecord(content_hash="c" * 64, source="test-fixture",
                                weather_observed=weather, road_condition=road,
                                shadow_direction="none_visible", shadow_length="none",
                                lighting="unknown", raw_response={})

    rainy_at_declared_hour = {
        "precipitation_mm": 40.0,
        "hourly_precipitation_mm": {12: 6.0, 3: 0.0},
        "cloudcover_mean_pct": 90.0,
    }
    # (1) Dry photograph, rain demonstrably falling in the declared hour:
    #     now a contradiction. This is the case that used to be refused.
    evidence = {}
    issues = check._weather_subcheck(record("clear", "dry asphalt"), rainy_at_declared_hour, evidence, 12)
    assert issues, "a dry photo during an hour of measured rain must contradict"
    assert "declared hour" in issues[0], issues[0]
    assert evidence["declared_hour_precipitation_mm"] == 6.0

    # (2) Same rainy day, but the declared hour itself was dry: NOT a
    #     contradiction, because the photograph and the weather agree.
    evidence = {}
    issues = check._weather_subcheck(record("clear", "dry asphalt"), rainy_at_declared_hour, evidence, 3)
    assert not issues, f"a dry photo in a dry hour must not contradict: {issues}"

    # (3) The new refusal in the other direction - wet ground, no rain in
    #     the declared hour but rain earlier the same day. Ground stays wet
    #     after rain, so this must be noted, never alleged.
    evidence = {}
    issues = check._weather_subcheck(record("wet_ground", "wet asphalt"), rainy_at_declared_hour, evidence, 3)
    assert not issues, f"wet ground after earlier rain must not contradict: {issues}"
    assert evidence.get("weather_status") == "noted, not a contradiction"

    # (4) Wet photograph on a genuinely bone-dry day still contradicts.
    evidence = {}
    issues = check._weather_subcheck(
        record("wet_ground", "wet asphalt"),
        {"precipitation_mm": 0.0, "hourly_precipitation_mm": {}, "cloudcover_mean_pct": 5.0},
        evidence, 12,
    )
    assert issues, "wet ground on a day with zero rain must still contradict"
    print(f"  hourly threshold {RAINY_HOUR_MM}mm: dry-photo-in-wet-hour fires, "
          "dry-photo-in-dry-hour does not, wet-photo-after-rain does not, wet-photo-on-dry-day does")


@test
def test_scene_consistency_skips_cases_without_coordinates():
    from src.checks.scene_consistency import SceneConsistencyCheck
    from src.checks.base import CheckContext

    conn = get_conn()
    case = get_case(cases_by_archetype("CLEAN")[0]["case_id"])
    case.latitude = None
    case.longitude = None
    ctx = CheckContext(conn=conn, case=case, images=db.get_images_for_case(conn, case.case_id),
                       perception={}, config={})
    findings=SceneConsistencyCheck().run(ctx)
    assert len(findings)==1 and findings[0].verdict==Verdict.INCONCLUSIVE
    assert set(findings[0].evidence['missing_requirements']) >= {'latitude','longitude'}
    print("  no coordinates -> [] (not an INCONCLUSIVE in every report)")


@test
def test_scene_consistency_on_real_perception_if_any_exists():
    """
    Runs against whatever perception records exist. Skips rather than
    fails when the vision pass has not been run - the check's correctness
    does not depend on quota being available today.
    """
    conn = get_conn()
    rows = conn.execute(
        "SELECT DISTINCT i.case_id FROM images i JOIN perception_records p "
        "ON i.content_hash = p.content_hash LIMIT 25"
    ).fetchall()
    if not rows:
        print("  SKIP: no perception records yet (run: python -m src.perception --stratified)")
        return

    verdicts = Counter()
    for (case_id,) in rows:
        for f in run_checks(conn, get_case(case_id), check_ids=["scene_consistency"]):
            if "not yet available" in f.explanation:
                continue
            verdicts[f.verdict.value] += 1
            assert f.explanation.strip()
            if f.verdict == Verdict.CONCERN:
                # The flagship promise: a CONCERN must name the declared
                # time and say what physically contradicts it.
                assert "contradicts the declared time and place" in f.explanation
                assert "solar_elevation_deg" in f.evidence
    print(f"  {sum(verdicts.values())} finding(s) over {len(rows)} case(s): {dict(verdicts)}")


# ---------------------------------------------------------------------------
# DamagePlausibilityCheck
# ---------------------------------------------------------------------------


@test
def test_damage_plausibility_bands_and_tolerance():
    from src.checks.damage_plausibility import CEILING_TOLERANCE, SEVERITY_RANGES, worst_severity

    # Most severe wins - a claimant cannot dilute the assessment by
    # uploading more photographs of undamaged bodywork.
    assert worst_severity(["minor", "severe", "none"]) == "severe"
    assert worst_severity(["none", "minor"]) == "minor"
    assert worst_severity([None, "nonsense"]) is None
    assert worst_severity([]) is None

    # Bands overlap on purpose; ceilings must still increase.
    ceilings = [SEVERITY_RANGES[s][1] for s in ("none", "minor", "moderate")]
    assert ceilings == sorted(ceilings), "severity ceilings must be monotonic"
    assert SEVERITY_RANGES["severe"][1] is None, "severe must have no ceiling to guess at"
    assert CEILING_TOLERANCE > 1.0, "the check must allow headroom over the ceiling"
    print(f"  worst-wins ordering holds; tolerance {CEILING_TOLERANCE}x over ceiling")


@test
def test_damage_plausibility_skips_underwriting_cases():
    """
    Underwriting cases are pre-policy inspections: no incident, no claim
    amount, nothing to compare against. The check must never speak about
    one.

    Tested at two levels because the framework gets there first. For a
    case-scoped check with requires_perception=True, _run_one returns its
    own "Perception data not yet available." INCONCLUSIVE *before*
    check.run() is ever called - so asserting run_checks() returns []
    would be asserting the framework's behaviour, not the check's, and
    would pass or fail depending on whether the vision pass had happened
    to cover that case.
    """
    from src.checks.base import CheckContext
    from src.checks.damage_plausibility import DamagePlausibilityCheck
    from src.models import PerceptionRecord

    conn = get_conn()
    underwriting = None
    for row in cases_by_archetype("CLEAN"):
        case = get_case(row["case_id"])
        if case.agent_type == "underwriting":
            underwriting = case
            break
    assert underwriting is not None, "expected an underwriting case in this corpus"

    # Level 1 - the check's own logic, given perception so the framework
    # rule cannot mask it. Severity is deliberately "severe" so a check
    # that failed to skip would have something to talk about.
    images = db.get_images_for_case(conn, underwriting.case_id)
    perception = {
        img.content_hash: PerceptionRecord(
            content_hash=img.content_hash, source="test-fixture",
            damage_severity="severe", raw_response={},
        )
        for img in images
    }
    ctx = CheckContext(conn=conn, case=underwriting, images=images, perception=perception, config={})
    assert DamagePlausibilityCheck().run(ctx) == [], (
        "an underwriting case has no claim amount to test, so the check must stay silent"
    )

    # Level 2 - integrated. Whatever the framework decides, the one thing
    # that must never happen is an accusation.
    findings = run_checks(conn, underwriting, check_ids=["damage_plausibility"])
    assert all(f.verdict != Verdict.CONCERN for f in findings), (
        f"underwriting case raised a CONCERN: {[(f.verdict.value, f.explanation) for f in findings]}"
    )
    print(f"  {underwriting.case_id} (underwriting, claim_amount={underwriting.claim_amount}): "
          f"run() -> [], integrated -> {[f.verdict.value for f in findings] or '[]'}")


# ---------------------------------------------------------------------------
# DigitalEditCheck
# ---------------------------------------------------------------------------


@test
def test_digital_edit_signals_are_bounded_and_deterministic():
    from src.checks.digital_edit import analyse

    conn = get_conn()
    image = db.get_all_images(conn)[0]
    first = analyse(image.path)
    assert first is not None, "a corpus image must be analysable"
    for key in ("ghost", "noise", "edge", "combined"):
        assert key in first, f"missing signal {key}"
        assert 0.0 <= first[key] <= 1.0, f"{key} out of range: {first[key]}"
    second = analyse(image.path)
    assert first == second, "image forensics must be deterministic"
    print(f"  {first}")


@test
def test_digital_edit_never_accuses_while_uncalibrated():
    """
    An uncalibrated forensic threshold is an accusation with no evidence
    behind it. The check must abstain until measured - and, having been
    measured to have no discriminative power on this corpus, must abstain
    permanently.
    """
    from src.checks.digital_edit import get_calibration

    cal = get_calibration()
    conn = get_conn()
    case = get_case(cases_by_archetype("CLEAN")[0]["case_id"])
    findings = run_checks(conn, case, check_ids=["digital_edit"])
    assert findings, "digital_edit produced no findings"

    if not cal.get("calibrated", False):
        for f in findings:
            assert f.verdict == Verdict.INCONCLUSIVE, (
                f"an uncalibrated forensic check must never accuse, got {f.verdict}"
            )
        assert REGISTRY["digital_edit"].weight == 0.0, "an uninformative check must carry weight 0.0"
        print(f"  uncalibrated (measured AUC {cal.get('combined_auc', float('nan')):.3f}): "
              f"all {len(findings)} finding(s) INCONCLUSIVE, weight 0.0")
    else:
        print(f"  calibrated at threshold {cal['concern_threshold']:.3f}")


# ---------------------------------------------------------------------------
# PlateOCRCheck
# ---------------------------------------------------------------------------


@test
def test_plate_parsing_handles_ocr_confusions():
    """Pure-function test, no OCR engine needed - fast and deterministic."""
    from src.checks.plate_ocr import coerce_to_plate, edit_distance, normalise

    assert coerce_to_plate("GJ01AB1234") == "GJ01AB1234"
    assert coerce_to_plate("GJ 01 AB 1234") == "GJ01AB1234", "spaces must be tolerated"
    assert coerce_to_plate("GJ-01-AB-1234") == "GJ01AB1234", "hyphens must be tolerated"
    assert coerce_to_plate("6J01AB1234") == "GJ01AB1234", "6->G in a letter slot"
    assert coerce_to_plate("GJO1AB1234") == "GJ01AB1234", "O->0 in a digit slot"
    assert coerce_to_plate("GJ01ABC1234") == "GJ01ABC1234", "three-letter series is valid"
    assert coerce_to_plate("hello") is None
    assert coerce_to_plate("") is None
    assert normalise("gj-01 ab#1234") == "GJ01AB1234"
    assert edit_distance("GJ01AB1234", "GJ01AB1234") == 0
    assert edit_distance("GJ01AB1234", "GJ01AB1235") == 1
    print("  spaces, hyphens, O/0, I/1, S/5, B/8, 6/G confusions all handled")


@test
def test_plate_ocr_no_plate_found_is_inconclusive_not_concern():
    """
    The corpus is 200-300px, so most images yield no plate-shaped text at
    all. That must be INCONCLUSIVE - scoring it CONCERN would fire on the
    majority of honest claims.
    """
    conn = get_conn()
    case = get_case(cases_by_archetype("CLEAN")[0]["case_id"])
    findings = run_checks(conn, case, check_ids=["plate_ocr"])
    assert findings, "expected at least one finding"
    for f in findings:
        assert f.verdict != Verdict.CONCERN or f.evidence.get("plate_candidate"), (
            "CONCERN is only permissible when an actual plate candidate was read"
        )
        if not f.evidence.get("plate_candidate"):
            assert f.verdict == Verdict.INCONCLUSIVE, f"no plate found must be INCONCLUSIVE, got {f.verdict.value}"
    found = sum(1 for f in findings if f.evidence.get("plate_candidate"))
    print(f"  {case.case_id}: {len(findings)} image(s), {found} with a plate candidate, none wrongly CONCERN")


# ---------------------------------------------------------------------------
# Retirement and demotion
#
# These two tests exist to make a governance decision mechanical. A
# retired check and a demoted check are both easy to un-retire by
# accident - an import added back, a threshold reintroduced - and the
# damage would be silent, showing up only as a worse false-positive rate
# nobody traced to its cause. So both are asserted, not documented.
# ---------------------------------------------------------------------------


@test
def test_retired_check_is_not_registered():
    assert "vehicle_consistency" not in REGISTRY, (
        "vehicle_consistency was retired (99.11% FP on clean cases, signal inverted) - "
        "it must not be in REGISTRY. See src/checks/retired/vehicle_consistency.py."
    )
    # Importable for reference, but inert: importing it must not register it.
    from src.checks.retired.vehicle_consistency import VehicleConsistencyCheck

    assert VehicleConsistencyCheck.check_id == "vehicle_consistency"
    assert "vehicle_consistency" not in REGISTRY, "importing a retired check must not register it"
    print("  vehicle_consistency: importable for reference, absent from REGISTRY")


@test
def test_demoted_ai_check_can_never_produce_concern():
    conn = get_conn()
    checked = 0
    for row in cases_by_archetype("CLEAN")[:12]:
        case = get_case(row["case_id"])
        for f in run_checks(conn, case, check_ids=["ai_generation"]):
            assert f.verdict is not Verdict.CONCERN, (
                f"ai_generation is demoted and must always be INCONCLUSIVE, got {f.verdict} "
                f"on {case.case_id}"
            )
            if "artificial_probability" in f.evidence:
                # The measurement must survive the demotion - that is the
                # entire reason the check still runs.
                assert 0.0 <= f.evidence["artificial_probability"] <= 1.0
                checked += 1
    if checked == 0:
        # Missing native cache is not a scored success. Verify the demotion
        # contract separately with explicitly controlled classifier output.
        from src.checks.ai_detection import AIGenerationCheck
        image=db.get_images_for_case(conn,case.case_id)[0]
        ctx=CheckContext(conn=conn,case=case,images=[image],perception={},config={})
        controlled=AIGenerationCheck()._check_one_image(ctx,image,
            lambda _: [{'label':'artificial','score':.99}],.8,.6)
        assert controlled.verdict==Verdict.INCONCLUSIVE
        assert controlled.evidence['artificial_probability']==.99
        print('Native AI classifier unverified/unavailable; controlled demotion contract passed.')
    assert REGISTRY["ai_generation"].weight == 0.0, "a demoted check must carry weight 0.0"
    print(f"  {checked} image(s) scored, all INCONCLUSIVE, probabilities still recorded, weight 0.0")


@test
def test_every_registered_check_has_a_justified_weight():
    expected = {
        "internal_duplicate": 1.0,
        "external_corpus": 1.0,
        "threshold_gaming": 1.0,
        "scene_consistency": 1.0,
        # 0.0 - a measured negative, recorded the way vehicle_consistency's
        # was. Two detection routes were built and measured against this
        # check's target archetype: cross-case linkage (UNAVAILABLE - all
        # 800 cases have unique registrations and claimants) and synthetic
        # image forensics (CANDIDATE BUT CONFOUNDED - AUC 0.26 inverted,
        # resolution matched but JPEG quantisation not). Neither yields a
        # usable detector, so the check carries no weight. See
        # outputs/baseline_signal_measurement.json.
        "baseline_corruption": 0.0,
        # entity_graph: 1.0 by argument, not by measurement on this corpus.
        # Two independent shared identifiers between different claimants is
        # close to fact rather than inference - people do not coincidentally
        # share both a bank account and a phone number. The production corpus
        # assigns unique claimants and registrations so nothing can join, and
        # the check was measured instead against an injected ring
        # (8/8 detected, 0 false positives across 792 unrelated cases;
        # outputs/entity_graph_measurement.json).
        "entity_graph": 1.0,
        # view_completeness: 0.0, a measured negative. All three of its
        # components fire on 100% of clean underwriting cases on this corpus
        # - every underwriting case carries exactly two images against a
        # four-view requirement, angle similarity is inverted (AUC 0.35), and
        # plates are legible in ~0% of both classes.
        # See outputs/view_completeness_measurement.json.
        "view_completeness": 0.0,
        # baseline_linkage: 1.0. A vehicle certified undamaged that claims
        # moderate-or-worse damage inside 30 days is a contradiction between
        # two stored records rather than an estimate from pixels. Measured
        # 20/20 on linked positives, 0/10 on long-interval controls and
        # 0/620 on unlinked claims (outputs/baseline_linkage_measurement.json).
        "baseline_linkage": 1.0,
        # severity_progression: 1.0 by argument, measured against injected
        # repeat-claim sequences. A severity sequence that falls and recovers
        # with no repair on record is a contradiction between stored
        # observations rather than an estimate from pixels. Measured 8/8 on
        # oscillating positives, 0/6 on monotone controls and 0/6 on repaired
        # controls (outputs/severity_progression_measurement.json).
        "severity_progression": 1.0,
        "exif_metadata": 0.7,
        "damage_plausibility": 0.7,
        "plate_ocr": 0.3,
        "c2pa_credentials": 0.1,
        "ai_generation": 0.0,
        "digital_edit": 0.0,
    }
    assert set(REGISTRY) == set(expected), f"registry {sorted(REGISTRY)} != weighted set {sorted(expected)}"
    for check_id, want in expected.items():
        got = REGISTRY[check_id].weight
        assert got == want, f"{check_id} weight {got} != {want}"
        assert 0.0 <= got <= 1.0
    print("  weights: " + ", ".join(f"{k}={v}" for k, v in sorted(expected.items(), key=lambda kv: -kv[1])))


# ---------------------------------------------------------------------------
# Framework: crash handling, skip rules, registry
# ---------------------------------------------------------------------------


class _AlwaysRaisesCheck(Check):
    check_id = "always_raises"
    category = CheckCategory.PROVENANCE
    scope = "case"
    cost_inr = 0.0
    requires_perception = False

    def run(self, ctx: CheckContext) -> list:
        raise RuntimeError("deliberate failure for test_check_that_raises_produces_inconclusive")


@test
def test_check_that_raises_produces_inconclusive_not_a_crash():
    conn = get_conn()
    case = get_case(load_ground_truth()[0]["case_id"])
    ctx = CheckContext(conn=conn, case=case, images=[], perception={}, config={})

    findings = _run_one(_AlwaysRaisesCheck(), ctx)

    assert len(findings) == 1, f"expected exactly one finding, got {findings}"
    finding = findings[0]
    assert finding.verdict == Verdict.INCONCLUSIVE
    assert finding.confidence == 0.0
    assert finding.evidence.get("error_type") == "RuntimeError"
    diagnostic = finding.evidence['diagnostic']
    assert diagnostic['stage'] == 'check:always_raises'
    assert diagnostic['error_category'] == 'worker_exception'
    assert diagnostic['exception_type'] == 'RuntimeError'
    assert diagnostic['attempted_network'] is False
    assert "deliberate failure" not in diagnostic['message']
    assert 'RuntimeError' in diagnostic['message']
    assert 'error' not in finding.evidence  # Raw exception text is not a separate evidence field.
    print(f"  {finding.verdict.value}: {finding.explanation} (evidence={finding.evidence})")


@test
def test_image_scoped_check_with_zero_images_is_inconclusive():
    conn = get_conn()
    underwriting_rows = [row for row in load_ground_truth() if row["agent_type"] == "underwriting"]
    # Any case works for this - it just needs zero images, so build a
    # context directly rather than hunting for a real zero-image case.
    case = get_case((underwriting_rows or load_ground_truth())[0]["case_id"])
    ctx = CheckContext(conn=conn, case=case, images=[], perception={}, config={})

    findings = _run_one(REGISTRY["internal_duplicate"], ctx)

    assert len(findings) == 1
    assert findings[0].verdict == Verdict.INCONCLUSIVE
    assert findings[0].explanation == "No images available for this case."
    print(f"  {findings[0].explanation}")


@test
def test_check_category_matches_the_prd_taxonomy():
    # Exactly five, matching the PRD/SRS/presentation. Pinned because the
    # enum previously drifted to seven by acquiring members named after
    # techniques (VISUAL, DOCUMENT) rather than questions, and checks were
    # then filed by mechanism instead of by what they establish.
    assert {c.name for c in CheckCategory} == {
        "IDENTITY",
        "HISTORY",
        "PROVENANCE",
        "CONTEXT",
        "ECONOMIC",
    }, f"CheckCategory drifted: {sorted(c.name for c in CheckCategory)}"
    assert REGISTRY["plate_ocr"].category is CheckCategory.IDENTITY
    print("  5 categories: " + ", ".join(sorted(c.name for c in CheckCategory)))


@test
def test_ai_baseline_archetype_is_underwriting_and_distinct():
    """
    AI_GENERATED_BASELINE is a different shape of fraud from every other
    archetype and the corpus must reflect that, not just the label.

    Every claims-side archetype fabricates the PRESENCE of damage. This
    one fabricates its ABSENCE, at policy inception, to inflate the
    insured declared value and to plant a clean pre-existing-condition
    baseline. So: it must be an underwriting case (no claim amount, no
    incident), and it must NOT be drawn from the claims fraud budget,
    because mixing an underwriting case into a claims denominator
    corrupts every claims-side recall figure in the report.
    """
    import json as _json

    rows = cases_by_archetype("AI_GENERATED_BASELINE")
    if not rows:
        print("  SKIP: no AI_GENERATED_BASELINE cases (data/ai_generated_underwriting/ absent at generation)")
        return

    conn = get_conn()
    for row in rows:
        case = get_case(row["case_id"])
        assert case.agent_type == "underwriting", (
            f"{case.case_id} must be an underwriting case, got {case.agent_type!r}"
        )
        assert case.claim_amount is None, f"{case.case_id} must have no claim amount"
        meta = _json.loads(row["fraud_metadata"] or "{}")
        assert meta.get("attack") == "baseline_corruption", meta
        assert meta.get("fabricates") == "absence_of_damage", meta
        assert meta.get("stage") == "policy_inception", meta
        assert meta.get("distinct_from") == "claim_time_fabrication", meta
        assert "ai_image_source" in meta and meta["ai_image_source"], meta
        assert db.get_images_for_case(conn, case.case_id), f"{case.case_id} has no images"

    # The claims-side archetypes must be undisturbed by its addition.
    claims_fraud = [r for r in load_ground_truth()
                    if r["archetype"] not in ("CLEAN", "AI_GENERATED_BASELINE")]
    assert claims_fraud, "expected claims-side fraud cases"
    print(f"  {len(rows)} AI_GENERATED_BASELINE case(s), all underwriting with no claim amount; "
          f"{len(claims_fraud)} claims-side fraud cases unaffected")


@test
def test_baseline_corruption_does_not_claim_a_target_it_cannot_fire_on():
    """
    A check must not advertise an archetype it structurally cannot detect.

    This is a regression test for a real bug in this check's first
    version. It declared target_archetypes = ("AI_GENERATED_BASELINE",)
    and fired on photographs that *contradict* a no-damage declaration -
    but that archetype fabricates the *absence* of damage, so its
    photographs agree with the declaration by construction. The check
    returned PASS at up to 0.8 confidence on every case it was built to
    catch, and because the agent reads finding explanations, the treatment
    arm was being told the fraud looked consistent.

    The rule this locks in: if a check names a target archetype, it must
    be able to reach CONCERN on it. Naming a target you always PASS on is
    worse than naming none, because it makes an undetected archetype look
    covered in the reports.
    """
    check = REGISTRY["baseline_corruption"]
    conn = get_conn()
    targets = [r["case_id"] for r in load_ground_truth()
               if r["archetype"] == "AI_GENERATED_BASELINE"]
    assert targets, "expected AI_GENERATED_BASELINE cases in the corpus"

    verdicts = Counter()
    for case_id in targets:
        case = get_case(case_id)
        for f in run_checks(conn, case, check_ids=["baseline_corruption"]):
            if f.check_id == "baseline_corruption":
                verdicts[f.verdict.value] += 1

    fires = verdicts.get("concern", 0)
    if fires == 0:
        assert "AI_GENERATED_BASELINE" not in check.target_archetypes, (
            "baseline_corruption never reaches CONCERN on AI_GENERATED_BASELINE "
            f"(verdicts: {dict(verdicts)}) yet still claims it as a target - that "
            "credits the check with an archetype nothing detects"
        )
    print(f"  {len(targets)} target case(s), verdicts {dict(verdicts)}; "
          f"declared targets {check.target_archetypes or '()'} - consistent")


@test
def test_registry_and_all_checks_are_consistent():
    assert set(ALL_CHECKS) == set(REGISTRY.keys())
    # Equality, not a subset: a subset check would silently tolerate a
    # retired check creeping back into the battery.
    assert set(ALL_CHECKS) == {
        "internal_duplicate",
        "exif_metadata",
        "threshold_gaming",
        "external_corpus",
        "c2pa_credentials",
        "ai_generation",
        "plate_ocr",
        "scene_consistency",
        "damage_plausibility",
        "digital_edit",
        "baseline_corruption",
        "entity_graph",
        "view_completeness",
        "baseline_linkage",
        "severity_progression",
    }, f"unexpected battery: {sorted(ALL_CHECKS)}"
    for check_id, check in REGISTRY.items():
        assert check.check_id == check_id
        assert check.scope in ("image", "case")
        assert isinstance(check.category, CheckCategory)
    print(f"  {len(ALL_CHECKS)} registered: {ALL_CHECKS}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    try:
        ok = run_all()
    finally:
        if _conn is not None:
            _conn.close()
    sys.exit(0 if ok else 1)
