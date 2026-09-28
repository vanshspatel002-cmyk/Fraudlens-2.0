"""
Tests for the rules-only baseline scorer.

These are deliberately model-free and database-free: the baseline is
arithmetic plus a template, and the point of testing it in isolation is
that the control arm of an ablation must be verifiable without running
the thing it is a control for.

The tests that matter most are the ones asserting what the baseline
must *never* do - never reject, never let a zero-weight check move a
score, never let a pile of INCONCLUSIVE findings drift a case upward.
Those are the properties that make the comparison against the agent arm
honest, and all three are easy to break by accident.

Run:  python test_baseline.py
"""

from __future__ import annotations

import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]

from src import baseline
from src.models import Case, CheckCategory, Finding, Recommendation, RiskBand, Verdict

_TESTS: list = []


def test(fn):
    _TESTS.append(fn)
    return fn


def run_all() -> bool:
    passed, failed = 0, 0
    failures = []
    for fn in _TESTS:
        print(f"--- {fn.__name__} ---")
        try:
            fn()
            passed += 1
            print(f"PASS  {fn.__name__}")
        except Exception as e:  # noqa: BLE001 - test runner, wants everything
            failed += 1
            failures.append((fn.__name__, traceback.format_exc()))
    for name, tb in failures:
        print(f"FAIL  {name}\n{tb}")
    print(f"\n{passed} passed, {failed} failed")
    return failed == 0


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def make_case(case_id: str = "case-0001") -> Case:
    return Case(
        case_id=case_id,
        claimant_id="claimant-0001",
        garage_id="GAR-VAD-01",
        claim_type="collision",
        agent_type="claims",
        vehicle_registration="GJ01AB1234",
        declared_time=datetime(2026, 1, 1, tzinfo=timezone.utc),
        claim_amount=48000.0,
    )


def finding(check_id: str, verdict: Verdict, confidence: float, explanation: str = "reason") -> Finding:
    return Finding(
        check_id=check_id,
        case_id="case-0001",
        category=CheckCategory.HISTORY,
        verdict=verdict,
        confidence=confidence,
        explanation=explanation,
    )


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------


@test
def test_concern_contributes_weight_times_confidence():
    score, _ = baseline.score_case([finding("internal_duplicate", Verdict.CONCERN, 0.9)])
    assert abs(score - 0.9) < 1e-9, score  # weight 1.0
    score, _ = baseline.score_case([finding("exif_metadata", Verdict.CONCERN, 0.8)])
    assert abs(score - 0.56) < 1e-9, score  # weight 0.7
    print("  1.0x0.9 = 0.90, 0.7x0.8 = 0.56")


@test
def test_inconclusive_and_pass_contribute_exactly_zero():
    # The tempting bug is letting many INCONCLUSIVEs drift a case upward
    # "because something is off". Eight checks saying "I could not tell"
    # is not evidence, and treating it as evidence manufactures false
    # positives on every case with many images.
    noise = [finding("internal_duplicate", Verdict.INCONCLUSIVE, 1.0) for _ in range(20)]
    noise += [finding("exif_metadata", Verdict.PASS, 1.0) for _ in range(20)]
    score, band = baseline.score_case(noise)
    assert score == 0.0, score
    assert band is RiskBand.CLEAR
    print(f"  40 inconclusive/pass findings -> score {score}, band {band.value}")


@test
def test_demoted_check_cannot_move_the_score():
    # Belt and braces: ai_generation is forced INCONCLUSIVE in its own
    # run(), but even a hand-built CONCERN at full confidence must score
    # zero, because its weight is 0.0.
    score, band = baseline.score_case([finding("ai_generation", Verdict.CONCERN, 1.0)])
    assert score == 0.0, score
    assert band is RiskBand.CLEAR
    print("  a forged CONCERN from the demoted check still scores 0.0")


@test
def test_retired_check_findings_are_ignored():
    # A stale findings row from a withdrawn check must not keep voting.
    score, _ = baseline.score_case([finding("vehicle_consistency", Verdict.CONCERN, 1.0)])
    assert score == 0.0, score
    score, _ = baseline.score_case([finding("no_such_check_at_all", Verdict.CONCERN, 1.0)])
    assert score == 0.0, score
    print("  retired and unknown check_ids both weigh 0.0")


@test
def test_scores_accumulate_across_checks():
    score, band = baseline.score_case(
        [
            finding("internal_duplicate", Verdict.CONCERN, 0.9),
            finding("threshold_gaming", Verdict.CONCERN, 0.8),
        ]
    )
    assert abs(score - 1.7) < 1e-9, score
    assert band is RiskBand.ESCALATE_SIU
    print(f"  two strong concerns -> {score:.2f} -> {band.value}")


# ---------------------------------------------------------------------------
# Banding
# ---------------------------------------------------------------------------


@test
def test_band_boundaries_are_half_open_and_ordered():
    cases = [
        (0.0, RiskBand.CLEAR),
        (0.299, RiskBand.CLEAR),
        (0.3, RiskBand.REQUEST_EVIDENCE),
        (0.599, RiskBand.REQUEST_EVIDENCE),
        (0.6, RiskBand.DESK_REVIEW),
        (0.999, RiskBand.DESK_REVIEW),
        (1.0, RiskBand.ESCALATE_SIU),
        (99.0, RiskBand.ESCALATE_SIU),
    ]
    for score, want in cases:
        got = baseline.band_for(score)
        assert got is want, f"{score} -> {got}, want {want}"
    print("  boundaries at 0.3 / 0.6 / 1.0, lower bound inclusive")


@test
def test_no_band_can_ever_reject():
    # The structural safeguard, restated at the level that routes cases.
    for band in RiskBand:
        rec = band.to_recommendation()
        assert rec in (Recommendation.APPROVE, Recommendation.REQUEST_EVIDENCE, Recommendation.ESCALATE)
        assert "reject" not in rec.value
        assert "deny" not in rec.value
    print("  all 4 bands route to approve / request_evidence / escalate")


# ---------------------------------------------------------------------------
# Decisions
# ---------------------------------------------------------------------------


@test
def test_decision_is_stamped_for_the_ablation():
    d = baseline.decide([], make_case())
    assert d.policy_version == "baseline-v1"
    assert d.tool_calls_count == 0
    assert d.iterations_count == 0
    assert d.llm_calls_count == 0
    assert d.risk_band is RiskBand.CLEAR
    assert d.recommendation is Recommendation.APPROVE
    print(f"  {d.policy_version}: 0 tools, 0 iterations, 0 llm calls")


@test
def test_request_evidence_always_names_a_specific_artifact():
    # AgentDecision refuses to construct REQUEST_EVIDENCE with an empty
    # artifact list - "send better photos" is not actionable. This test
    # exists because the baseline is what has to satisfy that guard.
    d = baseline.decide([finding("exif_metadata", Verdict.CONCERN, 0.6)], make_case())
    assert d.risk_band is RiskBand.REQUEST_EVIDENCE, d.risk_band
    assert d.requested_artifacts, "REQUEST_EVIDENCE must name at least one artifact"
    assert all(len(a) > 15 for a in d.requested_artifacts), d.requested_artifacts
    print(f"  asks for: {d.requested_artifacts[0]}")


@test
def test_narrative_is_templated_from_finding_explanations():
    # The control arm must stay LLM-free: a "baseline" that called a
    # model to write its summary would contaminate the comparison it
    # exists to support. So every sentence must be traceable to a
    # finding the checks produced.
    concerns = [
        finding("internal_duplicate", Verdict.CONCERN, 0.9, "This image matches an image in case-0501."),
        finding("threshold_gaming", Verdict.CONCERN, 0.8, "Claim falls just under the survey threshold."),
    ]
    d = baseline.decide(concerns, make_case())
    for f in concerns:
        assert f.explanation in d.summary, f"missing explanation: {f.explanation}"
    assert "escalate" not in d.summary.lower() or "Special Investigation" in d.summary
    print(f"  summary: {d.summary[:110]}...")


@test
def test_summary_is_capped_and_says_how_many_were_omitted():
    concerns = [
        finding("internal_duplicate", Verdict.CONCERN, 0.9, f"Concern number {i}.") for i in range(9)
    ]
    d = baseline.decide(concerns, make_case())
    assert "further concern(s) recorded" in d.summary, d.summary
    print(f"  9 concerns -> {baseline.MAX_NARRATIVE_FINDINGS} shown + a count of the rest")


@test
def test_supporting_findings_are_ordered_strongest_first():
    weak = finding("c2pa_credentials", Verdict.CONCERN, 0.9)      # weight 0.1
    strong = finding("internal_duplicate", Verdict.CONCERN, 0.5)  # weight 1.0
    d = baseline.decide([weak, strong], make_case())
    assert d.supporting_finding_ids[0] == strong.finding_id, "heaviest evidence must lead"
    print("  0.1x0.9 ranked below 1.0x0.5, as weight intends")


@test
def test_clean_case_with_no_findings_is_a_confident_clear():
    d = baseline.decide([], make_case())
    assert d.risk_band is RiskBand.CLEAR
    assert d.confidence >= 0.85, d.confidence
    assert d.requested_artifacts == []
    print(f"  no findings -> clear at confidence {d.confidence}")


@test
def test_thresholds_are_parameters_so_the_sweep_can_vary_them():
    findings = [finding("exif_metadata", Verdict.CONCERN, 0.5)]  # score 0.35
    strict = baseline.decide(findings, make_case(), 0.1, 0.2, 0.3)
    lax = baseline.decide(findings, make_case(), 0.5, 0.8, 1.2)
    assert strict.risk_band is RiskBand.ESCALATE_SIU, strict.risk_band
    assert lax.risk_band is RiskBand.CLEAR, lax.risk_band
    # Same evidence, same score, different routing - which is exactly
    # what the sweep measures.
    assert strict.score == lax.score
    print(f"  score {strict.score} -> {strict.risk_band.value} (strict) / {lax.risk_band.value} (lax)")


if __name__ == "__main__":
    sys.exit(0 if run_all() else 1)
