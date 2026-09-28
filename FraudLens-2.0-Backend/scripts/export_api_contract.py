"""
Export the API contract for the UI design step.

Two artefacts, and both are handed to someone who cannot run this code:

  outputs/openapi.json   the machine contract, for client generation
  outputs/api_reference.md  the human one, with a REAL example response per
                            endpoint drawn from live data

The examples matter more than they look. A schema says a field is
`Optional[str]`; an example says whether it is populated in practice, what a
risk band actually reads like, and whether `attributed_to` says "garage" on
the finding a designer is about to put beside a claimant's name. Completeness
beats brevity here, because the reader cannot check anything themselves.

Runs against a copy of the database and makes no LLM calls.

Usage:
    python scripts/export_api_contract.py
"""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any, Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]

from fastapi.testclient import TestClient

OPENAPI_OUT = Path("outputs/openapi.json")
REFERENCE_OUT = Path("outputs/api_reference.md")
MAX_EXAMPLE_CHARS = 2600


def truncate(payload: Any, limit: int = MAX_EXAMPLE_CHARS) -> str:
    text = json.dumps(payload, indent=2, default=str, ensure_ascii=False)
    if len(text) <= limit:
        return text
    return text[:limit] + "\n  … truncated for length; the full shape is in openapi.json"


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="fraudlens_export_"))
    db_copy = tmp / "export.db"
    shutil.copy("fraudlens.db", db_copy)

    try:
        from src import api, db
        api.DB_PATH = str(db_copy)
        client = TestClient(api.app)

        spec = client.get("/openapi.json").json()
        OPENAPI_OUT.parent.mkdir(parents=True, exist_ok=True)
        OPENAPI_OUT.write_text(json.dumps(spec, indent=2), encoding="utf-8")

        # Real identifiers, so every example is drawn from live data rather
        # than invented.
        conn = db.connect(db_copy)
        case_row = conn.execute(
            "SELECT case_id FROM findings WHERE verdict = 'concern' LIMIT 1").fetchone()
        example_case = case_row[0] if case_row else None
        if example_case is None:
            row = conn.execute("SELECT case_id FROM cases LIMIT 1").fetchone()
            example_case = row[0] if row else "case-0001"
        img_row = conn.execute("SELECT image_id FROM images LIMIT 1").fetchone()
        example_image = img_row[0] if img_row else None
        gar_row = conn.execute(
            "SELECT garage_id FROM cases WHERE garage_id IS NOT NULL "
            "AND garage_id != 'UNASSIGNED' LIMIT 1").fetchone()
        example_garage = gar_row[0] if gar_row else None
        traced = None
        for (cid,) in conn.execute(
            "SELECT DISTINCT case_id FROM audit_log WHERE event_type='case_adjudicated'"
        ):
            events = db.get_audit_events_for_case(conn, cid)
            if any((e.details or {}).get("trace") for e in events):
                traced = cid
                break
        conn.close()

        # (method, path, description, live call)
        endpoints: list[tuple[str, str, str, Optional[tuple[str, dict]]]] = [
            ("GET", "/v1/cases",
             "The case queue. Every row carries what a table renders, so listing a "
             "page costs one request.",
             ("/v1/cases", {"page_size": 2})),
            ("GET", "/v1/cases/{case_id}",
             "One case, complete: declaration, images, findings grouped by the five "
             "categories, decision, and concern counts by category and by attribution.",
             (f"/v1/cases/{example_case}", {})),
            ("GET", "/v1/cases/{case_id}/trace",
             "The agent's ordered reasoning. Tool steps carry the tool name, what it "
             "was asked and what came back. Provider-outage steps are withheld.",
             (f"/v1/cases/{traced or example_case}/trace", {})),
            ("GET", "/v1/cases/{case_id}/report",
             "A structured report for on-screen rendering and later PDF export: "
             "declaration, findings grouped by category, agent recommendation and "
             "narrative, and the latest human admin action where one exists.",
             (f"/v1/cases/{example_case}/report", {})),
            ("GET", "/v1/cases/{case_id}/similar",
             "Cases sharing an image, claimant, garage or registration, with what is "
             "shared.",
             (f"/v1/cases/{example_case}/similar", {})),
            ("GET", "/v1/track",
             "Public narrow tracking endpoint. Verifies case id plus registration or "
             "policy number, then returns only status, final admin action and narrative.",
             None),
            ("GET", "/v1/images/{image_id}",
             "The image bytes, with ETag and cache headers. `?thumb=1` returns a "
             "400px-wide version generated on first request and cached to disk - the "
             "queue asks for dozens at once.",
             None),
            ("POST", "/v1/cases",
             "Submit a declaration plus image files as multipart form data. Returns "
             "immediately with a job id; checks and adjudication run in the "
             "background.",
             None),
            ("POST", "/v1/cases/{case_id}/reprocess",
             "Re-run checks and adjudication for an existing case.", None),
            ("POST", "/v1/cases/{case_id}/action",
             "Record a human admin action: approve, reject with a reason, or request "
             "more evidence. This enum is separate from the agent Recommendation enum, "
             "which still has no reject member.",
             None),
            ("GET", "/v1/jobs/{job_id}",
             "Poll a background job: status, progress, resulting case id, and whether "
             "the provider was unavailable.",
             None),
            ("GET", "/v1/checks",
             "The check battery with each check's measured recall, false-positive "
             "rate, marginal contribution, status and - where it is not contributing - "
             "one sentence saying why.",
             ("/v1/checks", {})),
            ("GET", "/v1/checks/{check_id}",
             "One check in full, including its own description and the artefacts "
             "recording how it was measured.",
             ("/v1/checks/threshold_gaming", {})),
            ("GET", "/v1/garages/{garage_id}",
             "A garage's claim-value distribution and sub-threshold share. Exists "
             "because threshold_gaming is garage-scoped: the finding describes the "
             "repairer, and a UI needs somewhere to show that.",
             (f"/v1/garages/{example_garage}", {}) if example_garage else None),
            ("GET", "/v1/stats",
             "Dashboard aggregates, including concerns by attribution and both "
             "ablation arms side by side.",
             ("/v1/stats", {})),
            ("GET", "/v1/policies",
             "Both agent configurations: check sets, tools, caps, bias and full "
             "system prompt.",
             None),
            ("GET", "/health",
             "Database connectivity, provider configuration and ablation progress.",
             ("/health", {})),
        ]

        a_: list[str] = []
        a = a_.append
        a("# FraudLens API reference")
        a("")
        a("Generated by `scripts/export_api_contract.py` from a live database. The "
          "machine contract is `outputs/openapi.json`; this document exists so a "
          "designer can see what the responses actually contain.")
        a("")
        a(f"**{len(spec.get('paths', {}))} endpoints.** Base URL in development: "
          "`http://localhost:8000`. CORS is open to all origins, so a frontend on "
          "another port works without configuration.")
        a("")

        a("## Conventions")
        a("")
        a("**Errors** all share one shape, so a client can branch on `code` without "
          "reading prose:")
        a("")
        a("```json")
        a(json.dumps({"status": 404, "code": "CASE_NOT_FOUND",
                      "message": "No case with id 'case-9999'.",
                      "details": []}, indent=2))
        a("```")
        a("")
        a("Codes in use: `CASE_NOT_FOUND`, `IMAGE_NOT_FOUND`, `IMAGE_FILE_MISSING`, "
          "`CHECK_NOT_FOUND`, `GARAGE_NOT_FOUND`, `JOB_NOT_FOUND`, "
          "`VALIDATION_FAILED`, `INVALID_SORT_FIELD`, `INVALID_SORT_DIRECTION`, "
          "`INTERNAL_ERROR`.")
        a("")
        a("**Finding attribution.** Every finding carries `attributed_to` — one of "
          "`claimant`, `garage`, `vehicle`, `image` — plus `subject_id` and, where an "
          "endpoint exists, `subject_url`. This is not cosmetic: `threshold_gaming` "
          "raises 91 of the corpus's clean-case concerns and all 91 were measured to "
          "describe the repairing garage's billing pattern rather than the claimant's "
          "conduct. **Render a garage-attributed finding beside the garage, not the "
          "claimant.**")
        a("")
        a("**Check status.** Findings also carry `check_status` and `check_limitation`. "
          "Seven of the checks currently fire on nothing, and a UI presenting every "
          "concern as equally trustworthy would overstate the system. Use "
          "`check_weight` and `check_status` to shade reliability inline.")
        a("")
        a("**Risk bands** are `clear`, `request_evidence`, `desk_review`, "
          "`escalate_siu`. **Agent recommendations** are `approve`, "
          "`request_evidence`, `escalate` and still cannot reject. **Human admin "
          "actions** are separate: `approve`, `reject`, `request_more_evidence`.")
        a("")
        a("---")
        a("")

        a("## Endpoints")
        a("")
        for method, path, description, call in endpoints:
            a(f"### `{method} {path}`")
            a("")
            a(description)
            a("")
            operation = (spec.get("paths", {}).get(path, {}) or {}).get(method.lower(), {})
            params = operation.get("parameters", [])
            if params:
                a("**Parameters**")
                a("")
                a("| Name | In | Type | Required | Description |")
                a("|---|---|---|---|---|")
                for p in params:
                    schema = p.get("schema", {})
                    kind = schema.get("type") or "|".join(
                        s.get("type", "?") for s in schema.get("anyOf", [])) or "string"
                    a(f"| `{p['name']}` | {p.get('in')} | {kind} | "
                      f"{'yes' if p.get('required') else 'no'} | "
                      f"{(p.get('description') or '').replace('|', '\\|')} |")
                a("")
            if operation.get("requestBody"):
                content = list(operation["requestBody"].get("content", {}))
                a(f"**Request body**: `{', '.join(content)}`")
                a("")

            if call is not None:
                url, query = call
                try:
                    response = client.get(url, params=query)
                    a(f"**Example response** (`{url}`):")
                    a("")
                    a("```json")
                    a(truncate(response.json()))
                    a("```")
                except Exception as e:  # noqa: BLE001
                    a(f"_Example unavailable: {type(e).__name__}_")
                a("")
            elif method == "GET" and path == "/v1/images/{image_id}":
                a("**Returns** raw image bytes with `Content-Type: image/jpeg` (or the "
                  "original type), an `ETag`, and `Cache-Control: public, max-age=86400`. "
                  "404 returns the JSON error envelope, never a raw exception.")
                a("")
                if example_image:
                    a(f"Example: `GET /v1/images/{example_image}?thumb=1`")
                    a("")
            else:
                a("_Mutating endpoint; no example is issued against the live database "
                  "by this exporter._")
                a("")
            a("---")
            a("")

        a("## Schemas")
        a("")
        a("Full definitions are in `openapi.json`. The ones a UI touches most:")
        a("")
        for name in ("CaseSummary", "CaseDetail", "FindingOut", "FindingGroup",
                     "CaseReportOut", "TrackOut", "DecisionOut", "TraceStepOut",
                     "ImageOut", "CheckMeta",
                     "GarageSummary", "StatsOut", "ErrorResponse"):
            schema = spec.get("components", {}).get("schemas", {}).get(name)
            if not schema:
                continue
            a(f"### `{name}`")
            a("")
            props = schema.get("properties", {})
            required = set(schema.get("required", []))
            a("| Field | Type | Required | Description |")
            a("|---|---|---|---|")
            for field, meta in props.items():
                kind = meta.get("type") or "|".join(
                    s.get("type", "ref") for s in meta.get("anyOf", [])) or "object"
                a(f"| `{field}` | {kind} | {'yes' if field in required else 'no'} | "
                  f"{(meta.get('description') or '').replace('|', '\\|')} |")
            a("")

        REFERENCE_OUT.write_text("\n".join(a_) + "\n", encoding="utf-8")
        print(f"-> {OPENAPI_OUT} ({len(spec.get('paths', {}))} paths)")
        print(f"-> {REFERENCE_OUT} ({len(a_)} lines)")
        return 0
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
