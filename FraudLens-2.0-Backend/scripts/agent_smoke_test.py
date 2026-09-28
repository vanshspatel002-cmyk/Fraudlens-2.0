"""
Smoke-test the agent on real cases with real quota.

Ten cases - five fraud, five clean, both agent types - adjudicated end to
end against the live model. The point is not to measure accuracy; ten
cases cannot. The point is to answer three questions that the offline
suite cannot:

  1. Does the loop hold together against a real model's output, rather
     than against replies a test author wrote to be parseable?
  2. **How often does the agent call a follow-up tool?** This is the
     agentic claim under test. If it never calls one, it is an expensive
     way to read a list the baseline reads for free, and the ablation
     should report that rather than assume adaptive depth happened.
  3. Are the narratives things a claims handler could act on?

Selection is stratified and seeded so the same ten cases are used on
every re-run - comparing a narrative against a different case's narrative
would tell us nothing.

Writes outputs/agent_smoke_test.md.

Usage:
    python scripts/agent_smoke_test.py
    python scripts/agent_smoke_test.py --limit 4     # fewer, to save quota
"""

from __future__ import annotations

import argparse
import csv
import json
import random
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any, Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]

from src import db
from src.agent.engine import adjudicate
from src.agent.policy import policy_for
from src.checks import run_checks
from src.llm import get_provider, is_rate_limit_error, usage_stats
from src.models import Verdict

GROUND_TRUTH_CSV = Path("data/generated/ground_truth.csv")
OUTPUT = Path("outputs/agent_smoke_test.md")
SEED = 42


def select_cases(conn, n_fraud: int, n_clean: int) -> list[tuple[str, str]]:
    """
    (case_id, archetype) pairs: fraud and clean, both agent types.

    Prefers cases that have perception coverage, because a case the vision
    pass never reached gives the agent a wall of INCONCLUSIVEs and tests
    little beyond the fallback path - which the offline suite already
    covers thoroughly.
    """
    with open(GROUND_TRUTH_CSV, encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    archetype = {r["case_id"]: r["archetype"] for r in rows}

    perceived = {
        r[0] for r in conn.execute(
            "SELECT DISTINCT i.case_id FROM images i "
            "JOIN perception_records p ON i.content_hash = p.content_hash"
        )
    }
    cases = {c.case_id: c for c in db.get_all_cases(conn)}

    def pick(pool: list[str], k: int) -> list[str]:
        rng = random.Random(SEED)
        with_perception = sorted(c for c in pool if c in perceived)
        without = sorted(c for c in pool if c not in perceived)
        rng.shuffle(with_perception)
        rng.shuffle(without)
        return (with_perception + without)[:k]

    fraud_pool = [c for c, a in archetype.items() if a != "CLEAN" and c in cases]
    clean_pool = [c for c, a in archetype.items() if a == "CLEAN" and c in cases]

    # Guarantee at least one underwriting case on each side, so both
    # policies are actually exercised rather than only the claims one.
    uw_fraud = [c for c in fraud_pool if cases[c].agent_type == "underwriting"]
    uw_clean = [c for c in clean_pool if cases[c].agent_type == "underwriting"]

    chosen: list[str] = []
    chosen += pick(uw_fraud, 1)
    chosen += [c for c in pick(fraud_pool, n_fraud + 2) if c not in chosen][: n_fraud - len(chosen)]
    clean_chosen: list[str] = pick(uw_clean, 1)
    clean_chosen += [c for c in pick(clean_pool, n_clean + 2) if c not in clean_chosen][: n_clean - len(clean_chosen)]

    return [(c, archetype[c]) for c in chosen + clean_chosen]


def main(argv: Optional[list[str]] = None) -> None:
    parser = argparse.ArgumentParser(description="Smoke-test the agent on real cases.")
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--db-path", default="fraudlens.db")
    args = parser.parse_args(argv)

    conn = db.connect(args.db_path)
    db.init_db(conn)
    provider = get_provider()

    half = max(1, args.limit // 2)
    selected = select_cases(conn, half, args.limit - half)
    print(f"selected {len(selected)} cases: "
          f"{Counter(a for _, a in selected)}")

    results: list[dict[str, Any]] = []
    quota_hit = False

    for case_id, archetype in selected:
        case = db.get_case(conn, case_id)
        policy = policy_for(case.agent_type)
        started = time.monotonic()
        findings = run_checks(conn, case, check_ids=list(policy.check_ids))
        check_ms = int((time.monotonic() - started) * 1000)

        try:
            result = adjudicate(conn, case, findings, policy, provider)
        except Exception as e:  # noqa: BLE001
            if is_rate_limit_error(e):
                print(f"  {case_id}: quota exhausted, stopping early")
                quota_hit = True
                break
            print(f"  {case_id}: FAILED {type(e).__name__}: {e}")
            continue

        d = result.decision
        concerns = [f for f in findings if f.verdict is Verdict.CONCERN]
        results.append({
            "case_id": case_id, "archetype": archetype, "agent_type": case.agent_type,
            "policy": policy.policy_version,
            "recommendation": d.recommendation.value,
            "risk_band": d.risk_band.value if d.risk_band else None,
            "tool_calls": d.tool_calls_count, "iterations": d.iterations_count,
            "llm_calls": d.llm_calls_count, "latency_ms": d.latency_ms,
            "check_ms": check_ms, "converged": result.converged,
            "coerced": result.coerced_rejection,
            "concerns": [f.check_id for f in concerns],
            "narrative": d.summary,
            "cited": len(d.supporting_finding_ids),
            "artifacts": d.requested_artifacts,
            "tools_used": [s.detail for s in result.trace if s.kind == "tool_call"],
        })
        print(f"  {case_id} [{archetype}] -> {results[-1]['risk_band']} "
              f"({d.tool_calls_count} tools, {d.iterations_count} iters)")

        # If the daily quota died mid-pass every later case would produce
        # an identical non-convergence, which would look like a finding
        # about the agent rather than about the free tier.
        if not result.converged and d.llm_calls_count <= 1:
            print("  (non-convergence on the first call - likely quota; stopping)")
            quota_hit = True
            break

    write_report(results, quota_hit, len(selected))
    conn.close()


def write_report(results: list[dict[str, Any]], quota_hit: bool, attempted: int) -> None:
    lines: list[str] = []
    a = lines.append

    # A case whose adjudication never got a successful model call is a
    # record of an outage, not of the agent. Counting it as "adjudicated"
    # would let a quota failure masquerade as a measured decision, and
    # every downstream number (tool-use rate, mean iterations) would be
    # computed over a population that never ran.
    real = [r for r in results if r["llm_calls"] > 0]
    stalled = [r for r in results if r["llm_calls"] == 0]

    a("# Agent Smoke Test")
    a("")
    a(f"{len(real)} of {attempted} selected cases genuinely adjudicated against the live model.")
    if stalled:
        a("")
        a(f"> **{len(stalled)} case(s) never reached the model at all** - the provider was "
          "unreachable (free-tier quota) so they took the DESK_REVIEW fallback without a single "
          "completed LLM call. They are listed below for completeness but are excluded from every "
          "statistic: they describe an outage, not an adjudication, and averaging them in would "
          "report a tool-use rate for cases that never ran.")
    if quota_hit:
        a("")
        a("> **Stopped early on free-tier quota.** The remaining cases were not attempted, "
          "because every one of them would have produced an identical non-convergence that "
          "described the outage rather than the case.")
    a("")

    if not real:
        a("")
        a("**No case reached the model.** Free-tier quota was exhausted before the first "
          "adjudication completed, so this run measured nothing about the agent. The offline "
          "suite (test_agent.py, 16 tests) covers loop, parsing, guard and trace behaviour "
          "without quota; what is still unvalidated is how a real model behaves against these "
          "prompts, and that needs a quota reset rather than a code change.")
        if stalled:
            a("")
            a("| Case | Archetype | Agent | Outcome |")
            a("|---|---|---|---|")
            for r in stalled:
                a(f"| `{r['case_id']}` | {r['archetype']} | {r['agent_type']} | "
                  f"provider unreachable -> {r['risk_band']} fallback |")
        OUTPUT.parent.mkdir(parents=True, exist_ok=True)
        OUTPUT.write_text("\n".join(lines) + "\n", encoding="utf-8")
        print(f"\nreport -> {OUTPUT}")
        return

    tool_users = [r for r in real if r["tool_calls"] > 0]
    total_tools = sum(r["tool_calls"] for r in real)
    tool_names = Counter(t for r in real for t in r["tools_used"])

    a("## The agentic claim: did it choose to dig deeper?")
    a("")
    a("This is what separates the agent from the rules-only baseline. The baseline reads the "
      "findings and applies arithmetic; the agent can decide it needs another fact first. If "
      "it never does, the ablation is comparing an expensive list-reader against a cheap one.")
    a("")
    a(f"- Cases where the agent called at least one tool: **{len(tool_users)}/{len(real)}**")
    a(f"- Total tool calls: **{total_tools}**")
    a(f"- Mean iterations: **{sum(r['iterations'] for r in real) / len(real):.1f}**")
    a(f"- Mean LLM calls: **{sum(r['llm_calls'] for r in real) / len(real):.1f}**")
    a(f"- Mean latency: **{sum(r['latency_ms'] for r in real) / len(real) / 1000:.1f}s** "
      f"(checks alone: {sum(r['check_ms'] for r in real) / len(real) / 1000:.1f}s)")
    if tool_names:
        a(f"- Tools chosen: {', '.join(f'`{k}` x{v}' for k, v in tool_names.most_common())}")
    a("")
    converged = sum(1 for r in real if r["converged"])
    a(f"Converged: **{converged}/{len(real)}**. Coerced rejections: "
      f"**{sum(1 for r in real if r['coerced'])}**.")
    a("")

    # The clear rate belongs next to the tool-use rate, not buried in the
    # per-case table. An adjudicator that never clears anything has a
    # perfect recall and is useless: it has moved the whole book to manual
    # review. The rules-only baseline clears 99.4% of clean cases, so this
    # is the number the ablation turns on.
    cleared = [r for r in real if r["risk_band"] == "clear"]
    clean_real = [r for r in real if r["archetype"] == "CLEAN"]
    clean_cleared = [r for r in clean_real if r["risk_band"] == "clear"]
    a("## Did it clear anything?")
    a("")
    a(f"- Cases cleared: **{len(cleared)}/{len(real)}**")
    if clean_real:
        a(f"- Clean cases cleared: **{len(clean_cleared)}/{len(clean_real)}**")
    by_side = Counter(r["agent_type"] for r in clean_real)
    if by_side:
        a(f"- Clean cases by policy: {dict(by_side)}")
    if clean_real and not clean_cleared:
        a("")
        a("> **The agent cleared no clean case.** On this sample it sends every "
          "clean file to a human, which is a worse outcome than the rules-only "
          "baseline's 0.56% false-positive rate, not a better one. Recall means "
          "nothing without this number beside it.")
    a("")

    a("## Per case")
    a("")
    a("| Case | Archetype | Agent | Band | Tools | Iters | Concerns raised |")
    a("|---|---|---|---|---|---|---|")
    for r in real:
        concerns = ", ".join(sorted(set(r["concerns"]))) or "none"
        a(f"| `{r['case_id']}` | {r['archetype']} | {r['agent_type']} | **{r['risk_band']}** "
          f"| {r['tool_calls']} | {r['iterations']} | {concerns} |")
    a("")

    a("## Narratives")
    a("")
    a("The output a claims handler would actually read.")
    a("")
    for r in real:
        a(f"### `{r['case_id']}` — {r['archetype']} → {r['risk_band']}")
        a("")
        a(f"*{r['agent_type']} agent, {r['tool_calls']} tool call(s), {r['iterations']} iteration(s), "
          f"{r['cited']} finding(s) cited, {r['latency_ms'] / 1000:.1f}s*")
        a("")
        if r["tools_used"]:
            a(f"Tools chosen: {', '.join('`' + t + '`' for t in r['tools_used'])}")
            a("")
        a(f"> {r['narrative']}")
        a("")
        if r["artifacts"]:
            a("Requested:")
            for artifact in r["artifacts"]:
                a(f"- {artifact}")
            a("")

    a("---")
    a("")
    a(f"LLM usage this run: `{json.dumps(usage_stats()['keys'], default=str)}`")

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"\nreport -> {OUTPUT}")
    print(f"tool-using cases: {len(tool_users)}/{len(real)}, total tool calls: {total_tools}")


if __name__ == "__main__":
    main()
