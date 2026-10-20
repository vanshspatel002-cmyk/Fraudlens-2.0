"""
Test suite for the HTTP API.

Entirely offline, in two distinct senses, and both matter:

  1. **No LLM is called.** POST /v1/cases schedules the adjudication
     pipeline as a FastAPI background task, and TestClient runs background
     tasks for real once the response is returned. Left alone, a single
     submit test would fire the whole check battery and a live Gemini call.
     `src.api._run_pipeline` is therefore replaced for the duration of the
     test. This is not incidental tidiness - it is the difference between a
     suite that runs on a spent free tier and one that does not.

  2. **No production data is touched.** Every test runs against a
     purpose-built temporary database with real image files on disk, so the
     image-serving tests can assert actual bytes rather than mocking the
     filesystem and proving nothing.

Run with:
    python test_api.py
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import shutil
import sqlite3
import sys
import tempfile
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

sys.path.insert(0, str(Path(__file__).resolve().parent))

from fastapi.testclient import TestClient
from PIL import Image as PILImage, ImageDraw

from src import api, db
from src.agent.engine import TraceStep
from src.orchestrator import adjudication_event
from src.models import (AgentDecision, AuditEvent, Case, CheckCategory, Finding,
                        Image, Recommendation, RiskBand, Verdict)

_TESTS: list = []
_TMP: Optional[Path] = None
_CLIENT: Optional[TestClient] = None

# A one-pixel PNG. Small enough to inline, real enough that PIL and the
# content-type sniffing both behave as they would on a genuine file.
PNG_BYTES = bytes.fromhex(
    "89504e470d0a1a0a0000000d494844520000000100000001080200000090"
    "7753de0000000c4944415408d763f8cfc00000030101003d0a0a"
    "b40000000049454e44ae426082"
)


def non_vehicle_png_bytes() -> bytes:
    """A simple document-like image: real image bytes, clearly not a vehicle."""
    im = PILImage.new("RGB", (512, 512), "white")
    d = ImageDraw.Draw(im)
    d.rectangle((60, 50, 452, 462), outline="black", width=4)
    for y in range(80, 420, 36):
        d.rectangle((90, y, 420, y + 9), fill="black")
    out = io.BytesIO()
    im.save(out, format="PNG")
    return out.getvalue()


def corpus_vehicle_path() -> Path:
    candidates = sorted(Path("data/curated/whole").glob("*.jpg"))
    if not candidates:
        candidates = sorted(Path("data/curated/damaged").glob("*.jpg"))
    assert candidates, "test requires at least one real corpus vehicle image"
    return candidates[0]


def test(fn):
    _TESTS.append(fn)
    return fn


# ---------------------------------------------------------------------------
# Fixture
# ---------------------------------------------------------------------------

def build_fixture() -> tuple[Path, TestClient]:
    tmp = Path(tempfile.mkdtemp(prefix="fraudlens_api_test_"))
    db_path = tmp / "test.db"
    img_dir = tmp / "images"
    img_dir.mkdir()

    img_a = img_dir / "a.png"
    img_a.write_bytes(PNG_BYTES)

    conn = db.connect(db_path)
    db.init_db(conn)

    claims = Case(
        case_id="case-claims-1", claimant_id="CLM-1", garage_id="GAR-1",
        claim_type="motor_claim", declared_time=datetime(2026, 1, 5, tzinfo=timezone.utc),
        declared_location="Andheri, Mumbai", latitude=19.11, longitude=72.86,
        agent_type="claims", claim_amount=48000.0, vehicle_registration="MH01AB1234",
        vehicle_make="Maruti", vehicle_model="Swift", vehicle_variant="ZXI",
        vehicle_year=2022, fuel_type="petrol", idv=525000.0,
        policy_number="POL-CLAIMS-1", policy_type="comprehensive",
        previous_policy_number="OLD-POL-1", policy_ncb_percent=20.0,
        person_name="Asha Shah", person_contact="9876543210",
        driving_license_number="DL-0420110012345", fir_number="FIR-7",
        settlement_preference="bank_transfer", bank_account_last4="1234",
        status="open",
    )
    underwriting = Case(
        case_id="case-uw-1", claimant_id="CLM-2", garage_id="GAR-2",
        claim_type="underwriting_inspection",
        declared_time=datetime(2026, 2, 1, tzinfo=timezone.utc),
        declared_location="Manjalpur, Vadodara", latitude=22.27, longitude=73.19,
        agent_type="underwriting", claim_amount=None,
        vehicle_registration="GJ27PT7711", status="open",
    )
    for case in (claims, underwriting):
        db.insert_case(conn, case)

    db.save_image(conn, Image(image_id="img-1", case_id="case-claims-1",
                              path=str(img_a), content_hash=hashlib.sha256(PNG_BYTES).hexdigest(),
                              phash="0"*16, dhash="0"*16))
    # A row whose file does not exist, to pin down the 404-not-500 behaviour.
    db.save_image(conn, Image(image_id="img-missing", case_id="case-claims-1",
                              path=str(img_dir / "gone.png"), content_hash=hashlib.sha256(b"gone").hexdigest(),
                              phash="1"*16, dhash="1"*16))

    db.insert_finding(conn, Finding(
        check_id="external_corpus", case_id="case-claims-1",
        category=CheckCategory.HISTORY, verdict=Verdict.CONCERN, confidence=0.95,
        explanation="Image found in an external index.", evidence={"similarity": 1.0},
        finding_id="find-1",
    ))
    db.insert_finding(conn, Finding(
        check_id="exif_metadata", case_id="case-claims-1",
        category=CheckCategory.PROVENANCE, verdict=Verdict.PASS, confidence=0.6,
        explanation="Metadata consistent.", evidence={}, finding_id="find-2",
    ))

    decision = AgentDecision(
        case_id="case-claims-1", recommendation=Recommendation.ESCALATE,
        confidence=0.9, summary="Escalated: image sourced externally.",
        supporting_finding_ids=["find-1"], requested_artifacts=[],
        policy_version="agent-claims-v1", risk_band=RiskBand.ESCALATE_SIU,
        score=1.0, tool_calls_count=2, iterations_count=3, llm_calls_count=3,
        latency_ms=15000, decision_id="dec-1",
    )
    db.insert_agent_decision(conn, decision)
    # Built by the production producer, not by hand. The previous fixture
    # invented a three-key subset with a "content" field no producer emits,
    # which is why the API silently dropping every tool payload looked
    # correct: the test agreed with the broken code instead of with reality.
    db.log_audit_event(conn, adjudication_event(
        case_id="case-claims-1",
        arm="agent",
        policy_version="agent-claims-v1",
        decision=decision,
        converged=True,
        trace=[
            TraceStep(0, "tool_call", "get_claimant_history",
                      {"args": {"claimant_id": "CLM-1"},
                       "result_keys": ["claims", "total"]}, 120).to_dict(),
            TraceStep(1, "parse_failure", "reply was not a usable decision object",
                      {"reply_preview": "not json"}, 90).to_dict(),
            TraceStep(2, "fallback",
                      "provider error: ClientError: 429 RESOURCE_EXHAUSTED", {}, 0).to_dict(),
            TraceStep(3, "llm_call", "decision: escalate_siu",
                      {"recommendation": "escalate"}, 800).to_dict(),
        ],
    ))
    conn.commit()
    conn.close()

    api.DB_PATH = str(db_path)
    api.UPLOAD_DIR = tmp / 'uploads'
    api.THUMB_DIR = tmp / 'thumbnails'
    os.environ['FRAUDLENS_WORKER_ENABLED']='0'
    os.environ["ADMIN_EMAIL"] = "reviewer@example.com"
    os.environ["ADMIN_PASSWORD_SHA256"] = hashlib.sha256(b"test-admin").hexdigest()
    api._ARCHETYPES = {"case-claims-1": "EXTERNAL_SOURCING", "case-uw-1": "CLEAN"}
    api._JOBS.clear()
    test_client = TestClient(api.app)
    login = test_client.post('/v1/auth/login',json={'email':'reviewer@example.com','password':'test-admin'})
    assert login.status_code==200,login.text
    test_client.headers.update({'Authorization':'Bearer '+login.json()['token']})
    return tmp, test_client


def client() -> TestClient:
    assert _CLIENT is not None
    return _CLIENT


# ---------------------------------------------------------------------------
# Listing, filtering, pagination
# ---------------------------------------------------------------------------

@test
def test_list_returns_all_cases_with_summary_fields():
    r = client().get("/v1/cases")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total"] == 2, body
    ids = {i["case_id"] for i in body["items"]}
    assert ids == {"case-claims-1", "case-uw-1"}, ids
    claims = next(i for i in body["items"] if i["case_id"] == "case-claims-1")
    assert claims["concern_count"] == 1, claims
    assert claims["image_count"] == 2, claims
    assert claims["risk_band"] == "escalate_siu", claims
    print(f"  2 cases, summary carries risk_band/concern_count/image_count")


@test
def test_filter_by_agent_type():
    r = client().get("/v1/cases", params={"agent_type": "underwriting"})
    body = r.json()
    assert body["total"] == 1, body
    assert body["items"][0]["case_id"] == "case-uw-1"
    print("  agent_type filter isolates the underwriting case")


@test
def test_filter_by_risk_band():
    """risk_band lives on the decision, not the case row - the filter must still work."""
    hit = client().get("/v1/cases", params={"risk_band": "escalate_siu"}).json()
    assert hit["total"] == 1 and hit["items"][0]["case_id"] == "case-claims-1", hit
    miss = client().get("/v1/cases", params={"risk_band": "clear"}).json()
    assert miss["total"] == 0, miss
    print("  risk_band filter works despite living on a joined decision")


@test
def test_filter_by_archetype_and_status():
    a = client().get("/v1/cases", params={"archetype": "CLEAN"}).json()
    assert a["total"] == 1 and a["items"][0]["case_id"] == "case-uw-1", a
    s = client().get("/v1/cases", params={"status": "open"}).json()
    assert s["total"] == 2, s
    print("  archetype and status filters work")


@test
def test_pagination_slices_without_overlap():
    first = client().get("/v1/cases", params={"page": 1, "page_size": 1}).json()
    second = client().get("/v1/cases", params={"page": 2, "page_size": 1}).json()
    assert len(first["items"]) == 1 and len(second["items"]) == 1
    assert first["items"][0]["case_id"] != second["items"][0]["case_id"]
    # total must describe the whole filtered set, not the page - otherwise
    # the frontend cannot render a pager.
    assert first["total"] == 2 and second["total"] == 2, (first["total"], second["total"])
    assert first["has_more"] is True and second["has_more"] is False
    print("  pages disjoint; total reflects the full set; has_more terminates")


@test
def test_pagination_rejects_out_of_range_page_size():
    assert client().get("/v1/cases", params={"page_size": 0}).status_code == 422
    assert client().get("/v1/cases", params={"page_size": 10_000}).status_code == 422
    # The envelope names the field, so a form can highlight the input.
    body = client().get("/v1/cases", params={"page_size": 10_000}).json()
    assert body["code"] == "VALIDATION_FAILED", body
    assert body["details"] and body["details"][0]["field"], body
    print("  page_size bounds enforced, and the error names the field")


# ---------------------------------------------------------------------------
# Detail, trace
# ---------------------------------------------------------------------------

@test
def test_case_detail_groups_findings_by_category():
    body = client().get("/v1/cases/case-claims-1").json()
    grouped = body["findings_by_category"]
    assert set(grouped) == {c.value for c in CheckCategory}, set(grouped)
    assert len(grouped["history"]) == 1, grouped["history"]
    assert grouped["history"][0]["check_id"] == "external_corpus"
    assert len(grouped["provenance"]) == 1
    assert body["decision"]["risk_band"] == "escalate_siu"
    assert body["images"][0]["url"] == "/v1/images/img-1"
    print("  detail groups by all 5 categories and embeds decision + image urls")


@test
def test_missing_case_returns_the_error_envelope():
    for path in ("/v1/cases/nope", "/v1/cases/nope/trace"):
        r = client().get(path)
        assert r.status_code == 404, (path, r.status_code)
        body = r.json()
        # A frontend branches on `code`; `message` is for humans. The old
        # FastAPI `detail` key is gone deliberately.
        assert body["code"] == "CASE_NOT_FOUND", body
        assert "nope" in body["message"], body
        assert set(body) >= {"status", "code", "message", "details"}, body
    print("  404 returns the coded envelope on detail and trace")


@test
def test_trace_returns_ordered_steps_with_tool_io():
    body = client().get("/v1/cases/case-claims-1/trace").json()
    kinds = [s["kind"] for s in body["steps"]]
    # The fallback step is withheld, so it does not appear here.
    assert kinds == ["tool_call", "parse_failure", "llm_call"], kinds
    assert [s["index"] for s in body["steps"]] == [0, 1, 2]
    assert body["converged"] is True
    assert body["policy_version"] == "agent-claims-v1"

    # Producer kinds are normalised into a small vocabulary a UI can switch on,
    # while the original kind is preserved alongside it.
    types = [s["type"] for s in body["steps"]]
    assert types == ["tool_call", "parse_failure", "reasoning"], types

    # The tool input and output are the whole point of the trace: without them
    # a consumer can say a tool was called but not what it was asked or what
    # came back. This is the assertion that would have caught the API reading
    # a `content` key the producer never writes.
    tool = body["steps"][0]
    assert tool["tool_name"] == "get_claimant_history", tool
    assert tool["tool_input"] == {"claimant_id": "CLM-1"}, tool
    assert tool["tool_output"].get("result_keys") == ["claims", "total"], tool
    assert tool["latency_ms"] == 120, tool
    print(f"  trace ordered, tool io populated: {kinds}")


@test
def test_trace_withholds_provider_outage_steps():
    """
    A 429 is not reasoning, and a demonstration must not show it as such.

    The endpoint withholds those steps and reports how many it withheld, so a
    consumer neither renders an outage as thinking nor silently loses the fact
    that one happened.
    """
    body = client().get("/v1/cases/case-claims-1/trace").json()
    assert body["excluded_outage_steps"] == 1, body
    assert all("provider error" not in (s["content"] or "") for s in body["steps"])
    assert all(s["kind"] != "fallback" for s in body["steps"])
    print(f"  1 outage step withheld, {len(body['steps'])} genuine step(s) shown")


@test
def test_trace_is_empty_not_an_error_for_undecided_case():
    """An undecided case has no trace. That is a valid state, not a 404."""
    r = client().get("/v1/cases/case-uw-1/trace")
    assert r.status_code == 200, r.text
    assert r.json()["steps"] == []
    print("  undecided case returns an empty trace, not an error")


# ---------------------------------------------------------------------------
# Images
# ---------------------------------------------------------------------------

@test
def test_image_serves_correct_bytes_and_content_type():
    r = client().get("/v1/images/img-1")
    assert r.status_code == 200, r.text
    assert r.content == PNG_BYTES, (len(r.content), len(PNG_BYTES))
    assert r.headers["content-type"].startswith("image/png"), r.headers["content-type"]
    print(f"  served {len(r.content)} bytes as {r.headers['content-type']}")


@test
def test_unknown_image_and_missing_file_both_404():
    unknown = client().get("/v1/images/does-not-exist")
    assert unknown.status_code == 404
    assert unknown.json()["code"] == "IMAGE_NOT_FOUND", unknown.json()
    # A DB row whose file has vanished must be 404, not a 500: the resource
    # is genuinely absent and the server is not broken. It gets its own code
    # so a UI can distinguish "no such image" from "the file went away".
    r = client().get("/v1/images/img-missing")
    assert r.status_code == 404, r.status_code
    assert r.json()["code"] == "IMAGE_FILE_MISSING", r.json()
    print("  unknown id and vanished file 404 with distinct codes")


# ---------------------------------------------------------------------------
# Submit, action
# ---------------------------------------------------------------------------

@test
def test_submit_creates_case_and_job_without_calling_the_model():
    calls: list[tuple[str, str]] = []
    original = api._run_pipeline
    api._run_pipeline = lambda job_id, case_id: calls.append((job_id, case_id))
    try:
        vehicle_path = corpus_vehicle_path()
        with open(vehicle_path, "rb") as fh:
            r = client().post(
                "/v1/cases",
                headers={'Authorization':''},
                data={
                    "agent_type": "claims",
                    "declared_location": "Pune",
                    "claim_amount": "25000",
                    "vehicle_registration": "MH12XY9999",
                    "vehicle_make": "Honda",
                    "vehicle_model": "City",
                    "policy_number": "POL-NEW-1",
                    "bank_account_last4": "9876",
                },
                files={"images": ("vehicle.jpg", fh, "image/jpeg")},
            )
        assert r.status_code == 201, r.text
        body = r.json()
        assert body["status"] == "queued"
        # The case must be persisted and immediately fetchable - the
        # frontend navigates to it straight after submitting.
        detail = client().get(f"/v1/cases/{body['case_id']}")
        assert detail.status_code == 200, detail.text
        assert detail.json()["agent_type"] == "claims"
        assert detail.json()["vehicle_make"] == "Honda"
        assert detail.json()["policy_number"] == "POL-NEW-1"
        assert detail.json()["bank_account_last4"] == "9876"
        assert calls == [], calls
        assert client().get('/v1/jobs/'+body['job_id']).json()['status']=='queued'
    finally:
        api._run_pipeline = original
    print("  submit persists the case, queues a job, and calls no model")


@test
def test_submit_rejects_non_vehicle_before_case_creation():
    before = client().get("/v1/cases").json()["total"]
    r = client().post(
        "/v1/cases",
        headers={'Authorization':''},
        data={"agent_type": "claims", "vehicle_registration": "MH12NO0001"},
        files={"images": ("document.png", non_vehicle_png_bytes(), "image/png")},
    )
    assert r.status_code == 422, r.text
    body = r.json()
    assert body["code"] == "VEHICLE_IMAGE_REQUIRED", body
    after = client().get("/v1/cases").json()["total"]
    assert after == before, (before, after)
    print("  non-vehicle upload rejected before a case id is consumed")


@test
def test_clip_gate_accepts_corpus_vehicle_and_rejects_document_image():
    from src import vehicle_gate

    vehicle = vehicle_gate.classify_image(corpus_vehicle_path())
    with tempfile.TemporaryDirectory(prefix="fraudlens_gate_test_") as tmp:
        doc = Path(tmp) / "document.png"
        doc.write_bytes(non_vehicle_png_bytes())
        non_vehicle = vehicle_gate.classify_image(doc)

    assert vehicle.accepted, vehicle
    assert not non_vehicle.accepted, non_vehicle
    print(f"  CLIP gate vehicle score {vehicle.vehicle_score:.3f}, "
          f"document score {non_vehicle.vehicle_score:.3f}")


@test
def test_job_status_is_pollable_and_unknown_job_404s():
    original = api._run_pipeline
    api._run_pipeline = lambda job_id, case_id: None
    try:
        with open(corpus_vehicle_path(), "rb") as fh:
            body = client().post(
                "/v1/cases",
                headers={'Authorization':''},
                data={'agent_type':'underwriting','vehicle_registration':'MH12UW0001'},
                files={"images": ("vehicle.jpg", fh, "image/jpeg")},
            ).json()
        job = client().get(f"/v1/jobs/{body['job_id']}")
        assert job.status_code == 200, job.text
        assert job.json()["case_id"] == body["case_id"]
        assert job.json()["status"] in {"queued", "running", "done", "failed"}
    finally:
        api._run_pipeline = original
    assert client().get("/v1/jobs/unknown").status_code == 404
    print("  job pollable; unknown job 404s")


@test
def test_action_updates_status_and_writes_an_audit_event():
    r = client().post("/v1/cases/case-uw-1/action",
                      json={"action": "request_more_evidence", "reason": "need plate", "requested_artifacts": ['A clear registration plate photograph'],
                            "admin_id": "adjuster-7"})
    assert r.status_code == 200, r.text
    assert r.json()['status']=='awaiting_evidence'
    assert client().get('/v1/cases/case-uw-1').json()['status']=='awaiting_evidence'

    conn = db.connect(api.DB_PATH)
    try:
        events = [e for e in db.get_audit_events_for_case(conn, "case-uw-1")
                  if e.event_type == "admin_action"]
        actions = db.get_admin_actions_for_case(conn, "case-uw-1")
    finally:
        conn.close()
    assert events and events[-1].details["action"] == "request_more_evidence", events
    assert events[-1].details["admin_id"] == "reviewer@example.com"
    assert actions and actions[-1].action.value == "request_more_evidence"
    print("  admin action updates status and leaves an audit trail")


@test
def test_admin_reject_requires_reason_and_closes_case():
    missing = client().post("/v1/cases/case-uw-1/action",
                            json={"action": "reject", "admin_id": "admin-1"})
    assert missing.status_code == 422, missing.text

    reject = client().post("/v1/cases/case-uw-1/action",
                           json={"action": "reject", "reason": "confirmed staged loss", "public_message":"The sample evidence did not support this application.",
                                 "admin_id": "admin-1"})
    assert reject.status_code == 200, reject.text
    assert reject.json()["status"] == "closed_rejected"
    assert client().get("/v1/cases/case-uw-1").json()["status"] == "closed_rejected"

    reopen = client().post("/v1/cases/case-uw-1/action",
                           json={"action": "request_more_evidence",
                                 "reason": "upload clearer VIN image", "requested_artifacts": ['A clear VIN photograph'],
                                 "admin_id": "admin-1"})
    assert reopen.status_code == 200, reopen.text
    assert reopen.json()['status']=='awaiting_evidence'

    approve = client().post("/v1/cases/case-claims-1/action",
                            json={"action": "approve", "admin_id": "admin-2"})
    assert approve.status_code == 200, approve.text
    assert approve.json()["status"] == "closed_approved"

    assert client().post("/v1/cases/unknown/action",
                         json={"action": "approve"}).status_code == 404
    print("  reject requires reason; approve/reject close; request-more-evidence reopens")


@test
def test_report_includes_declaration_findings_agent_and_admin_action():
    body = client().get("/v1/cases/case-claims-1/report").json()
    assert body["declaration"]["policy_number"] == "POL-CLAIMS-1", body["declaration"]
    assert body["declaration"]["bank_account_last4"] == "1234", body["declaration"]
    assert body["findings_by_category"]["history"][0]["attributed_to"] == "image"
    assert body["agent_recommendation"]["recommendation"] == "escalate", body["agent_recommendation"]
    assert body["agent_narrative"] == "Escalated: image sourced externally."
    assert body["admin_action"]["action"] == "approve", body["admin_action"]
    assert body["admin_action"]["admin_id"] == "reviewer@example.com"
    print("  report carries declaration, grouped findings, agent narrative, admin action")


@test
def test_public_track_is_narrow_and_verified():
    r = client().get("/v1/track", params={
        "case_id": "case-claims-1",
        "registration_number": "MH01AB1234",
    })
    assert r.status_code == 200, r.text
    body = r.json()
    assert set(body) == {'case_id','agent_type','status','final_admin_action','narrative','processing_status','evidence_request'}, body
    assert body["final_admin_action"] == "approve", body
    assert body["narrative"] == "Your application has been approved by a reviewer."
    assert "findings" not in body and "trace" not in body and "evidence" not in body

    by_policy = client().get("/v1/track", params={
        "case_id": "case-claims-1",
        "policy_number": "POL-CLAIMS-1",
    })
    assert by_policy.status_code == 200, by_policy.text
    wrong = client().get("/v1/track", params={
        "case_id": "case-claims-1",
        "registration_number": "WRONG",
    })
    assert wrong.status_code == 404, wrong.text
    print("  public track verifies pair and returns only status/action/narrative")


# ---------------------------------------------------------------------------
# Dashboard, config, contract
# ---------------------------------------------------------------------------

@test
def test_stats_aggregate_correctly():
    s = client().get("/v1/stats").json()
    assert s["total_cases"] >= 2
    assert s["by_agent_type"]["claims"] >= 1
    assert s["concern_findings"] == 1, s
    assert s["concerns_by_check"]["external_corpus"] == 1, s["concerns_by_check"]
    # Concerns are also grouped by whose conduct they describe, so a dashboard
    # can separate "about the garage" from "about the claimant".
    assert s["concerns_by_attribution"].get("image") == 1, s["concerns_by_attribution"]
    assert s["by_risk_band"]["escalate_siu"] == 1, s["by_risk_band"]
    assert s["decided_cases"] == 1, s
    # Nothing was cleared, so straight-through must be 0.0 - not None, which
    # would read as "not measured".
    assert s["straight_through_rate"] == 0.0, s["straight_through_rate"]
    print(f"  stats: {s['total_cases']} cases, STP {s['straight_through_rate']}")


@test
def test_policies_expose_both_configs():
    body = client().get("/v1/policies").json()
    assert len(body) == 2, body
    by_type = {p["agent_type"]: p for p in body}
    assert set(by_type) == {"claims", "underwriting"}
    assert by_type["claims"]["check_ids"] != by_type["underwriting"]["check_ids"]
    assert "baseline_corruption" in by_type["underwriting"]["check_ids"]
    assert by_type["claims"]["system_prompt"], "prompt must be exposed for review"
    print(f"  policies differ: claims {len(by_type['claims']['check_ids'])} checks, "
          f"underwriting {len(by_type['underwriting']['check_ids'])}")


@test
def test_openapi_is_complete_enough_to_be_a_frontend_contract():
    """
    Every endpoint must declare a response schema.

    The frontend is generated against this document; an endpoint returning
    an undeclared shape is a contract hole that surfaces as a runtime error
    in the browser rather than a failure here.
    """
    spec = client().get("/openapi.json").json()
    expected = {"/v1/cases", "/v1/cases/{case_id}", "/v1/cases/{case_id}/trace",
                "/v1/cases/{case_id}/report", "/v1/cases/{case_id}/action",
                "/v1/track", "/v1/images/{image_id}",
                "/v1/stats", "/v1/policies", "/v1/jobs/{job_id}"}
    missing = expected - set(spec["paths"])
    assert not missing, f"missing paths: {missing}"

    undeclared = []
    for path, methods in spec["paths"].items():
        for method, op in methods.items():
            ok = op.get("responses", {}).get("200") or op.get("responses", {}).get("201")
            if not ok or "content" not in ok:
                undeclared.append(f"{method.upper()} {path}")
    assert not undeclared, f"no declared success schema: {undeclared}"
    print(f"  {len(spec['paths'])} paths, all with declared success schemas")


@test
def test_cors_headers_present_for_a_cross_origin_request():
    """Without these the frontend fails at the preflight with no useful error."""
    r = client().options("/v1/cases", headers={
        "Origin": "http://localhost:5173",
        "Access-Control-Request-Method": "GET",
    })
    assert r.status_code in (200, 204), r.status_code
    assert r.headers.get("access-control-allow-origin") == "http://localhost:5173", dict(r.headers)
    print("  CORS preflight allowed for the configured frontend origin")


# ---------------------------------------------------------------------------

def run_all() -> bool:
    passed, failed = 0, 0
    failures = []
    for fn in _TESTS:
        print(f"--- {fn.__name__} ---")
        try:
            fn()
            passed += 1
            print(f"PASS  {fn.__name__}")
        except Exception as e:  # noqa: BLE001
            failed += 1
            failures.append((fn.__name__, traceback.format_exc()))
            print(f"FAIL  {fn.__name__}  ->  {type(e).__name__}: {e}")
    if failures:
        print("\n" + "=" * 70)
        for name, tb in failures:
            print(f"FAIL  {name}\n{tb}")
    print(f"\n{passed} passed, {failed} failed")
    return failed == 0


if __name__ == "__main__":
    _TMP, _CLIENT = build_fixture()
    try:
        ok = run_all()
    finally:
        if _TMP:
            shutil.rmtree(_TMP, ignore_errors=True)
    sys.exit(0 if ok else 1)
