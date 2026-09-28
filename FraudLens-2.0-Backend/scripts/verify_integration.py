"""
End-to-end integration check: does a case survive the whole pipeline?

This asserts the seams rather than the units. It drives a case through
submission, checks, adjudication, persistence, and HTTP readback exactly as
the frontend would. No LLM calls are made; adjudication is stubbed.

Everything runs against a temporary database copy, so it is safe to run while
an ablation driver is live.

Usage:
    python scripts/verify_integration.py
"""

from __future__ import annotations

import hashlib
import os
import shutil
import sys
import tempfile
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]

from fastapi.testclient import TestClient

from src import db
from src.agent.engine import AdjudicationResult, TraceStep
from src.checks import run_checks
from src.models import AgentDecision, Recommendation, RiskBand, Verdict
from src.orchestrator import adjudication_event

_failures: list[str] = []


def check(label: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"  PASS  {label}")
    else:
        suffix = f" - {detail}" if detail else ""
        _failures.append(f"{label}{suffix}")
        print(f"  FAIL  {label}{suffix}")


def corpus_vehicle_image() -> Path:
    candidates = sorted(Path("data/curated/whole").glob("*.jpg"))
    if not candidates:
        candidates = sorted(Path("data/curated/damaged").glob("*.jpg"))
    if not candidates:
        raise RuntimeError("no curated vehicle image found")
    return candidates[0]


def stub_adjudicate(conn, case, findings, policy, provider):
    """A canned adjudication with a realistic trace. No model involved."""
    concerns = [f for f in findings if f.verdict is Verdict.CONCERN]
    band = RiskBand.ESCALATE_SIU if concerns else RiskBand.CLEAR
    decision = AgentDecision(
        case_id=case.case_id,
        recommendation=(Recommendation.ESCALATE if concerns else Recommendation.APPROVE),
        confidence=0.8,
        summary=(f"Integration check: {len(concerns)} concern(s) raised. "
                 "This narrative exists so the decision panel has something to render."),
        supporting_finding_ids=[f.finding_id for f in concerns][:3],
        requested_artifacts=["A clear photograph of the registration plate"],
        policy_version=policy.policy_version,
        risk_band=band,
        tool_calls_count=1,
        iterations_count=2,
        llm_calls_count=2,
        latency_ms=1200,
    )
    trace = [
        TraceStep(
            0,
            "tool_call",
            "get_claimant_history",
            {"args": {"claimant_id": case.claimant_id},
             "result_keys": ["cases", "total_claimed_inr"]},
            40,
        ),
        TraceStep(
            1,
            "llm_call",
            f"decision: {band.value}",
            {"recommendation": decision.recommendation.value},
            60,
        ),
    ]
    return AdjudicationResult(decision, trace, converged=True)


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="fraudlens_integration_"))
    db_path = tmp / "integration.db"
    shutil.copy("fraudlens.db", db_path)
    original_run_pipeline = None

    try:
        from src import api

        api.DB_PATH = str(db_path)
        api._JOBS.clear()
        original_run_pipeline = api._run_pipeline
        api._run_pipeline = lambda job_id, case_id: api._set_job(
            job_id,
            status="done",
            stage="test-stubbed",
            progress=1.0,
            case_id=case_id,
            detail="Integration harness stubbed background adjudication.",
        )
        os.environ["ADMIN_PASSWORD_SHA256"] = hashlib.sha256(
            b"integration-admin").hexdigest()
        client = TestClient(api.app)
        client.headers.update({"Authorization": "Bearer integration-admin"})

        print("\n1. submit a case through the API")
        with corpus_vehicle_image().open("rb") as fh:
            response = client.post(
                "/v1/cases",
                data={
                    "agent_type": "claims",
                    "declared_location": "Andheri, Mumbai",
                    "claim_amount": "48750",
                    "vehicle_registration": "MH01AB1234",
                },
                files={"images": ("vehicle.jpg", fh, "image/jpeg")},
            )
        check("POST /v1/cases returns 201", response.status_code == 201, response.text)
        if response.status_code != 201:
            return 1
        case_id = response.json()["case_id"]
        print(f"     case_id = {case_id}")

        conn = db.connect(db_path)
        case = db.get_case(conn, case_id)
        check("case row persisted", case is not None)

        print("\n2. run checks on a real corpus case")
        corpus_case = next(
            c for c in db.get_all_cases(conn)
            if c.agent_type == "claims" and db.get_images_for_case(conn, c.case_id)
        )
        from src.agent.policy import policy_for

        policy = policy_for(corpus_case.agent_type)
        findings = run_checks(conn, corpus_case, check_ids=list(policy.check_ids))
        check("checks produced findings", len(findings) > 0, f"{len(findings)} findings")

        print("\n3. adjudicate (stubbed) and persist every artefact")
        result = stub_adjudicate(conn, corpus_case, findings, policy, None)
        for finding in findings:
            try:
                db.insert_finding(conn, finding)
            except Exception:  # noqa: BLE001 - already stored by an earlier pass
                pass
        db.insert_agent_decision(conn, result.decision)
        db.log_audit_event(conn, adjudication_event(
            case_id=corpus_case.case_id,
            arm="agent",
            policy_version=policy.policy_version,
            decision=result.decision,
            converged=result.converged,
            trace=result.trace_dicts(),
        ))
        conn.commit()

        print("\n4. every table the interface depends on has rows")
        for table in ("cases", "images", "findings", "agent_decisions", "audit_log"):
            n = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            check(f"{table} is populated", n > 0, f"{n} rows")
        conn.close()

        print("\n5. read it back through the API, as the frontend does")
        detail = client.get(f"/v1/cases/{corpus_case.case_id}")
        check("GET case detail returns 200", detail.status_code == 200, detail.text[:200])
        body = detail.json()

        grouped = body.get("findings_by_category") or {}
        total_findings = sum(len(v) for v in grouped.values())
        check("findings present in the detail payload", total_findings > 0,
              "the Findings panel would render blank")
        check("findings are grouped by category", len(grouped) == 5, f"{len(grouped)} groups")
        check("decision present with a narrative",
              bool((body.get("decision") or {}).get("summary")))
        check("decision carries a risk band",
              bool((body.get("decision") or {}).get("risk_band")))
        check("images carry a fetchable url",
              all(i.get("url") for i in body.get("images", [])))

        print("\n6. image bytes actually serve")
        if body.get("images"):
            img = client.get(body["images"][0]["url"])
            check("GET image returns bytes", img.status_code == 200 and len(img.content) > 0,
                  f"status {img.status_code}")
            check("image has an image content-type",
                  img.headers.get("content-type", "").startswith("image/"),
                  img.headers.get("content-type", ""))

        print("\n7. the trace is complete, with tool inputs and outputs")
        trace = client.get(f"/v1/cases/{corpus_case.case_id}/trace")
        check("GET trace returns 200", trace.status_code == 200)
        steps = trace.json().get("steps", [])
        check("trace has steps", len(steps) > 0, "the Agent trace page would be empty")
        tool_steps = [s for s in steps if s["kind"] == "tool_call"]
        check("trace contains a tool call", len(tool_steps) > 0)
        if tool_steps:
            check("tool call records its input", bool(tool_steps[0].get("tool_input")),
                  "tool_input missing - the trace cannot show what was asked")
            check("tool call records what came back", bool(tool_steps[0].get("tool_output")),
                  "tool_output missing - the trace cannot show the answer")

        print("\n8. dashboard aggregates are non-trivial")
        stats = client.get("/v1/stats").json()
        check("stats report findings", stats.get("total_findings", 0) > 0)
        check("stats report concerns by check", bool(stats.get("concerns_by_check")))
        check("stats report a straight-through rate",
              stats.get("straight_through_rate") is not None)

    except Exception as e:  # noqa: BLE001
        print(f"\nFAIL  integration check raised {type(e).__name__}: {e}")
        traceback.print_exc()
        _failures.append(f"unhandled exception: {type(e).__name__}: {e}")
    finally:
        if original_run_pipeline is not None:
            api._run_pipeline = original_run_pipeline
        shutil.rmtree(tmp, ignore_errors=True)

    print()
    if _failures:
        print(f"{len(_failures)} INTEGRATION FAILURE(S):")
        for failure in _failures:
            print(f"  - {failure}")
        return 1
    print("integration verified: every seam carries data end to end")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
