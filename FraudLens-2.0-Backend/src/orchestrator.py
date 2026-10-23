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
import json
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
            "decision_id": decision.decision_id,
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
    run_id: Optional[str] = None,
    on_stage=None,
    check_config: Optional[dict[str, Any]] = None,
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
    check_options = {'config': {'cache_ocr': True, 'plate_ocr_observed_prefix': True, 'execution_states': True,
                              'skip_experimental_models':True}} if run_id and policy.policy_version.startswith('agent-production-') else {}
    if check_options:
        # New intake records this in a server-written audit, never applicant
        # narrative text. Legacy generated UTC tags are local wall-clock values.
        gate = next((e for e in db.get_audit_events_for_case(conn, case_id)
                     if e.event_type == 'vehicle_image_gate'), None)
        check_options['config']['scene_time_basis'] = (gate.details.get('declared_time_basis', 'unverified')
                                                     if gate else 'unverified')
        if gate and case.agent_type=='underwriting' and 'odometer' in gate.details.get('photo_slots',[]):
            hashes={score.get('content_hash') for score in gate.details.get('scores',[]) if score.get('slot')=='odometer'}
            check_options['config']['required_odometer_image_ids']=[image.image_id for image in db.get_images_for_case(conn,case_id) if image.content_hash in hashes]
            for batch in conn.execute('SELECT b.image_ids,r.artifacts FROM evidence_batches b JOIN evidence_requests r ON r.request_id=b.request_id WHERE b.case_id=?',(case_id,)):
                if any(any(term in str(label).lower() for term in ('odometer','mileage')) for label in json.loads(batch['artifacts'])):
                    check_options['config']['required_odometer_image_ids'].extend(json.loads(batch['image_ids']))
            check_options['config']['odometer_photo_required']=True
    if check_config:
        check_options.setdefault('config', {}).update(check_config)
    from src.timing import span
    def check_started(check_id, index, total):
        # Only optional observations/cache writes exist at this point. Release
        # them before another connection updates durable progress (SQLite too).
        conn.commit()
        on_stage('check: ' + check_id, 0.6 + 0.25 * index / max(1, total))
    if on_stage:
        check_options['on_check'] = check_started
    with span('pipeline.checks'):
        findings = run_checks(conn, case, check_ids=list(policy.check_ids), **check_options)
    if run_id and policy.policy_version.startswith('agent-production-'):
        from src.checks import REGISTRY
        from src.models import Verdict
        for finding in findings:
            if REGISTRY[finding.check_id].weight == 0:
                if finding.check_id == 'baseline_corruption':
                    finding.evidence={**finding.evidence,'experimental_explanation':finding.explanation,
                        'recorded_declaration_notes':case.declaration_notes}
                    if 'declared_condition' in finding.evidence:
                        finding.evidence['experimental_assumed_condition']=finding.evidence.pop('declared_condition')
                    finding.explanation='This experimental check assumes an undamaged declaration, which is not established by an underwriting application alone. Review the recorded applicant declaration.'
                finding.evidence = {**finding.evidence,
                    'experimental_verdict': finding.verdict.value,
                    'experimental_confidence': finding.confidence,
                    'production_limitation': 'Zero-weight experimental check; no production detection signal.'}
                finding.verdict = Verdict.INCONCLUSIVE
                finding.confidence = 0.0
                finding.explanation = 'Experimental zero-weight observation, inconclusive for production routing. ' + finding.explanation

    if run_id:
        conn.commit()  # release optional check-cache writes before the provider call
    trace: list[dict[str, Any]] = []
    response_sources = []
    if use_agent:
        if provider is None:
            provider = get_provider()
        adjudicator = provider
        if run_id and policy.policy_version.startswith('agent-production-'):
            class RecordedProvider:
                def chat(self, *args, **kwargs):
                    response = provider.chat(*args, **kwargs)
                    cached = getattr(response, 'cached', None)
                    response_sources.append({'source': 'request_cache' if cached is True else (
                        'fresh_provider' if cached is False else 'unrecorded'),
                        'model': getattr(response, 'model', 'unrecorded'),
                        'request_provenance': {key: (getattr(response, 'raw', None) or {}).get('request_provenance', {}).get(key)
                            for key in ('session_attempt', 'requested_model', 'serving_model', 'timestamp',
                                'provider_request_id','finish_reason','token_usage','http_status','latency_ms','started_at','source','schema','run_id','case_id')
                            if key in (getattr(response, 'raw', None) or {}).get('request_provenance', {})}})
                    return response
                def __getattr__(self, name):
                    return getattr(provider, name)
            adjudicator = RecordedProvider()
        if on_stage:
            on_stage('agent adjudication', 0.9)
        with span('pipeline.adjudication'):
            result = adjudicate(conn, case, findings, policy, adjudicator,
                check_config=check_options.get('config'), release_transactions=bool(run_id))
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

    from .assessment_explanation import explain_assessment
    explanation = explain_assessment(case, findings, decision, policy, converged=converged,
        trace=trace, run_id=run_id, use_agent=use_agent, check_config=check_options.get('config', {}))

    if persist:
        if run_id and db.is_postgres(conn):
            from . import runtime_store
            conn.execute('BEGIN')
            db.lock_case(conn, case_id)
            runtime_store.fence(conn, run_id)
        for finding in findings:
            db.insert_finding(conn, finding)
        db.insert_agent_decision(conn, decision)
        event = adjudication_event(case.case_id, 'agent' if use_agent else 'baseline',
                                   policy.policy_version, decision, converged, trace)
        event.details['assessment_explanation'] = explanation
        if run_id:
            event.details['run_id'] = run_id
            event.details['model_response_sources'] = response_sources
            conn.execute('INSERT INTO processing_results(run_id,case_id,decision_id,finding_ids,image_ids,policy_version,converged,created_at) VALUES (?,?,?,?,?,?,?,?)',
                (run_id, case_id, decision.decision_id,
                 __import__('json').dumps([f.finding_id for f in findings]),
                 __import__('json').dumps([i.image_id for i in db.get_images_for_case(conn, case_id)]),
                 policy.policy_version, int(converged), time.time()))
        db.log_audit_event(conn, event)
        conn.commit()

    # Ephemeral handoff to the existing durable job payload, with an immutable
    # copy in the adjudication audit above. No research model/schema change.
    decision._model_response_sources = response_sources
    decision._assessment_explanation = explanation
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
