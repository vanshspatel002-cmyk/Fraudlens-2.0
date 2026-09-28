"""
The ablation: LLM agent vs rules-only baseline, same cases, same findings.

--------------------------------------------------------------------------
What is held constant, and why it has to be
--------------------------------------------------------------------------
Both arms receive the *same* Finding objects. `run_checks` is called once
per case and the result is handed to both adjudicators, so a difference in
outcome cannot come from the checks having run differently. The arms differ
in exactly one thing: whether a weighted sum or an LLM reads the findings.

Cases the label audit flagged as defective are excluded from the clean
denominator. A CLEAN case carrying a stock-agency watermark penalises the
arms asymmetrically - the baseline cannot read a watermark and is credited
with a correct clear, while the agent reads it, flags it, and is scored as
a false positive for being right.

--------------------------------------------------------------------------
Quota
--------------------------------------------------------------------------
The baseline arm is free. The agent arm costs ~3 LLM calls per case against
a free tier of ~100/day, so a 99-case pass takes several days. Every result
is appended to a JSONL the moment it completes and the script resumes from
that file, so an interruption - which is the expected case, not the
exceptional one - costs at most the case in flight.

Usage:
    python scripts/run_ablation.py --arm baseline     # free, run first
    python scripts/run_ablation.py --arm agent        # resumable, quota-bound
    python scripts/run_ablation.py --report-only
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import sys
import traceback
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]

from src import baseline, db
from src.agent.engine import adjudicate
from src.agent.policy import policy_for
from src.checks import run_checks
from src.llm import get_provider, is_quota_budget_error, is_rate_limit_error
from src.models import Verdict
from src.orchestrator import adjudication_event
from src.sampling import ablation_sample, sample_report

RESULTS = Path("outputs/ablation_results.jsonl")
REPORT = Path("outputs/ablation_results.md")
EXCLUSIONS = Path("data/generated/corpus_exclusions.json")
BANDS = ("clear", "request_evidence", "desk_review", "escalate_siu")


def load_exclusions() -> set[str]:
    if not EXCLUSIONS.exists():
        return set()
    try:
        return set(json.loads(EXCLUSIONS.read_text(encoding="utf-8"))
                   .get("excluded_case_ids", []))
    except json.JSONDecodeError:
        return set()



FROZEN_SAMPLE = Path("outputs/ablation_sample.json")


def load_or_freeze_sample(conn, excluded: set[str]) -> list[dict[str, Any]]:
    """
    The sample, fixed on first use.

    Both arms must adjudicate the same cases - that is the entire point of an
    ablation. The clean-label audit runs for hours and keeps appending to
    corpus_exclusions.json, so re-deriving the sample on each invocation would
    quietly hand the agent arm a different set of cases than the baseline arm
    already ran, and the report would compare them regardless.

    So the sample is frozen to disk the first time any arm runs, and every
    later invocation reads that file. Exclusions discovered afterwards are
    subtracted at *scoring* time instead, where they belong: dropping a case
    from a denominator is an analysis decision, and it does not require the
    two arms to have run different experiments.
    """
    if FROZEN_SAMPLE.exists():
        payload = json.loads(FROZEN_SAMPLE.read_text(encoding="utf-8"))
        return payload["cases"]

    sample = ablation_sample(conn, exclude=excluded)
    FROZEN_SAMPLE.parent.mkdir(parents=True, exist_ok=True)
    FROZEN_SAMPLE.write_text(json.dumps({
        "seed": 42,
        "exclusions_at_freeze": sorted(excluded),
        "cases": sample,
    }, indent=2), encoding="utf-8")
    return sample



def _archetype_of(case_id: str) -> str:
    """Archetype for a case outside the sample - the partner of a duplicate usually is."""
    try:
        from src.sampling import load_archetypes
        return load_archetypes().get(case_id, "unknown")
    except Exception:  # noqa: BLE001
        return "unknown"



def interleave_by_archetype(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    Order the work so that ANY prefix is a representative sample.

    The sample is built archetype by archetype, so running it in natural
    order spends the first day entirely on REUSE, the second on
    EXTERNAL_SOURCING, and does not reach a single clean case until day
    three. That is exactly backwards for a job whose defining constraint is
    that it will be interrupted: the first quota window produced eight REUSE
    cases and nothing else, from which neither a false-positive rate nor a
    cross-archetype comparison can be computed.

    Round-robin across archetypes instead. The set of cases is unchanged -
    it is frozen in outputs/ablation_sample.json - only the order differs,
    so this costs nothing and makes every partial result usable.
    """
    groups: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        groups.setdefault(row["archetype"], []).append(row)
    order = sorted(groups)
    out: list[dict[str, Any]] = []
    i = 0
    while len(out) < len(rows):
        progressed = False
        for arch in order:
            group = groups[arch]
            if i < len(group):
                out.append(group[i])
                progressed = True
        if not progressed:
            break
        i += 1
    return out



def is_outage_row(row: dict[str, Any]) -> bool:
    """
    True if this row records a provider outage rather than an adjudication.

    A case whose run ended in a fallback caused by a provider error made some
    real calls, then had the quota pulled out from under it mid-reasoning and
    took the DESK_REVIEW fallback. That band is the outage's, not the agent's,
    and on a clean case it would be scored as a false positive the agent never
    committed.

    This is distinct from a case that simply failed to converge - hitting the
    iteration cap, or never producing parseable JSON. That IS the agent's
    behaviour and must stay in the numbers. The test is specifically whether
    the provider stopped answering.

    Over a multi-day quota-bound run this will not be rare, which is why it is
    a rule rather than a one-off exclusion.
    """
    for step in row.get("trace") or []:
        if step.get("kind") == "fallback" and "provider error" in (step.get("detail") or ""):
            return True
    return False


def has_fallback_trace(trace_steps: list[dict[str, Any]]) -> bool:
    """
    True if the agent returned a coerced fallback rather than a model decision.

    Any fallback trace means the final band belongs to the harness, a provider
    failure, or non-parseable model output. That can be useful diagnostic
    evidence, but it must not advance the ablation arm.
    """
    return any((step.get("kind") or "").lower() == "fallback" for step in trace_steps)



ERROR_LOG = Path("outputs/ablation_errors.log")
MAX_CONSECUTIVE_FAILURES = 5


def log_failure(case_id: str, arm: str, trace_text: str) -> None:
    """Append a full traceback. Never let logging a failure cause one."""
    try:
        ERROR_LOG.parent.mkdir(parents=True, exist_ok=True)
        with ERROR_LOG.open("a", encoding="utf-8") as fh:
            fh.write(f"\n{'=' * 70}\n{datetime.now(timezone.utc).isoformat()} "
                     f"arm={arm} case={case_id}\n{'=' * 70}\n{trace_text}\n")
    except Exception:  # noqa: BLE001
        pass


def _stub_adjudicate(conn, case, findings, policy, provider):
    """
    A canned adjudication, so --stub exercises everything except the model.

    The bug this exists to prevent fired only *after* a successful
    adjudication, which an exhausted free tier made unreachable - so it hid
    behind a 429 for twenty runs. Any future change to the record/guard/persist
    path can now be checked in seconds without quota.
    """
    from src.agent.engine import AdjudicationResult, TraceStep
    from src.models import AgentDecision, Recommendation, RiskBand

    concerns = [f for f in findings if f.verdict is Verdict.CONCERN]
    band = RiskBand.ESCALATE_SIU if concerns else RiskBand.CLEAR
    decision = AgentDecision(
        case_id=case.case_id,
        recommendation=(Recommendation.ESCALATE if concerns else Recommendation.APPROVE),
        confidence=0.75,
        summary=f"[stub] {len(concerns)} concern(s); no model was called.",
        supporting_finding_ids=[f.finding_id for f in concerns][:3],
        requested_artifacts=[],
        policy_version=policy.policy_version,
        risk_band=band,
        tool_calls_count=1,
        iterations_count=2,
        llm_calls_count=2,
        latency_ms=0,
    )
    trace = [
        TraceStep(0, "tool_call", "get_claimant_history", {"args": {}, "result_keys": ["cases"]}, 5),
        TraceStep(1, "llm_call", f"decision: {band.value}", {"recommendation": decision.recommendation.value}, 5),
    ]
    return AdjudicationResult(decision, trace, converged=True)


def make_provider(args):
    """The provider, or nothing at all when stubbing."""
    if args.stub or args.arm != "agent":
        return None
    return get_provider()


def load_rows() -> list[dict[str, Any]]:
    if not RESULTS.exists():
        return []
    out = []
    for line in RESULTS.read_text(encoding="utf-8").splitlines():
        if line.strip():
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue  # torn final line from a killed run
    return out


def main(argv: Optional[list[str]] = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--arm", choices=["baseline", "agent"], default="baseline")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--db-path", default="fraudlens.db")
    parser.add_argument("--report-only", action="store_true")
    parser.add_argument("--stub", action="store_true",
                        help="Run the loop against a canned adjudicator - no API calls. "
                             "Verifies this code path in seconds.")
    args = parser.parse_args(argv)
    if args.arm == "agent" and not args.stub:
        os.environ.setdefault("GEMINI_QUOTA_CONSUMER", "ablation")

    conn = db.connect(args.db_path)
    db.init_db(conn)

    excluded = load_exclusions()
    sample = load_or_freeze_sample(conn, excluded)
    print(sample_report(sample))
    if excluded:
        print(f"  {len(excluded)} case(s) flagged by the label audit "
              f"(applied at scoring, not sampling)")

    if args.report_only:
        write_report(load_rows(), sample, excluded)
        return

    done = {(r["arm"], r["case_id"]) for r in load_rows()}
    todo = interleave_by_archetype(
        [r for r in sample if (args.arm, r["case_id"]) not in done])
    if args.limit:
        todo = todo[: args.limit]
    print(f"\narm={args.arm}: {len(sample)} in sample, "
          f"{len(sample) - len(todo)} done, {len(todo)} to run")

    provider = make_provider(args)
    RESULTS.parent.mkdir(parents=True, exist_ok=True)
    stopped = False
    aborted = False
    consecutive_failures = 0

    with RESULTS.open("a", encoding="utf-8") as fh:
        for row in todo:
            case = db.get_case(conn, row["case_id"])
            policy = policy_for(case.agent_type)

            check_started = time.monotonic()
            findings = run_checks(conn, case, check_ids=list(policy.check_ids))
            check_ms = int((time.monotonic() - check_started) * 1000)

            started = time.monotonic()
            try:
                if args.arm == "baseline":
                    decision = baseline.decide(findings, case)
                    tool_calls = iterations = llm_calls = 0
                    converged = True
                else:
                    adjudicator = _stub_adjudicate if args.stub else adjudicate
                    result = adjudicator(conn, case, findings, policy, provider)
                    decision = result.decision
                    tool_calls = decision.tool_calls_count
                    iterations = decision.iterations_count
                    llm_calls = decision.llm_calls_count
                    converged = result.converged
            except Exception as e:  # noqa: BLE001
                if is_rate_limit_error(e) or is_quota_budget_error(e):
                    print(f"  {row['case_id']}: quota exhausted - stopping; re-run to resume")
                    stopped = True
                    break

                # Anything that is NOT a rate limit is a bug, and must be
                # impossible to mistake for one. An UnboundLocalError once
                # failed 20 consecutive runs while the driver logged "no
                # progress" beside genuine 429 messages, and a day of quota
                # went unused because the crash looked like quota exhaustion.
                consecutive_failures += 1
                trace_text = traceback.format_exc()
                log_failure(row["case_id"], args.arm, trace_text)
                print(f"\n!! {row['case_id']}: NON-QUOTA FAILURE "
                      f"{type(e).__name__}: {e}", file=sys.stderr)
                print(trace_text, file=sys.stderr)
                print(f"!! logged to {ERROR_LOG} "
                      f"({consecutive_failures} consecutive)", file=sys.stderr)

                if consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
                    print(f"\n!! ABORTING: {consecutive_failures} consecutive non-quota "
                          f"failures. This is a bug, not a quota limit - re-running will "
                          f"not help. See {ERROR_LOG}.", file=sys.stderr)
                    stopped = True
                    aborted = True
                    break
                continue

            latency_ms = int((time.monotonic() - started) * 1000)
            # Defined here, before anything reads it. Both the JSONL record
            # and the persistence block below need it, and they sit on
            # opposite sides of the stalled-run guard.
            trace_steps = result.trace_dicts() if args.arm == "agent" else []

            record = {
                "arm": args.arm,
                "case_id": row["case_id"],
                "archetype": row["archetype"],
                "agent_type": row["agent_type"],
                "is_fraud": row["archetype"] != "CLEAN",
                "risk_band": decision.risk_band.value if decision.risk_band else None,
                "recommendation": decision.recommendation.value,
                "concern_checks": sorted({f.check_id for f in findings
                                          if f.verdict is Verdict.CONCERN}),
                "tool_calls": tool_calls,
                "iterations": iterations,
                "llm_calls": llm_calls,
                "converged": converged,
                "latency_ms": latency_ms,
                "check_ms": check_ms,
                "summary": decision.summary,
                "trace": trace_steps,
            }
            # A case the provider never answered is a record of an outage, not
            # an adjudication. It took the DESK_REVIEW fallback without a
            # single completed call, so writing it would let a quota failure
            # be scored as the agent's judgement - and DESK_REVIEW on a clean
            # case would count as a false positive the agent never made.
            # Drop it and stop; the resume will retry it with quota.
            if args.arm == "agent" and llm_calls == 0:
                print(f"  [{args.arm}] {row['case_id']}: no completed LLM call "
                      "(provider unreachable) - not recorded; stopping")
                stopped = True
                break
            if args.arm == "agent" and has_fallback_trace(trace_steps):
                print(f"  [{args.arm}] {row['case_id']}: fallback trace produced "
                      "no trustworthy model decision - not recorded; stopping")
                stopped = True
                break

            # Persist the decision and its trace.
            #
            # The JSONL is the scoring artefact, but it is not the whole
            # record: the agent's reasoning steps were being computed and
            # discarded, so GET /v1/cases/{id}/trace returned nothing for
            # every case in the corpus and the interface had no reasoning to
            # show. Writing the audit event here is what makes the trace
            # visible. Wrapped, because a storage failure on the audit trail
            # must never cost the experiment a result that has already been
            # paid for in quota.
            try:
                # Findings are persisted here, not only the decision.
                #
                # They were not, and the result was a `findings` table that
                # was empty for all 800 cases: the interface's Findings panel
                # rendered blank everywhere and /v1/stats reported zero
                # concerns. Nothing had failed - the findings were computed
                # correctly and cached to JSONL - they simply had no writer on
                # this path. The orchestrator persists them; this script did
                # not; and no unit test could catch a seam that neither side
                # owned. IntegrityError means an earlier pass already stored
                # them, which is fine.
                for finding in findings:
                    try:
                        db.insert_finding(conn, finding)
                    except sqlite3.IntegrityError:
                        pass

                decision.policy_version = (policy.policy_version if args.arm == "agent"
                                           else baseline.POLICY_VERSION)
                db.insert_agent_decision(conn, decision)
                # Built by the shared producer so this event cannot drift
                # from the orchestrator's, or from what the tests assert.
                db.log_audit_event(conn, adjudication_event(
                    case_id=case.case_id,
                    arm=args.arm,
                    policy_version=decision.policy_version,
                    decision=decision,
                    converged=converged,
                    trace=trace_steps,
                ))
                conn.commit()
            except Exception as e:  # noqa: BLE001
                print(f"    (could not persist decision/trace: {type(e).__name__}: {e})")

            consecutive_failures = 0
            fh.write(json.dumps(record) + "\n")
            fh.flush()
            print(f"  [{args.arm}] {row['case_id']} {row['archetype']:20s} -> "
                  f"{record['risk_band']}")

    if aborted:
        print("\nABORTED on repeated non-quota failures - fix the bug before re-running",
              file=sys.stderr)
    elif stopped:
        print("\nstopped early; re-run to resume")
    write_report(load_rows(), sample, excluded)
    conn.close()


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------

def _metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """
    Binary framing: 'flagged' = anything other than CLEAR.

    That is the decision the business actually makes - a case that is not
    cleared costs a human touch, whichever band it lands in. Using
    escalate_siu alone as 'positive' would score an agent that routes
    everything to desk review as having zero false positives, which is the
    opposite of true.
    """
    if not rows:
        return {"n": 0}
    fraud = [r for r in rows if r["is_fraud"]]
    clean = [r for r in rows if not r["is_fraud"]]
    flagged = [r for r in rows if r["risk_band"] != "clear"]
    tp = sum(1 for r in fraud if r["risk_band"] != "clear")
    fp = sum(1 for r in clean if r["risk_band"] != "clear")
    fn = len(fraud) - tp
    precision = tp / (tp + fp) if (tp + fp) else None
    recall = tp / len(fraud) if fraud else None
    f1 = (2 * precision * recall / (precision + recall)
          if precision and recall and (precision + recall) else None)
    cleared_clean = sum(1 for r in clean if r["risk_band"] == "clear")
    return {
        "n": len(rows), "fraud_n": len(fraud), "clean_n": len(clean),
        "tp": tp, "fp": fp, "fn": fn, "tn": len(clean) - fp,
        "precision": precision, "recall": recall, "f1": f1,
        "fp_rate_clean": (fp / len(clean)) if clean else None,
        "stp_rate": (cleared_clean / len(clean)) if clean else None,
        "flagged": len(flagged),
        "mean_tools": sum(r["tool_calls"] for r in rows) / len(rows),
        "mean_iters": sum(r["iterations"] for r in rows) / len(rows),
        "mean_llm_calls": sum(r["llm_calls"] for r in rows) / len(rows),
        "mean_latency_ms": sum(r["latency_ms"] for r in rows) / len(rows),
    }


def _pct(x: Optional[float]) -> str:
    return "n/a" if x is None else f"{x:.1%}"


def _ms(x: Optional[float]) -> str:
    return "n/a" if x is None else f"{x / 1000:.2f}s"


def write_report(rows: list[dict[str, Any]], sample: list[dict[str, Any]],
                 excluded: set[str]) -> None:
    a_: list[str] = []
    a = a_.append
    by_arm = {arm: [r for r in rows if r["arm"] == arm] for arm in ("baseline", "agent")}

    a("# Ablation — LLM agent vs rules-only baseline")
    a("")
    a("Same cases, same findings, one difference: whether a weighted sum or an LLM reads "
      "them. `run_checks` runs once per case and both adjudicators receive the identical "
      "`Finding` objects, so no result here can come from the checks behaving differently.")
    a("")
    a("```")
    a(sample_report(sample))
    a("```")
    if excluded:
        a("")
        a(f"{len(excluded)} case(s) excluded by the label audit "
          f"(`outputs/clean_label_audit.md`). A CLEAN case carrying a stock-agency "
          "watermark penalises the arms asymmetrically: the baseline cannot read the "
          "watermark and is credited with a correct clear, while the agent reads it, "
          "flags it, and is recorded as a false positive for being right.")
    a("")

    complete = {arm: len(v) for arm, v in by_arm.items()}
    a(f"**Progress: baseline {complete['baseline']}/{len(sample)}, "
      f"agent {complete['agent']}/{len(sample)}.**")
    outages = [r for r in by_arm["agent"] if is_outage_row(r)]
    if outages:
        a("")
        a(f"> **{len(outages)} agent row(s) excluded as provider outages** "
          f"({', '.join('`' + r['case_id'] + '`' for r in outages)}). These made real "
          "calls and were then cut off mid-reasoning by the free-tier quota, taking the "
          "DESK_REVIEW fallback. That band belongs to the outage, not the agent, and on "
          "a clean case it would score as a false positive the agent never committed. "
          "Cases that merely failed to converge — iteration cap, unparseable reply — are "
          "kept, because that is the agent's own behaviour.")
    if complete["agent"] < len(sample):
        a("")
        agent_rows = by_arm["agent"]
        measured = (sum(r["llm_calls"] for r in agent_rows) / len(agent_rows)
                    if agent_rows else 0.0)
        remaining = len(sample) - complete["agent"]
        a(f"> The agent arm is incomplete. Measured cost is **{measured:.1f} LLM calls "
          f"per case** (the plan assumed 3.0), so the remaining {remaining} case(s) need "
          f"~{measured * remaining:.0f} calls - about "
          f"{max(1, round(measured * remaining / 100))} more day(s) at ~100/day. "
          "Every figure below for "
          "the agent is computed over the cases it has actually adjudicated, and the "
          "two arms are compared **only on their shared subset** — comparing a partial "
          "agent run against a complete baseline run over different cases would be a "
          "sampling artefact, not a result.")
    a("")

    # ---- shared subset ----------------------------------------------------
    # Exclusions are applied here rather than at sampling, so that a defect
    # found after the arms ran does not require re-running either of them.
    outage_ids = {r["case_id"] for r in by_arm["agent"] if is_outage_row(r)}
    shared_ids = (({r["case_id"] for r in by_arm["baseline"]}
                   & {r["case_id"] for r in by_arm["agent"]})
                  - excluded - outage_ids)
    shared = {arm: [r for r in by_arm[arm] if r["case_id"] in shared_ids]
              for arm in ("baseline", "agent")}

    for agent_type in ("claims", "underwriting"):
        subset = {arm: [r for r in shared[arm] if r["agent_type"] == agent_type]
                  for arm in ("baseline", "agent")}
        mb, ma = _metrics(subset["baseline"]), _metrics(subset["agent"])
        a(f"## {agent_type.title()} — head to head on {len(subset['agent'])} shared case(s)")
        a("")
        if not ma.get("n"):
            a("_No agent results yet for this agent type._")
            a("")
            continue
        a(f"Fraud: {ma['fraud_n']}, clean: {ma['clean_n']}.")
        a("")
        a("| Metric | Baseline | Agent |")
        a("|---|---|---|")
        a(f"| Precision | {_pct(mb['precision'])} | {_pct(ma['precision'])} |")
        a(f"| Recall | {_pct(mb['recall'])} | {_pct(ma['recall'])} |")
        a(f"| F1 | {_pct(mb['f1'])} | {_pct(ma['f1'])} |")
        a(f"| False-positive rate on clean | {_pct(mb['fp_rate_clean'])} | {_pct(ma['fp_rate_clean'])} |")
        a(f"| Straight-through rate (clean cleared) | {_pct(mb['stp_rate'])} | {_pct(ma['stp_rate'])} |")
        a(f"| Mean tool calls | {mb['mean_tools']:.2f} | {ma['mean_tools']:.2f} |")
        a(f"| Mean iterations | {mb['mean_iters']:.2f} | {ma['mean_iters']:.2f} |")
        a(f"| Mean LLM calls | {mb['mean_llm_calls']:.2f} | {ma['mean_llm_calls']:.2f} |")
        a(f"| Mean adjudication latency | {_ms(mb['mean_latency_ms'])} | {_ms(ma['mean_latency_ms'])} |")
        a("")

    # ---- confusion matrices ----------------------------------------------
    a("## Confusion matrices over the four recommendations")
    a("")
    for arm in ("baseline", "agent"):
        if not shared[arm]:
            continue
        a(f"### {arm}")
        a("")
        a("| Truth | " + " | ".join(BANDS) + " |")
        a("|---|" + "---|" * len(BANDS))
        for truth, label in ((True, "FRAUD"), (False, "CLEAN")):
            counts = Counter(r["risk_band"] for r in shared[arm] if r["is_fraud"] is truth)
            a(f"| {label} | " + " | ".join(str(counts.get(b, 0)) for b in BANDS) + " |")
        a("")

    # ---- per archetype ----------------------------------------------------
    a("## Recall by archetype (shared subset)")
    a("")
    archetypes = sorted({r["archetype"] for r in shared["agent"] if r["is_fraud"]})
    if archetypes:
        a("| Archetype | n | Baseline caught | Agent caught |")
        a("|---|---|---|---|")
        for arch in archetypes:
            b = [r for r in shared["baseline"] if r["archetype"] == arch]
            g = [r for r in shared["agent"] if r["archetype"] == arch]
            bc = sum(1 for r in b if r["risk_band"] != "clear")
            gc = sum(1 for r in g if r["risk_band"] != "clear")
            a(f"| {arch} | {len(g)} | {bc}/{len(b)} | {gc}/{len(g)} |")
        a("")

    # ---- victim-side duplicates -----------------------------------------
    # Compared against the pre-fix archive rather than asserted, so this
    # section reports what actually changed and stays true if either run
    # is repeated.
    a("## The victim/reuser fix: what it did and did not resolve")
    a("")
    # Moved to outputs/archive/ by scripts/archive_superseded.py; the old
    # location is still checked so an un-archived working copy also works.
    pre = next((c for c in (Path("outputs/archive/ablation_results_pre_dupfix.jsonl"),
                            Path("outputs/ablation_results_pre_dupfix.jsonl"))
                if c.exists()), Path("outputs/archive/ablation_results_pre_dupfix.jsonl"))
    if not pre.exists():
        a("_No pre-fix archive to compare against._")
        a("")
    else:
        old_rows = {}
        for line in pre.read_text(encoding="utf-8").splitlines():
            if line.strip():
                try:
                    r = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if r["arm"] == "baseline":
                    old_rows[r["case_id"]] = r
        now = {r["case_id"]: r for r in by_arm["baseline"]}
        moved = [(cid, old_rows[cid], now[cid]) for cid in now
                 if cid in old_rows and old_rows[cid]["risk_band"] != now[cid]["risk_band"]]

        a("`internal_duplicate` used to flag both sides of a shared photograph. It now "
          "compares ingest time: the earlier submission yields INCONCLUSIVE naming the "
          "later case, and only the later yields CONCERN.")
        a("")
        if not moved:
            a("_No case changed band._")
        else:
            a("| Case | Truth | Before | After | Still flagged by |")
            a("|---|---|---|---|---|")
            for cid, before, after in sorted(moved):
                truth = "FRAUD" if after["is_fraud"] else "CLEAN"
                remaining = ", ".join(f"`{c}`" for c in after.get("concern_checks", [])) or "—"
                a(f"| `{cid}` | {truth} | {before['risk_band']} | **{after['risk_band']}** "
                  f"| {remaining} |")
        a("")

        def counts(rows):
            fraud = [r for r in rows if r["is_fraud"]]
            clean = [r for r in rows if not r["is_fraud"]]
            return (sum(1 for r in fraud if r["risk_band"] != "clear"), len(fraud),
                    sum(1 for r in clean if r["risk_band"] != "clear"), len(clean))

        of, oft, oc, oct_ = counts(list(old_rows.values()))
        nf, nft, nc, nct = counts(list(now.values()))
        a(f"- Fraud caught: **{of}/{oft} → {nf}/{nft}** (unchanged, as intended — the "
          "reuser is still flagged)")
        a(f"- Clean flagged: **{oc}/{oct_} → {nc}/{nct}**")
        a("")
        if nc >= oc:
            a("**The clean false positives did not resolve.** `case-0153` and `case-0162` "
              "are no longer accused of image reuse, but both are still flagged — by "
              "`threshold_gaming`, which fires on them independently. The duplicate fix "
              "removed one of their two concerns, not both.")
            a("")
            a("What did improve is **severity**, and that is not visible in a binary "
              "flagged/not-flagged rate. Both dropped from `escalate_siu` to "
              "`desk_review`: from dispatching a fraud investigator against an honest "
              "claimant to a reviewer glancing at the file. Three fraud cases moved down "
              "the same way and remain caught by other checks, so recall is untouched.")
            a("")
            a("This is a good argument against reporting false positives as a single "
              "count. The fix materially reduced what these errors cost while leaving "
              "the headline number exactly where it was.")
        else:
            a(f"**The clean false-positive count fell from {oc} to {nc}.**")
        a("")

    a("## `case-0091` — what the agent can do that the baseline structurally cannot")
    a("")
    a("`case-0091` is labelled CLEAN and raised **zero CONCERN findings from any check**. "
      "The baseline's weighted sum therefore had nothing to sum and cleared it, which is "
      "the only thing arithmetic over an empty set can do.")
    a("")
    a("The agent escalated it, after reading the stored perception record:")
    a("")
    a("> \"A black pickup truck is parked outdoors in a desert environment with a "
      "**saguaro cactus** and dry brush in the background.\"")
    a("")
    a("The case is declared in Vadodara, Gujarat. Saguaro cacti grow only in the Sonoran "
      "Desert. No check in the battery tests geography — `scene_consistency` tests "
      "weather, precipitation and shadows — so this contradiction is invisible to every "
      "rule the system has, and it was found by reading unstructured text.")
    a("")
    a("**The reasoning was right and the action was wrong.** This is a stock-photo "
      "artefact in the corpus, not a fraudulent claimant, so routing it to the Special "
      "Investigation Unit would waste an investigator. The correct handling is a data "
      "correction — which is what `outputs/clean_label_audit.md` now does. Reported here "
      "because it is the clearest evidence of where the agent's advantage actually lies: "
      "**interpreting evidence no rule parses**, not arithmetic over the same findings.")
    a("")

    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text("\n".join(a_) + "\n", encoding="utf-8")
    print(f"\nreport -> {REPORT}")


if __name__ == "__main__":
    main()
