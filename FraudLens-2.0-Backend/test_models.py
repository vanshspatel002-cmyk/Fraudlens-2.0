"""
Test suite for src.models and src.db.

No external test framework - stdlib only - so the result can be run
anywhere the project's own dependencies are installed, and the summary
line is plain English rather than pytest's report format.

Run with:
    python test_models.py
"""

from __future__ import annotations

import sqlite3
import sys
import tempfile
import traceback
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from src import db
from src.models import (
    AgentDecision,
    AdminAction,
    AdminActionRecord,
    Case,
    CheckCategory,
    Finding,
    ImageArtifact,
    PerceptionRecord,
    Recommendation,
    RiskBand,
    Verdict,
)

# ---------------------------------------------------------------------------
# Tiny test runner
# ---------------------------------------------------------------------------

_TESTS: list = []


def test(fn):
    _TESTS.append(fn)
    return fn


def run_all() -> bool:
    passed, failed = 0, 0
    failures = []
    for fn in _TESTS:
        try:
            fn()
            passed += 1
        except Exception as e:  # noqa: BLE001 - test runner, wants everything
            failed += 1
            failures.append((fn.__name__, e, traceback.format_exc()))
    for name, e, tb in failures:
        print(f"FAIL  {name}\n{tb}")
    print(f"\n{passed} passed, {failed} failed")
    return failed == 0


def expect_raises(exc_type, fn, *args, **kwargs):
    try:
        fn(*args, **kwargs)
    except exc_type:
        return
    except Exception as e:  # noqa: BLE001
        raise AssertionError(f"expected {exc_type.__name__}, got {type(e).__name__}: {e}") from e
    raise AssertionError(f"expected {exc_type.__name__}, nothing was raised")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

HASH_A = "a" * 64
HASH_B = "b" * 64


def make_finding(**overrides):
    kwargs = dict(
        check_id="scene_consistency",
        case_id="case-1",
        category=CheckCategory.CONTEXT,
        verdict=Verdict.CONCERN,
        confidence=0.81,
        explanation="Claim states 18:00 but shadow direction and length indicate midday sun.",
        evidence={"declared_time": "18:00", "solar_azimuth_deg": 288.4},
    )
    kwargs.update(overrides)
    return Finding(**kwargs)


def make_case(**overrides):
    kwargs = dict(case_id="case-1", claimant_id="claimant-1", garage_id="garage-1", claim_type="collision")
    kwargs.update(overrides)
    return Case(**kwargs)


def make_perception(**overrides):
    kwargs = dict(content_hash=HASH_A, source="clip-vit-b32", caption="a dented rear bumper")
    kwargs.update(overrides)
    return PerceptionRecord(**kwargs)


def make_artifact(**overrides):
    kwargs = dict(artifact_id="art-1", case_id="case-1", content_hash=HASH_A, filename="photo1.jpg")
    kwargs.update(overrides)
    return ImageArtifact(**kwargs)


def make_decision(**overrides):
    kwargs = dict(
        case_id="case-1",
        recommendation=Recommendation.APPROVE,
        confidence=0.9,
        summary="No inconsistencies found across 6 checks.",
    )
    kwargs.update(overrides)
    return AgentDecision(**kwargs)


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


@test
def test_verdict_has_exactly_three_values():
    assert {v.value for v in Verdict} == {"pass", "inconclusive", "concern"}


@test
def test_recommendation_has_no_reject_value():
    values = {r.value for r in Recommendation}
    assert "reject" not in values
    assert not any("reject" in v for v in values)


@test
def test_recommendation_values():
    assert {r.value for r in Recommendation} == {"approve", "request_evidence", "escalate"}


@test
def test_admin_action_is_distinct_and_can_reject():
    assert {a.value for a in AdminAction} == {"approve", "reject", "request_more_evidence"}
    assert AdminAction.REJECT.value not in {r.value for r in Recommendation}


@test
def test_check_category_values():
    # Exactly five, matching the PRD/SRS/presentation. The enum previously
    # drifted to seven by acquiring members named after techniques
    # (VISUAL, DOCUMENT) rather than after questions; checks then got
    # filed by mechanism instead of by what they establish.
    expected = {"identity", "history", "provenance", "context", "economic"}
    assert {c.value for c in CheckCategory} == expected


@test
def test_risk_band_maps_onto_recommendation_and_still_cannot_reject():
    assert {b.value for b in RiskBand} == {"clear", "request_evidence", "desk_review", "escalate_siu"}
    # Total mapping - every band routes somewhere, and the two review
    # bands deliberately collapse onto ESCALATE.
    assert RiskBand.CLEAR.to_recommendation() is Recommendation.APPROVE
    assert RiskBand.REQUEST_EVIDENCE.to_recommendation() is Recommendation.REQUEST_EVIDENCE
    assert RiskBand.DESK_REVIEW.to_recommendation() is Recommendation.ESCALATE
    assert RiskBand.ESCALATE_SIU.to_recommendation() is Recommendation.ESCALATE
    # The safeguard survives the finer granularity: no band denies a claim.
    assert all("reject" not in b.to_recommendation().value for b in RiskBand)


@test
def test_decision_rejects_a_risk_band_inconsistent_with_its_recommendation():
    # The two fields could silently disagree - a decision stamped
    # ESCALATE_SIU but carrying APPROVE would corrupt the ablation's
    # confusion matrix while looking fine in the database.
    expect_raises(
        ValueError,
        make_decision,
        recommendation=Recommendation.APPROVE,
        risk_band=RiskBand.ESCALATE_SIU,
    )


@test
def test_decision_defaults_are_ablation_safe():
    d = make_decision()
    assert d.policy_version == "unversioned", "an unstamped decision must not masquerade as a known arm"
    assert d.tool_calls_count == d.iterations_count == d.llm_calls_count == 0
    assert d.to_dict()["policy_version"] == "unversioned"


@test
def test_decision_rejects_negative_counters():
    expect_raises(ValueError, make_decision, llm_calls_count=-1)


@test
def test_verdict_is_string_comparable():
    # str Enum: comparable to plain strings, JSON-friendly by construction.
    assert Verdict.PASS == "pass"
    assert Recommendation.APPROVE == "approve"


# ---------------------------------------------------------------------------
# Finding
# ---------------------------------------------------------------------------


@test
def test_finding_valid_construction():
    f = make_finding()
    assert f.check_id == "scene_consistency"
    assert f.verdict is Verdict.CONCERN
    assert f.evidence["declared_time"] == "18:00"


@test
def test_finding_confidence_zero_is_valid():
    make_finding(confidence=0.0)


@test
def test_finding_confidence_one_is_valid():
    make_finding(confidence=1.0)


@test
def test_finding_confidence_above_one_rejected():
    expect_raises(ValueError, make_finding, confidence=1.01)


@test
def test_finding_confidence_below_zero_rejected():
    expect_raises(ValueError, make_finding, confidence=-0.01)


@test
def test_finding_confidence_non_numeric_rejected():
    expect_raises(TypeError, make_finding, confidence="high")


@test
def test_finding_blank_explanation_rejected():
    expect_raises(ValueError, make_finding, explanation="")


@test
def test_finding_whitespace_only_explanation_rejected():
    expect_raises(ValueError, make_finding, explanation="   ")


@test
def test_finding_none_explanation_rejected():
    expect_raises(ValueError, make_finding, explanation=None)


@test
def test_finding_blank_check_id_rejected():
    expect_raises(ValueError, make_finding, check_id="")


@test
def test_finding_blank_case_id_rejected():
    expect_raises(ValueError, make_finding, case_id="  ")


@test
def test_finding_wrong_category_type_rejected():
    expect_raises(TypeError, make_finding, category="context")


@test
def test_finding_wrong_verdict_type_rejected():
    expect_raises(TypeError, make_finding, verdict="concern")


@test
def test_finding_evidence_must_be_dict():
    expect_raises(TypeError, make_finding, evidence=["not", "a", "dict"])


@test
def test_finding_evidence_defaults_to_empty_dict():
    f = Finding(
        check_id="c",
        case_id="k",
        category=CheckCategory.PROVENANCE,
        verdict=Verdict.PASS,
        confidence=0.5,
        explanation="ok",
    )
    assert f.evidence == {}


@test
def test_finding_has_generated_uuid():
    f = make_finding()
    assert len(f.finding_id) == 36 and f.finding_id.count("-") == 4


@test
def test_finding_two_instances_get_different_ids():
    a, b = make_finding(), make_finding()
    assert a.finding_id != b.finding_id


@test
def test_finding_created_at_defaults_to_utc_now():
    f = make_finding()
    assert f.created_at.tzinfo is not None
    assert abs((datetime.now(timezone.utc) - f.created_at).total_seconds()) < 5


@test
def test_finding_to_dict_uses_enum_values_not_members():
    d = make_finding().to_dict()
    assert d["category"] == "context"
    assert d["verdict"] == "concern"
    assert isinstance(d["created_at"], str)


# ---------------------------------------------------------------------------
# AgentDecision / Recommendation guard
# ---------------------------------------------------------------------------


@test
def test_decision_valid_construction():
    d = make_decision()
    assert d.recommendation is Recommendation.APPROVE


@test
def test_decision_confidence_out_of_range_rejected():
    expect_raises(ValueError, make_decision, confidence=1.5)


@test
def test_decision_blank_summary_rejected():
    expect_raises(ValueError, make_decision, summary="")


@test
def test_decision_wrong_recommendation_type_rejected():
    expect_raises(TypeError, make_decision, recommendation="approve")


@test
def test_request_evidence_without_artifacts_rejected():
    expect_raises(
        ValueError,
        make_decision,
        recommendation=Recommendation.REQUEST_EVIDENCE,
        requested_artifacts=[],
    )


@test
def test_request_evidence_with_artifacts_accepted():
    d = make_decision(
        recommendation=Recommendation.REQUEST_EVIDENCE,
        requested_artifacts=["wide shot of rear bumper", "odometer photo"],
    )
    assert len(d.requested_artifacts) == 2


@test
def test_approve_without_artifacts_is_fine():
    # The guard is specific to REQUEST_EVIDENCE, not global.
    make_decision(recommendation=Recommendation.APPROVE, requested_artifacts=[])


@test
def test_escalate_without_artifacts_is_fine():
    make_decision(recommendation=Recommendation.ESCALATE, requested_artifacts=[])


@test
def test_decision_default_supporting_findings_is_empty_list():
    d = make_decision()
    assert d.supporting_finding_ids == []


@test
def test_decision_has_generated_uuid():
    d = make_decision()
    assert len(d.decision_id) == 36


# ---------------------------------------------------------------------------
# PerceptionRecord
# ---------------------------------------------------------------------------


@test
def test_perception_valid_construction():
    p = make_perception()
    assert p.content_hash == HASH_A
    assert p.embedding is None


@test
def test_perception_hash_too_short_rejected():
    expect_raises(ValueError, make_perception, content_hash="abc123")


@test
def test_perception_hash_uppercase_rejected():
    expect_raises(ValueError, make_perception, content_hash="A" * 64)


@test
def test_perception_hash_non_hex_rejected():
    expect_raises(ValueError, make_perception, content_hash="z" * 64)


@test
def test_perception_blank_source_rejected():
    expect_raises(ValueError, make_perception, source="")


@test
def test_perception_hash_bytes_matches_sha256():
    import hashlib

    data = b"some image bytes"
    assert PerceptionRecord.hash_bytes(data) == hashlib.sha256(data).hexdigest()


@test
def test_perception_hash_bytes_is_deterministic():
    data = b"same photo, submitted twice"
    assert PerceptionRecord.hash_bytes(data) == PerceptionRecord.hash_bytes(data)


@test
def test_perception_raw_response_defaults_to_empty_dict():
    p = make_perception()
    assert p.raw_response == {}


@test
def test_perception_raw_response_must_be_dict():
    expect_raises(TypeError, make_perception, raw_response=["oops"])


# ---------------------------------------------------------------------------
# Case
# ---------------------------------------------------------------------------


@test
def test_case_valid_construction():
    c = make_case()
    assert c.status == "open"


@test
def test_case_additive_intake_fields_and_bank_last4():
    c = make_case(vehicle_make="Honda", policy_number="POL-1", bank_account_last4="1234")
    assert c.vehicle_make == "Honda"
    assert c.policy_number == "POL-1"
    assert c.bank_account_last4 == "1234"


@test
def test_case_rejects_full_bank_account_storage():
    expect_raises(ValueError, make_case, bank_account_last4="123456789")


@test
def test_admin_reject_requires_reason_in_model():
    expect_raises(ValueError, AdminActionRecord,
                  case_id="case-1", admin_id="admin", action=AdminAction.REJECT)


@test
def test_case_blank_case_id_rejected():
    expect_raises(ValueError, make_case, case_id="")


@test
def test_case_blank_claimant_id_rejected():
    expect_raises(ValueError, make_case, claimant_id="")


@test
def test_case_blank_garage_id_rejected():
    expect_raises(ValueError, make_case, garage_id="   ")


@test
def test_case_blank_claim_type_rejected():
    expect_raises(ValueError, make_case, claim_type="")


@test
def test_case_latitude_out_of_range_rejected():
    expect_raises(ValueError, make_case, latitude=91.0)


@test
def test_case_longitude_out_of_range_rejected():
    expect_raises(ValueError, make_case, longitude=-181.0)


@test
def test_case_lat_lon_none_is_valid():
    c = make_case(latitude=None, longitude=None)
    assert c.latitude is None and c.longitude is None


@test
def test_case_boundary_lat_lon_are_valid():
    c = make_case(latitude=90.0, longitude=-180.0)
    assert c.latitude == 90.0 and c.longitude == -180.0


# ---------------------------------------------------------------------------
# ImageArtifact
# ---------------------------------------------------------------------------


@test
def test_artifact_valid_construction():
    a = make_artifact()
    assert a.role == "unspecified"


@test
def test_artifact_invalid_hash_rejected():
    expect_raises(ValueError, make_artifact, content_hash="not-a-hash")


@test
def test_artifact_blank_filename_rejected():
    expect_raises(ValueError, make_artifact, filename="")


@test
def test_artifact_blank_case_id_rejected():
    expect_raises(ValueError, make_artifact, case_id="")


@test
def test_artifact_custom_role_is_kept():
    a = make_artifact(role="odometer")
    assert a.role == "odometer"


# ---------------------------------------------------------------------------
# db.py - real sqlite, in-memory unless noted
# ---------------------------------------------------------------------------


def fresh_conn() -> sqlite3.Connection:
    conn = db.connect(":memory:")
    db.init_db(conn)
    return conn


@test
def test_db_init_creates_expected_tables():
    conn = fresh_conn()
    tables = {
        r["name"]
        for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    }
    assert {"cases", "findings", "perception_records", "image_artifacts", "agent_decisions"} <= tables
    conn.close()


@test
def test_db_init_migrates_old_schema_before_creating_migration_indexes():
    conn = db.connect(":memory:")
    conn.executescript(
        """
        CREATE TABLE cases (
            case_id TEXT PRIMARY KEY,
            claimant_id TEXT NOT NULL,
            garage_id TEXT NOT NULL,
            claim_type TEXT NOT NULL,
            declared_time TEXT,
            declared_location TEXT,
            latitude REAL,
            longitude REAL,
            agent_type TEXT NOT NULL DEFAULT 'claims',
            claim_amount REAL,
            vehicle_registration TEXT,
            status TEXT NOT NULL DEFAULT 'open',
            created_at TEXT NOT NULL
        );
        CREATE TABLE agent_decisions (
            decision_id TEXT PRIMARY KEY,
            case_id TEXT NOT NULL,
            recommendation TEXT NOT NULL,
            confidence REAL NOT NULL,
            summary TEXT NOT NULL,
            supporting_finding_ids TEXT NOT NULL,
            requested_artifacts TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        """
    )

    db.init_db(conn)

    case_columns = {r["name"] for r in conn.execute("PRAGMA table_info(cases)").fetchall()}
    decision_columns = {r["name"] for r in conn.execute("PRAGMA table_info(agent_decisions)").fetchall()}
    indexes = {
        r["name"]
        for r in conn.execute("SELECT name FROM sqlite_master WHERE type='index'").fetchall()
    }
    assert "policy_number" in case_columns
    assert "policy_version" in decision_columns
    assert "latency_ms" in decision_columns
    assert "idx_cases_policy_number" in indexes
    assert "idx_decisions_policy" in indexes
    conn.close()


@test
def test_db_insert_and_get_case_roundtrips():
    conn = fresh_conn()
    c = make_case(vehicle_make="Honda", policy_number="POL-1", bank_account_last4="1234")
    db.insert_case(conn, c)
    fetched = db.get_case(conn, c.case_id)
    assert fetched is not None
    assert fetched.case_id == c.case_id
    assert fetched.garage_id == c.garage_id
    assert fetched.vehicle_make == "Honda"
    assert fetched.policy_number == "POL-1"
    assert fetched.bank_account_last4 == "1234"
    conn.close()


@test
def test_db_get_missing_case_returns_none():
    conn = fresh_conn()
    assert db.get_case(conn, "does-not-exist") is None
    conn.close()


@test
def test_db_insert_and_get_findings_for_case():
    conn = fresh_conn()
    db.insert_case(conn, make_case())
    db.insert_finding(conn, make_finding())
    db.insert_finding(conn, make_finding(check_id="duplicate_hash"))
    findings = db.get_findings_for_case(conn, "case-1")
    assert len(findings) == 2
    conn.close()


@test
def test_db_finding_evidence_roundtrips_through_json():
    conn = fresh_conn()
    db.insert_case(conn, make_case())
    db.insert_finding(conn, make_finding(evidence={"solar_azimuth_deg": 288.4, "nested": {"a": 1}}))
    fetched = db.get_findings_for_case(conn, "case-1")[0]
    assert fetched.evidence["solar_azimuth_deg"] == 288.4
    assert fetched.evidence["nested"]["a"] == 1
    conn.close()


@test
def test_db_perception_record_missing_returns_none():
    conn = fresh_conn()
    assert db.get_perception_record(conn, HASH_A) is None
    conn.close()


@test
def test_db_perception_record_insert_and_get():
    conn = fresh_conn()
    db.upsert_perception_record(conn, make_perception(embedding=[0.1, 0.2, 0.3]))
    fetched = db.get_perception_record(conn, HASH_A)
    assert fetched is not None
    assert fetched.embedding == [0.1, 0.2, 0.3]
    conn.close()


@test
def test_db_perception_record_upsert_dedups_on_content_hash():
    # This is the whole point: same content_hash, second call updates
    # in place rather than costing a second row / second API call.
    conn = fresh_conn()
    db.upsert_perception_record(conn, make_perception(caption="first pass"))
    db.upsert_perception_record(conn, make_perception(caption="re-analysed, corrected caption"))
    count = conn.execute("SELECT COUNT(*) AS n FROM perception_records").fetchone()["n"]
    assert count == 1
    fetched = db.get_perception_record(conn, HASH_A)
    assert fetched.caption == "re-analysed, corrected caption"
    conn.close()


@test
def test_db_insert_image_artifact_links_case_and_hash():
    conn = fresh_conn()
    db.insert_case(conn, make_case())
    db.upsert_perception_record(conn, make_perception())
    db.insert_image_artifact(conn, make_artifact())
    artifacts = db.get_artifacts_for_case(conn, "case-1")
    assert len(artifacts) == 1
    assert artifacts[0].content_hash == HASH_A
    conn.close()


@test
def test_db_insert_agent_decision_and_fetch():
    conn = fresh_conn()
    db.insert_case(conn, make_case())
    db.insert_agent_decision(
        conn,
        make_decision(
            recommendation=Recommendation.REQUEST_EVIDENCE,
            requested_artifacts=["odometer photo"],
        ),
    )
    decisions = db.get_decisions_for_case(conn, "case-1")
    assert len(decisions) == 1
    assert decisions[0].requested_artifacts == ["odometer photo"]
    conn.close()


@test
def test_db_insert_admin_action_and_fetch_latest():
    conn = fresh_conn()
    db.insert_case(conn, make_case())
    db.insert_admin_action(conn, AdminActionRecord(
        case_id="case-1", admin_id="admin-1", action=AdminAction.APPROVE,
        timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc)))
    db.insert_admin_action(conn, AdminActionRecord(
        case_id="case-1", admin_id="admin-2", action=AdminAction.REJECT,
        reason="confirmed mismatch",
        timestamp=datetime(2026, 1, 2, tzinfo=timezone.utc)))
    actions = db.get_admin_actions_for_case(conn, "case-1")
    latest = db.get_latest_admin_action(conn, "case-1")
    assert [a.action for a in actions] == [AdminAction.APPROVE, AdminAction.REJECT]
    assert latest is not None and latest.action is AdminAction.REJECT
    assert latest.reason == "confirmed mismatch"
    conn.close()


@test
def test_db_foreign_key_violation_is_enforced():
    conn = fresh_conn()
    # No matching case row inserted - this must fail, not silently succeed.
    expect_raises(sqlite3.IntegrityError, db.insert_finding, conn, make_finding(case_id="ghost-case"))
    conn.close()


@test
def test_db_two_cases_do_not_collide():
    conn = fresh_conn()
    db.insert_case(conn, make_case(case_id="case-1"))
    db.insert_case(conn, make_case(case_id="case-2", garage_id="garage-2"))
    db.insert_finding(conn, make_finding(case_id="case-1"))
    db.insert_finding(conn, make_finding(case_id="case-2"))
    assert len(db.get_findings_for_case(conn, "case-1")) == 1
    assert len(db.get_findings_for_case(conn, "case-2")) == 1
    conn.close()


@test
def test_db_data_persists_across_connections_on_disk():
    # Integration check that this isn't just an in-memory illusion -
    # writes actually land on a real .db file on disk.
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "fraudlens_test.db"
        with db.session(db_path) as conn:
            db.insert_case(conn, make_case())
            db.insert_finding(conn, make_finding())

        with db.session(db_path) as conn2:
            fetched_case = db.get_case(conn2, "case-1")
            fetched_findings = db.get_findings_for_case(conn2, "case-1")

        assert fetched_case is not None
        assert len(fetched_findings) == 1


@test
def test_db_perception_record_with_no_embedding_roundtrips_as_none():
    conn = fresh_conn()
    db.upsert_perception_record(conn, make_perception(embedding=None))
    fetched = db.get_perception_record(conn, HASH_A)
    assert fetched.embedding is None
    conn.close()


@test
def test_legacy_case_read_without_optional_notes_column():
    conn=fresh_conn()
    try:
        db.insert_case(conn,make_case())
        conn.execute('ALTER TABLE cases DROP COLUMN declaration_notes')
        assert db.get_case(conn,'case-1').declaration_notes is None
        assert db.get_all_cases(conn)[0].declaration_notes is None
    finally:conn.close()


if __name__ == "__main__":
    ok = run_all()
    sys.exit(0 if ok else 1)
