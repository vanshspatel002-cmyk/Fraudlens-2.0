"""
Drive the ablation's agent arm to completion across quota days.

The agent arm needs ~2.4 LLM calls per case over 99 cases against a free
tier of ~100 requests/day, so it cannot finish in one sitting. Rather than
requiring a human to re-run it each morning, this loops: try to make
progress, and when the tier is spent, sleep and try again.

It adds nothing to the experiment - run_ablation.py already resumes from its
JSONL and already refuses to record a case the provider never answered. This
is purely the thing that keeps calling it.

Quota resets at midnight Pacific, not local midnight, so the wait is
probe-based rather than clock-based: guessing the offset is how the last
attempt wasted an hour.

Usage:
    python scripts/drive_ablation.py
    python scripts/drive_ablation.py --max-hours 48
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]

from src import db

RESULTS = Path("outputs/ablation_results.jsonl")
SAMPLE = Path("outputs/ablation_sample.json")
PROBE_INTERVAL = 900  # 15 min; the reset is a wall-clock edge, not a trickle
VALIDATE_EVERY = 10


@dataclass
class IntegrityResult:
    verified: int
    total: int
    problems: list[dict[str, Any]]


def _agent_rows() -> list[dict[str, Any]]:
    if not RESULTS.exists():
        return []
    out: list[dict[str, Any]] = []
    for line_no, line in enumerate(RESULTS.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if row.get("arm") == "agent":
            row["_line"] = line_no
            out.append(row)
    return out


def _fallback_trace(trace_steps: list[dict[str, Any]]) -> bool:
    return any((step.get("kind") or "").lower() == "fallback" for step in trace_steps)


def _latest_agent_event(conn, case_id: str) -> dict[str, Any] | None:
    rows = conn.execute(
        "SELECT details FROM audit_log WHERE case_id = ? AND event_type = ? ORDER BY created_at DESC",
        (case_id, "case_adjudicated"),
    ).fetchall()
    for row in rows:
        try:
            details = json.loads(row["details"])
        except json.JSONDecodeError:
            continue
        if details.get("arm") == "agent":
            return details
    return None


def verify_agent_integrity(db_path: str = "fraudlens.db") -> IntegrityResult:
    """
    Validate the agent arm's trusted prefix.

    The driver is allowed to report only the prefix that has already passed
    these checks: a real LLM call, a real trace in JSONL, no fallback, and a
    matching persisted decision/audit event. If a future record is bad, the
    reported progress stops at the previous row instead of advancing over it.
    """
    rows = _agent_rows()
    problems: list[dict[str, Any]] = []
    verified = 0

    conn = db.connect(db_path)
    db.init_db(conn)
    try:
        for row in rows:
            row_problems: list[str] = []
            case_id = row.get("case_id")
            trace = row.get("trace") or []
            llm_calls = int(row.get("llm_calls") or 0)

            if not case_id:
                row_problems.append("missing_case_id")
            if llm_calls <= 0:
                row_problems.append("no_completed_llm_call")
            if not trace:
                row_problems.append("jsonl_trace_empty")
            elif _fallback_trace(trace):
                row_problems.append("jsonl_fallback_trace")

            decision = None
            if case_id:
                decision = conn.execute(
                    "SELECT * FROM agent_decisions WHERE case_id = ? "
                    "AND policy_version LIKE 'agent-%' ORDER BY created_at DESC LIMIT 1",
                    (case_id,),
                ).fetchone()
            if decision is None:
                row_problems.append("missing_db_decision")
            else:
                expected = {
                    "risk_band": row.get("risk_band"),
                    "tool_calls_count": int(row.get("tool_calls") or 0),
                    "iterations_count": int(row.get("iterations") or 0),
                    "llm_calls_count": llm_calls,
                }
                for column, value in expected.items():
                    if decision[column] != value:
                        row_problems.append(f"db_{column}_mismatch")

            event = _latest_agent_event(conn, case_id) if case_id else None
            if event is None:
                row_problems.append("missing_audit_trace")
            else:
                event_trace = event.get("trace") or []
                if not event_trace:
                    row_problems.append("audit_trace_empty")
                elif _fallback_trace(event_trace):
                    row_problems.append("audit_fallback_trace")
                if int(event.get("llm_calls") or 0) != llm_calls:
                    row_problems.append("audit_llm_calls_mismatch")
                if event.get("risk_band") != row.get("risk_band"):
                    row_problems.append("audit_risk_band_mismatch")

            if row_problems:
                problems.append({
                    "case_id": case_id,
                    "line": row.get("_line"),
                    "verified_prefix": verified,
                    "problems": row_problems,
                })
                break
            verified += 1
    finally:
        conn.close()

    return IntegrityResult(verified=verified, total=len(rows), problems=problems)


def agent_done() -> int:
    return verify_agent_integrity().verified


def total_cases() -> int:
    if not SAMPLE.exists():
        return 0
    return len(json.loads(SAMPLE.read_text(encoding="utf-8"))["cases"])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--max-hours", type=float, default=48.0)
    parser.add_argument("--db-path", default="fraudlens.db")
    args = parser.parse_args()

    target = total_cases()
    started = time.monotonic()
    attempt = 0

    while time.monotonic() - started < args.max_hours * 3600:
        attempt += 1
        integrity = verify_agent_integrity(args.db_path)
        if integrity.problems:
            print(f"[drive] integrity failure at agent row {integrity.verified + 1}; "
                  f"verified prefix is {integrity.verified}/{target}", flush=True)
            print(json.dumps(integrity.problems[0], indent=2), flush=True)
            break
        before = integrity.verified
        if target and before >= target:
            print(f"[drive] agent arm complete: {before}/{target}")
            break

        print(f"[drive] attempt {attempt}: {before}/{target} done; running agent arm",
              flush=True)
        subprocess.call([
            sys.executable, "-u", "scripts/run_ablation.py",
            "--arm", "agent", "--db-path", args.db_path,
        ])

        integrity = verify_agent_integrity(args.db_path)
        after = integrity.verified
        if integrity.problems:
            print(f"[drive] integrity failure after attempt {attempt}; "
                  f"refusing to report past {after}/{target}", flush=True)
            print(json.dumps(integrity.problems[0], indent=2), flush=True)
            break
        gained = after - before
        print(f"[drive] attempt {attempt} added {gained} case(s) ({after}/{target})",
              flush=True)
        if after // VALIDATE_EVERY != before // VALIDATE_EVERY or (target and after >= target):
            print(f"[drive] integrity check passed for {after}/{target} agent case(s)",
                  flush=True)

        if target and after >= target:
            print("[drive] agent arm complete")
            break

        # No progress means the tier is spent - or something is wrong that
        # retrying immediately will not fix. Either way, wait.
        if gained == 0:
            print(f"[drive] no progress; sleeping {PROBE_INTERVAL // 60} min", flush=True)
            time.sleep(PROBE_INTERVAL)

    # Always leave a current report behind, however far it got.
    subprocess.call([
        sys.executable, "-u", "scripts/run_ablation.py",
        "--report-only", "--db-path", args.db_path,
    ])
    final_integrity = verify_agent_integrity(args.db_path)
    final = final_integrity.verified
    if final_integrity.problems:
        print(f"[drive] finished with verified prefix {final}/{target}; "
              "latest row failed integrity")
    else:
        print(f"[drive] finished with verified {final}/{target} agent case(s)")
    return 0 if (target and final >= target) else 1


if __name__ == "__main__":
    raise SystemExit(main())
