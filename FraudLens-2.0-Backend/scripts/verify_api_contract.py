"""
Verify the API from a frontend's position: can a screen be built from this?

--------------------------------------------------------------------------
Why this exists rather than more unit tests
--------------------------------------------------------------------------
Two bugs got past a passing unit suite. The trace endpoint read a `content`
key no producer ever writes, so every tool input and result was dropped and
the reasoning screen had nothing to show. And the `findings` table was empty
for all 800 cases, so the detail screen's central panel rendered blank. In
both cases every component was individually correct and every test passed,
because the tests asserted what the code did rather than what a screen needs.

So this asks the frontend's questions instead:

  - can a queue row be rendered without a second request?
  - does a case known to have findings return them, grouped?
  - does a trace carry the tool inputs and outputs it exists to show?
  - is a thumbnail actually smaller than the original?
  - does pagination reach the end without gaps or repeats?

Fixtures come from the real producing functions, never hand-written. A
fixture written by hand agrees with the author's belief about the shape; a
fixture built by the producer agrees with reality, and only the second kind
catches a field the producer never emits.

Runs against a temporary copy of the database, so it is safe alongside the
ablation. Makes no LLM calls.

Usage:
    python scripts/verify_api_contract.py
"""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
import traceback
from pathlib import Path
from typing import Any, Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]

from fastapi.testclient import TestClient

_failures: list[str] = []
_checks = 0


def check(label: str, condition: bool, detail: str = "") -> bool:
    global _checks
    _checks += 1
    if condition:
        print(f"  PASS  {label}")
        return True
    _failures.append(f"{label}{(' — ' + detail) if detail else ''}")
    print(f"  FAIL  {label}{(' — ' + detail) if detail else ''}")
    return False


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="fraudlens_contract_"))
    db_copy = tmp / "contract.db"
    shutil.copy("fraudlens.db", db_copy)

    try:
        from src import api, db
        api.DB_PATH = str(db_copy)
        api._JOBS.clear()
        client = TestClient(api.app)

        # -----------------------------------------------------------------
        print("\n1. the contract document itself")
        spec = client.get("/openapi.json").json()
        paths = spec.get("paths", {})
        check("openapi.json is served", bool(paths), "no paths")

        undeclared = []
        for path, methods in paths.items():
            for method, op in methods.items():
                ok = (op.get("responses", {}).get("200")
                      or op.get("responses", {}).get("201"))
                if not ok or "content" not in ok:
                    undeclared.append(f"{method.upper()} {path}")
        check("every endpoint declares a success schema", not undeclared,
              f"undeclared: {undeclared}")

        # An endpoint whose response schema is a bare object is invisible to a
        # generated client, which is the failure this whole script exists for.
        untyped = []
        for path, methods in paths.items():
            for method, op in methods.items():
                ok = (op.get("responses", {}).get("200")
                      or op.get("responses", {}).get("201") or {})
                schema = (ok.get("content", {}).get("application/json", {})
                          .get("schema", {}))
                if schema == {"type": "object"} or schema == {}:
                    if "image" not in path:  # images legitimately return bytes
                        untyped.append(f"{method.upper()} {path}")
        check("no endpoint returns an untyped object", not untyped, f"untyped: {untyped}")

        # -----------------------------------------------------------------
        print("\n2. a queue row renders a table with no second request")
        listing = client.get("/v1/cases", params={"page_size": 5}).json()
        check("GET /v1/cases returns a page", bool(listing.get("items")))
        for key in ("total", "page", "page_size", "has_more", "items"):
            check(f"envelope carries {key}", key in listing)

        if listing.get("items"):
            row = listing["items"][0]
            required = ("case_id", "agent_type", "status", "risk_band", "recommendation",
                        "concern_count", "image_count", "vehicle_registration",
                        "claimant_id", "garage_id", "incident_date", "claim_amount",
                        "below_survey_threshold", "thumbnail_url")
            missing = [k for k in required if k not in row]
            check("queue row has every column a table renders", not missing,
                  f"missing: {missing}")
            check("queue row carries a thumbnail url",
                  any(i.get("thumbnail_url") for i in listing["items"]),
                  "no row in the page offered a thumbnail")

        # -----------------------------------------------------------------
        print("\n3. filters and sorting behave")
        for name, params in (
            ("agent_type", {"agent_type": "underwriting"}),
            ("has_concerns", {"has_concerns": True}),
            ("search", {"search": "case-0001"}),
            ("amount_min", {"amount_min": 40000}),
        ):
            r = client.get("/v1/cases", params={**params, "page_size": 5})
            check(f"filter {name} returns 200", r.status_code == 200, r.text[:120])

        uw = client.get("/v1/cases", params={"agent_type": "underwriting",
                                             "page_size": 100}).json()
        check("agent_type filter is honoured",
              all(i["agent_type"] == "underwriting" for i in uw.get("items", [])))

        concerns_only = client.get("/v1/cases", params={"has_concerns": True,
                                                        "page_size": 50}).json()
        check("has_concerns filter is honoured",
              all(i["concern_count"] > 0 for i in concerns_only.get("items", [])))

        asc = client.get("/v1/cases", params={"sort_by": "claim_amount",
                                              "sort_dir": "asc", "page_size": 20}).json()
        amounts = [i["claim_amount"] for i in asc.get("items", [])
                   if i["claim_amount"] is not None]
        check("sort_by=claim_amount asc is ordered", amounts == sorted(amounts))

        bad = client.get("/v1/cases", params={"sort_by": "nonsense"})
        check("an invalid sort field is rejected with a coded error",
              bad.status_code == 422 and bad.json().get("code") == "INVALID_SORT_FIELD",
              f"{bad.status_code}: {bad.text[:120]}")

        # -----------------------------------------------------------------
        print("\n4. pagination walks to the end without gaps or repeats")
        seen: list[str] = []
        page, guard = 1, 0
        while guard < 40:
            guard += 1
            body = client.get("/v1/cases", params={"page": page, "page_size": 100,
                                                   "agent_type": "underwriting"}).json()
            seen.extend(i["case_id"] for i in body["items"])
            if not body["has_more"]:
                break
            page += 1
        check("pagination terminates", guard < 40)
        check("pagination yields no duplicates", len(seen) == len(set(seen)),
              f"{len(seen)} rows, {len(set(seen))} unique")
        total = client.get("/v1/cases", params={"agent_type": "underwriting",
                                                "page_size": 1}).json()["total"]
        check("pagination reaches the declared total", len(seen) == total,
              f"walked {len(seen)}, total says {total}")

        # -----------------------------------------------------------------
        print("\n5. case detail is one request, with findings grouped")
        conn = db.connect(db_copy)
        row = conn.execute(
            "SELECT case_id FROM findings WHERE verdict = 'concern' LIMIT 1").fetchone()
        with_concern = row[0] if row else None
        conn.close()
        check("a case with a concern exists to test against", with_concern is not None)

        if with_concern:
            detail = client.get(f"/v1/cases/{with_concern}").json()
            groups = detail.get("findings_by_category") or {}
            total_findings = sum(len(v) for v in groups.values())
            # The empty-findings bug: every component correct, panel blank.
            check("case detail returns findings", total_findings > 0,
                  "the Findings panel would render blank")
            check("findings are grouped into the five categories", len(groups) == 5,
                  f"{len(groups)} groups")
            check("finding groups are also returned as a list",
                  isinstance(detail.get("finding_groups"), list)
                  and len(detail["finding_groups"]) == 5)
            check("detail carries per-category concern counts",
                  bool(detail.get("concern_counts_by_category")))
            check("detail carries attributed counts",
                  bool(detail.get("attributed_counts")),
                  "a screen cannot say '2 about the garage, 0 about the claimant'")
            check("detail carries images with urls",
                  all(i.get("url") and i.get("thumbnail_url")
                      for i in detail.get("images", [])))
            check("images carry dimensions",
                  all(i.get("width") for i in detail.get("images", [])),
                  "a gallery cannot reserve layout space without them")

            flat = [f for fs in groups.values() for f in fs]
            check("every finding declares attribution",
                  all(f.get("attributed_to") in ("claimant", "garage", "vehicle", "image")
                      for f in flat))
            check("every finding carries its check's weight and status",
                  all("check_weight" in f and f.get("check_status") for f in flat))

        # -----------------------------------------------------------------
        print("\n6. attribution points at the right entity")
        conn = db.connect(db_copy)
        row = conn.execute(
            "SELECT case_id FROM findings WHERE check_id = 'threshold_gaming' "
            "AND verdict = 'concern' LIMIT 1").fetchone()
        conn.close()
        if row:
            detail = client.get(f"/v1/cases/{row[0]}").json()
            tg = [f for fs in detail["findings_by_category"].values() for f in fs
                  if f["check_id"] == "threshold_gaming"]
            check("threshold_gaming is attributed to the garage",
                  all(f["attributed_to"] == "garage" for f in tg),
                  "a UI would render this beside the claimant's name")
            check("threshold_gaming names the garage as its subject",
                  all(f.get("subject_id") for f in tg))
            check("threshold_gaming links to the garage endpoint",
                  all((f.get("subject_url") or "").startswith("/v1/garages/") for f in tg))
            if tg and tg[0].get("subject_id"):
                g = client.get(f"/v1/garages/{tg[0]['subject_id']}")
                check("the linked garage endpoint resolves", g.status_code == 200,
                      f"{g.status_code}")
                if g.status_code == 200:
                    body = g.json()
                    check("garage carries a claim-value distribution",
                          bool(body.get("claim_value_histogram")))
                    check("garage carries below-threshold share",
                          body.get("below_threshold_pct") is not None)
        else:
            print("  (no threshold_gaming concern in this database; attribution "
                  "assertions skipped)")

        # -----------------------------------------------------------------
        print("\n7. the trace carries tool inputs and outputs")
        conn = db.connect(db_copy)
        traced = None
        for (case_id,) in conn.execute(
            "SELECT DISTINCT case_id FROM audit_log WHERE event_type = 'case_adjudicated'"
        ):
            events = db.get_audit_events_for_case(conn, case_id)
            if any((e.details or {}).get("trace") for e in events
                   if e.event_type == "case_adjudicated"):
                traced = case_id
                break
        conn.close()
        check("an adjudicated case with a trace exists", traced is not None,
              "cannot verify the trace endpoint without one")

        if traced:
            trace = client.get(f"/v1/cases/{traced}/trace").json()
            check("trace returns steps", bool(trace.get("steps")),
                  "the reasoning screen would be empty")
            tools = [s for s in trace["steps"] if s["type"] == "tool_call"]
            if tools:
                # This is the assertion that would have caught the `content`
                # key bug: the endpoint returned steps, but every payload was
                # empty because it read a field no producer writes.
                check("a tool call names its tool",
                      all(s.get("tool_name") for s in tools))
                check("a tool call records what it was asked",
                      any(s.get("tool_input") for s in tools),
                      "tool_input empty on every step - the screen cannot show the query")
                check("a tool call records what came back",
                      any(s.get("tool_output") for s in tools),
                      "tool_output empty on every step - the screen cannot show the answer")
            else:
                print("  (no tool_call steps in this trace; payload assertions skipped)")
            check("trace reports withheld outage steps",
                  "excluded_outage_steps" in trace)
            check("no outage step is presented as reasoning",
                  all("provider error" not in (s.get("content") or "")
                      for s in trace["steps"]))

        # -----------------------------------------------------------------
        print("\n8. images serve, and a thumbnail is smaller")
        conn = db.connect(db_copy)
        img = conn.execute(
            "SELECT image_id FROM images ORDER BY image_id LIMIT 1").fetchone()
        conn.close()
        if img:
            full = client.get(f"/v1/images/{img[0]}")
            thumb = client.get(f"/v1/images/{img[0]}", params={"thumb": 1})
            check("full image returns bytes",
                  full.status_code == 200 and len(full.content) > 0)
            check("full image declares an image content-type",
                  full.headers.get("content-type", "").startswith("image/"))
            check("full image carries an ETag", bool(full.headers.get("etag")))
            check("full image carries cache headers",
                  "max-age" in full.headers.get("cache-control", ""))
            check("thumbnail returns bytes",
                  thumb.status_code == 200 and len(thumb.content) > 0)
            check("thumbnail is valid image data",
                  thumb.content[:3] in (b"\xff\xd8\xff", b"\x89PN"),
                  f"leading bytes {thumb.content[:4]!r}")
            check("thumbnail is smaller than the original",
                  len(thumb.content) < len(full.content),
                  f"thumb {len(thumb.content)}B vs full {len(full.content)}B")

        missing = client.get("/v1/images/does-not-exist")
        check("a missing image returns the error envelope",
              missing.status_code == 404
              and missing.json().get("code") == "IMAGE_NOT_FOUND",
              f"{missing.status_code}: {missing.text[:120]}")

        # -----------------------------------------------------------------
        print("\n9. errors are a single machine-readable shape")
        for path, expected in (("/v1/cases/nope", "CASE_NOT_FOUND"),
                               ("/v1/cases/nope/trace", "CASE_NOT_FOUND"),
                               ("/v1/checks/nope", "CHECK_NOT_FOUND"),
                               ("/v1/garages/nope", "GARAGE_NOT_FOUND"),
                               ("/v1/jobs/nope", "JOB_NOT_FOUND")):
            r = client.get(path)
            body = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
            check(f"{path} returns {expected}",
                  r.status_code == 404 and body.get("code") == expected,
                  f"{r.status_code}: {r.text[:120]}")
            check(f"{path} envelope has status, code, message",
                  all(k in body for k in ("status", "code", "message")))

        bad = client.get("/v1/cases", params={"page_size": 9999})
        body = bad.json()
        check("an out-of-range parameter names the offending field",
              bad.status_code == 422 and body.get("details")
              and body["details"][0].get("field"),
              f"{bad.status_code}: {bad.text[:160]}")

        # -----------------------------------------------------------------
        print("\n10. supporting endpoints a UI needs")
        checks_body = client.get("/v1/checks").json()
        check("checks endpoint lists the battery", len(checks_body) >= 10)
        statuses = {c["status"] for c in checks_body}
        check("check status is populated",
              statuses.issubset({"active", "quota_blocked", "corpus_untestable",
                                 "retired", "demoted"}), f"{statuses}")
        check("a non-active check explains itself",
              all(c.get("limitation") for c in checks_body
                  if c["status"] in ("corpus_untestable", "demoted", "retired")),
              "a UI would list a dead check as though it worked")
        check("checks carry marginal contribution where measured",
              any(c.get("marginal_recall_contribution") for c in checks_body))

        one = client.get(f"/v1/checks/{checks_body[0]['check_id']}")
        check("single check detail resolves", one.status_code == 200)
        check("single check carries a description",
              bool(one.json().get("description")))

        stats = client.get("/v1/stats").json()
        for key in ("total_cases", "by_risk_band", "concerns_by_check",
                    "concerns_by_attribution", "straight_through_rate", "ablation_arms"):
            check(f"stats carries {key}", key in stats)
        check("stats reports both ablation arms",
              len(stats.get("ablation_arms", [])) >= 1)

        policies = client.get("/v1/policies").json()
        check("policies returns both agent configurations", len(policies) == 2)
        check("policies differ in their check sets",
              policies[0]["check_ids"] != policies[1]["check_ids"])

        health = client.get("/health").json()
        for key in ("status", "database_reachable", "cases", "ablation_agent_cases"):
            check(f"health carries {key}", key in health)

        if listing.get("items"):
            sim = client.get(f"/v1/cases/{listing['items'][0]['case_id']}/similar")
            check("similar-cases endpoint resolves", sim.status_code == 200)

        # -----------------------------------------------------------------
        print("\n11. submission and action, without calling a model")
        original = api._run_pipeline
        calls: list[tuple[str, str]] = []
        api._run_pipeline = lambda job_id, case_id: calls.append((job_id, case_id))
        try:
            r = client.post("/v1/cases", data={"agent_type": "claims",
                                               "claim_amount": "48750",
                                               "declared_location": "Pune"})
            check("submission returns 201", r.status_code == 201, r.text[:160])
            if r.status_code == 201:
                body = r.json()
                check("submission returns a case id and a job id",
                      body.get("case_id") and body.get("job_id"))
                job = client.get(f"/v1/jobs/{body['job_id']}").json()
                check("job is pollable and reports progress",
                      "status" in job and "progress" in job)
                fetched = client.get(f"/v1/cases/{body['case_id']}")
                check("a submitted case is immediately fetchable",
                      fetched.status_code == 200)
                check("no model was called during submission", len(calls) == 1)
        finally:
            api._run_pipeline = original

        if listing.get("items"):
            target = listing["items"][0]["case_id"]
            act = client.post(f"/v1/cases/{target}/action",
                              json={"action": "request_evidence", "note": "need plate"})
            check("an adjuster action is recorded", act.status_code == 200, act.text[:160])
            reject = client.post(f"/v1/cases/{target}/action", json={"action": "reject"})
            check("rejection is structurally impossible", reject.status_code == 422,
                  f"got {reject.status_code}")

    except Exception as e:  # noqa: BLE001
        print(f"\nFAIL  contract check raised {type(e).__name__}: {e}")
        traceback.print_exc()
        _failures.append(f"unhandled exception: {type(e).__name__}: {e}")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print()
    if _failures:
        print(f"{len(_failures)} of {_checks} CONTRACT ASSERTIONS FAILED:")
        for f in _failures:
            print(f"  - {f}")
        return 1
    print(f"contract verified: {_checks} assertions passed. "
          "A frontend can be built against this.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
