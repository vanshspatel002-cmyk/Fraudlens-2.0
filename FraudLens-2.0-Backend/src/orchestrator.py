"""
fraudlens.orchestrator
========================

One case in, one persisted decision out - by either arm of the ablation.

This is the single entry point both arms share. It loads the case, runs
the checks, hands the findings to *either* the LLM agent or the rules-only
baseline, persists the decision, and writes an audit event. The `use_agent`
flag is the only thing that differs between the two arms, and it is
deliberately the only thing: if the arms diverged anywhere else - a
different check list, a different set of cases, a different denominator -
the comparison would measure that difference instead of the one under
test.

Resumability is not a convenience here. A full agent pass over 800 cases
is hundreds of LLM calls against a free tier capped at 20 requests per key
per day, so a pass will be interrupted far more often than it will finish.
process_all() therefore checks what has already been decided for this
policy version and skips it, writing incrementally so an interrupted run
loses at most the case in flight.
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
import time
from pathlib import Path
from typing import Any, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tqdm import tqdm

from src import baseline, db
from src.agent.engine import adjudicate
from src.agent.policy import AgentPolicy, policy_for
from src.checks import run_checks
from src.llm import LLMProvider, get_provider
from src.models import AgentDecision, AuditEvent, Case



def adjudication_event(
    case_id: str,
    arm: str,
    policy_version: Optional[str],
    decision: AgentDecision,
    converged: bool,
    trace: list[dict[str, Any]],
) -> AuditEvent:
    """
    The `case_adjudicated` audit event, built in exactly one place.

    Three callers were constructing this dict by hand - here, in
    scripts/run_ablation.py, and in test_api.py's fixture - and the fixture
    had drifted to a three-key subset of the nine the producers write. A test
    that invents its own shape agrees with itself rather than with reality,
    which is precisely how the API's mismatched trace field survived: the
    fixture used a `content` key that no producer emits, so the endpoint
    dropping every tool payload looked correct.

    Anything reading this event - the trace endpoint, the interface - should
    be tested against what this function returns, not against a hand-written
    approximation of it.
    """
    return AuditEvent(
        event_type="case_adjudicated",
        case_id=case_id,
        details={
            "arm": arm,
            "policy_version": policy_version,
            "risk_band": decision.risk_band.value if decision.risk_band else None,
            "converged": converged,
            "tool_calls": decision.tool_calls_count,
            "iterations": decision.iterations_count,
            "llm_calls": decision.llm_calls_count,
            "latency_ms": decision.latency_ms,
            "trace": trace,
        },
    )


def process_case(
    conn: sqlite3.Connection,
    case_id: str,
    policy: Optional[AgentPolicy] = None,
    provider: Optional[LLMProvider] = None,
    use_agent: bool = True,
    persist: bool = True,
) -> AgentDecision:
    """
    Run one case end to end and return its decision.

    The two arms receive *identical* findings - run_checks is called once,
    above the branch, precisely so the agent cannot be handed different
    evidence from the baseline.
    """
    case = db.get_case(conn, case_id)
    if case is None:
        raise ValueError(f"no such case: {case_id}")

    if policy is None:
        policy = policy_for(case.agent_type)

    started = time.monotonic()
    findings = run_checks(conn, case, check_ids=list(policy.check_ids))

    trace: list[dict[str, Any]] = []
    if use_agent:
        if provider is None:
            provider = get_provider()
        result = adjudicate(conn, case, findings, policy, provider)
        decision = result.decision
        trace = result.trace_dicts()
        converged = result.converged
    else:
        decision = baseline.decide(findings, case)
        # The baseline's own latency, recorded for the same reason the
        # agent's is: the ablation compares cost as well as outcome, and
        # "arithmetic is effectively free" should be a measured claim
        # rather than an assumed one.
        decision.latency_ms = int((time.monotonic() - started) * 1000)
        converged = True

    if persist:
        # Findings are persisted alongside the decision so a reviewer can
        # see what the adjudicator saw. Wrapped: a storage failure on the
        # audit trail must not lose the decision itself.
        try:
            for finding in findings:
                db.insert_finding(conn, finding)
        except sqlite3.IntegrityError:
            pass  # already stored by an earlier pass over this case
        db.insert_agent_decision(conn, decision)
        db.log_audit_event(conn, adjudication_event(
            case_id=case.case_id,
            arm="agent" if use_agent else "baseline",
            policy_version=policy.policy_version,
            decision=decision,
            converged=converged,
            trace=trace,
        ))
        conn.commit()

    return decision


def already_decided(conn: sqlite3.Connection, policy_version: str) -> set[str]:
    """Case ids that already have a decision under this policy version."""
    rows = conn.execute(
        "SELECT DISTINCT case_id FROM agent_decisions WHERE policy_version = ?",
        (policy_version,),
    ).fetchall()
    return {r[0] for r in rows}


def process_all(
    conn: sqlite3.Connection,
    provider: Optional[LLMProvider] = None,
    use_agent: bool = True,
    limit: Optional[int] = None,
    agent_type: Optional[str] = None,
    case_ids: Optional[list[str]] = None,
    resume: bool = True,
) -> dict[str, Any]:
    """
    Process many cases, resumably, committing after each one.

    Stops early and reports rather than thrashing when the provider runs
    dry: on a free tier a pass will hit its daily quota long before it
    finishes, and grinding through 600 more cases to produce 600 identical
    fallbacks would burn hours and pollute the results with decisions that
    describe an outage rather than a case.
    """
    cases = db.get_all_cases(conn)
    if agent_type:
        cases = [c for c in cases if c.agent_type == agent_type]
    if case_ids:
        wanted = set(case_ids)
        cases = [c for c in cases if c.case_id in wanted]

    if resume:
        versions = {policy_for(c.agent_type).policy_version for c in cases} if use_agent else {baseline.POLICY_VERSION}
        done: set[str] = set()
        for version in versions:
            done |= already_decided(conn, version)
        skipped = len([c for c in cases if c.case_id in done])
        cases = [c for c in cases if c.case_id not in done]
        if skipped:
            print(f"  resuming: {skipped} case(s) already decided")

    if limit:
        cases = cases[:limit]

    stats = {"processed": 0, "failed": 0, "not_converged": 0, "bands": {}, "stopped_early": False}
    consecutive_failures = 0

    for case in tqdm(cases, desc="agent" if use_agent else "baseline", unit="case"):
        policy = policy_for(case.agent_type)
        try:
            decision = process_case(conn, case.case_id, policy, provider, use_agent=use_agent)
        except Exception as e:  # noqa: BLE001 - one bad case must not end the pass
            stats["failed"] += 1
            consecutive_failures += 1
            print(f"\n[orchestrator] {case.case_id} failed: {type(e).__name__}: {e}", file=sys.stderr)
            if consecutive_failures >= 3:
                print("[orchestrator] three consecutive failures - stopping early rather than "
                      "burning the rest of the pass; re-run to resume.", file=sys.stderr)
                stats["stopped_early"] = True
                break
            continue

        consecutive_failures = 0
        stats["processed"] += 1
        band = decision.risk_band.value if decision.risk_band else "unknown"
        stats["bands"][band] = stats["bands"].get(band, 0) + 1
        if "did not converge" in decision.summary:
            stats["not_converged"] += 1

    return stats


def parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Adjudicate cases with the agent or the rules-only baseline.")
    p.add_argument("--baseline", action="store_true", help="use the rules-only scorer instead of the agent")
    p.add_argument("--limit", type=int, default=None)
    p.add_argument("--agent-type", choices=["claims", "underwriting"], default=None)
    p.add_argument("--case", action="append", dest="cases", help="specific case id (repeatable)")
    p.add_argument("--no-resume", action="store_true")
    p.add_argument("--db-path", default="fraudlens.db")
    return p.parse_args(argv)


def main(argv: Optional[list[str]] = None) -> None:
    args = parse_args(argv)
    conn = db.connect(args.db_path)
    db.init_db(conn)
    try:
        stats = process_all(
            conn,
            provider=None if args.baseline else get_provider(),
            use_agent=not args.baseline,
            limit=args.limit,
            agent_type=args.agent_type,
            case_ids=args.cases,
            resume=not args.no_resume,
        )
        print(f"\nprocessed {stats['processed']}, failed {stats['failed']}, "
              f"did not converge {stats['not_converged']}")
        print(f"bands: {stats['bands']}")
        if stats["stopped_early"]:
            print("stopped early - re-run to resume")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
