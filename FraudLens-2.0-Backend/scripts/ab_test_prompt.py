"""
A/B the underwriting prompt's "an all-clear set of findings is weak
evidence" paragraph.

--------------------------------------------------------------------------
Why this experiment blocks the ablation
--------------------------------------------------------------------------
The agent smoke test converged 10/10 and showed real adaptive depth, but
cleared **0 of 10** cases including **0 of 5** clean ones, against a
rules-only baseline that clears 99.4% of clean cases. An adjudicator that
never clears has not beaten the baseline; it has routed the whole book to
manual review. Until that is understood, an ablation table reporting recall
would be actively misleading.

Two candidate causes were identified and could not be separated from the
existing run. This isolates one of them.

--------------------------------------------------------------------------
The variable, and what is deliberately held constant
--------------------------------------------------------------------------
Variant A - the current underwriting prompt, which says:

    "on an underwriting case, an all-clear set of findings is weak
     evidence, not strong evidence ... prefer REQUESTING a specific
     further photograph when the file rests entirely on images that
     nothing has been able to corroborate."

Every underwriting case rests entirely on images, so this may fire
unconditionally.

Variant B - identical except that paragraph is replaced by a neutral one
stating that an absence of concerns is legitimate grounds to clear.

The factual sentence above it ("NO CHECK DETECTS THIS ATTACK") is kept in
both. It is measured and true, and removing it would change two things at
once.

--------------------------------------------------------------------------
Quota efficiency: why B runs on fewer cases than A
--------------------------------------------------------------------------
Free tier is ~20 requests/key/day across 5 keys, and the agent averages ~3
calls per case. The naive design - 12 cases x 2 variants = 24 runs - spends
a third of its budget on claims cases whose prompt is **byte-identical**
between the variants, because the paragraph under test exists only in the
underwriting prompt. Those runs cannot produce a difference; they can only
produce sampling noise that looks like one.

So: A runs on all 12 cases, B runs on the 6 underwriting cases. 18 runs
instead of 24, and the A-on-claims half is not waste - it measures the
claims-side clean clear rate, which the smoke test never sampled at all.

Findings are computed once per case and shared by both variants. That is
not only cheaper; it is required. If the two variants saw independently
recomputed findings, any difference could be the checks rather than the
prompt.

Resumable: results are appended to a JSONL as they complete, so a quota
death mid-run costs one case rather than the whole experiment.

Usage:
    python scripts/ab_test_prompt.py
    python scripts/ab_test_prompt.py --cases 12 --fresh
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any, Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]

from src import db
from src.agent.engine import adjudicate
from src.agent.policy import CLAIMS_POLICY, UNDERWRITING_POLICY, AgentPolicy
from src.checks import run_checks
from src.llm import get_provider, is_rate_limit_error, usage_stats
from src.sampling import sample_report, stratified_sample

RESULTS = Path("outputs/ab_test_prompt.jsonl")
REPORT = Path("outputs/ab_test_prompt.md")
SEED = 42

# The exact paragraph under test. Pulled by anchor rather than by line
# number so that an unrelated edit to the prompt makes this fail loudly
# instead of silently testing the wrong text.
VARIANT_A_PARAGRAPH = """\
What this means for you: on an underwriting case, an all-clear set of \
findings is weak evidence, not strong evidence. Weigh the non-image \
signals you can actually reason about - the applicant's history, the \
declared value against the vehicle, anything the tools can retrieve - \
and prefer REQUESTING a specific further photograph when the file rests \
entirely on images that nothing has been able to corroborate."""

VARIANT_B_PARAGRAPH = """\
What this means for you: judge the application on the evidence in front \
of you. An absence of concerns across the checks is legitimate grounds to \
CLEAR an application - it is the expected outcome for an honest \
applicant, and the overwhelming majority of applicants are honest. \
Request further photographs when there is a specific, nameable question \
you could actually answer with one, not merely because photographs are \
the only evidence a break-in inspection has."""


def build_variant_b() -> AgentPolicy:
    """Underwriting policy with the paragraph under test swapped out."""
    prompt = UNDERWRITING_POLICY.system_prompt
    if VARIANT_A_PARAGRAPH not in prompt:
        raise SystemExit(
            "the paragraph under test is no longer present verbatim in "
            "UNDERWRITING_POLICY.system_prompt - update VARIANT_A_PARAGRAPH "
            "before trusting this experiment"
        )
    return dataclasses.replace(
        UNDERWRITING_POLICY,
        system_prompt=prompt.replace(VARIANT_A_PARAGRAPH, VARIANT_B_PARAGRAPH, 1),
        policy_version=UNDERWRITING_POLICY.policy_version + "-variantB",
    )


def policy_for_variant(agent_type: str, variant: str, variant_b: AgentPolicy) -> AgentPolicy:
    if agent_type == "claims":
        return CLAIMS_POLICY
    return UNDERWRITING_POLICY if variant == "A" else variant_b


def load_done() -> set[tuple[str, str]]:
    if not RESULTS.exists():
        return set()
    done: set[tuple[str, str]] = set()
    for line in RESULTS.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue  # a torn final line from a killed run
        done.add((row["variant"], row["case_id"]))
    return done


def load_rows() -> list[dict[str, Any]]:
    if not RESULTS.exists():
        return []
    rows = []
    for line in RESULTS.read_text(encoding="utf-8").splitlines():
        if line.strip():
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return rows


def main(argv: Optional[list[str]] = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", type=int, default=12)
    parser.add_argument("--db-path", default="fraudlens.db")
    parser.add_argument("--fresh", action="store_true", help="discard previous results")
    parser.add_argument("--report-only", action="store_true")
    args = parser.parse_args(argv)

    if args.fresh and RESULTS.exists():
        RESULTS.unlink()

    conn = db.connect(args.db_path)
    db.init_db(conn)
    sample = stratified_sample(conn, args.cases, seed=SEED)
    print(sample_report(sample))

    if args.report_only:
        write_report(load_rows(), sample)
        return

    variant_b = build_variant_b()
    provider = get_provider()
    done = load_done()

    # (variant, case) pairs to run. B only where the prompt differs.
    plan: list[tuple[str, dict[str, Any]]] = []
    for row in sample:
        plan.append(("A", row))
    for row in sample:
        if row["agent_type"] == "underwriting":
            plan.append(("B", row))
    todo = [(v, r) for v, r in plan if (v, r["case_id"]) not in done]
    print(f"\n{len(plan)} run(s) planned, {len(plan) - len(todo)} already done, "
          f"{len(todo)} to run (~{len(todo) * 3} LLM calls)\n")

    # Findings are computed once per case and reused across variants, so
    # the two variants provably see identical evidence.
    findings_cache: dict[str, Any] = {}
    quota_hit = False

    RESULTS.parent.mkdir(parents=True, exist_ok=True)
    with RESULTS.open("a", encoding="utf-8") as fh:
        for variant, row in todo:
            case_id = row["case_id"]
            case = db.get_case(conn, case_id)
            policy = policy_for_variant(row["agent_type"], variant, variant_b)

            if case_id not in findings_cache:
                findings_cache[case_id] = run_checks(
                    conn, case, check_ids=list(policy.check_ids)
                )
            findings = findings_cache[case_id]

            started = time.monotonic()
            try:
                result = adjudicate(conn, case, findings, policy, provider)
            except Exception as e:  # noqa: BLE001
                if is_rate_limit_error(e):
                    print(f"  [{variant}] {case_id}: quota exhausted - stopping, "
                          "re-run to resume")
                    quota_hit = True
                    break
                print(f"  [{variant}] {case_id}: FAILED {type(e).__name__}: {e}")
                continue

            d = result.decision
            record = {
                "variant": variant,
                "case_id": case_id,
                "cell": row["cell"],
                "archetype": row["archetype"],
                "agent_type": row["agent_type"],
                "policy_version": policy.policy_version,
                "risk_band": d.risk_band.value if d.risk_band else None,
                "recommendation": d.recommendation.value,
                "tool_calls": d.tool_calls_count,
                "iterations": d.iterations_count,
                "llm_calls": d.llm_calls_count,
                "converged": result.converged,
                "latency_ms": int((time.monotonic() - started) * 1000),
                "summary": d.summary,
            }
            fh.write(json.dumps(record) + "\n")
            fh.flush()
            print(f"  [{variant}] {case_id} {row['cell']:20s} -> "
                  f"{record['risk_band']:16s} ({d.tool_calls_count} tools, "
                  f"{d.iterations_count} iters)")

            # A run that never reached the model describes an outage, not a
            # decision, and must not be averaged into either variant.
            if d.llm_calls_count == 0:
                print("    (no completed LLM call - provider unreachable; stopping)")
                quota_hit = True
                break

    if quota_hit:
        print("\nstopped early on quota; re-run this script to resume where it left off")
    write_report(load_rows(), sample)
    conn.close()


def _stats(rows: list[dict[str, Any]]) -> dict[str, Any]:
    real = [r for r in rows if r["llm_calls"] > 0]
    if not real:
        return {"n": 0}
    clean = [r for r in real if r["archetype"] == "CLEAN"]
    fraud = [r for r in real if r["archetype"] != "CLEAN"]
    cleared = lambda rs: sum(1 for r in rs if r["risk_band"] == "clear")  # noqa: E731
    esc = sum(1 for r in real if r["risk_band"] == "escalate_siu")
    return {
        "n": len(real),
        "clean_n": len(clean),
        "clean_cleared": cleared(clean),
        "fraud_n": len(fraud),
        "fraud_cleared": cleared(fraud),
        "escalated": esc,
        "mean_tools": sum(r["tool_calls"] for r in real) / len(real),
        "mean_iters": sum(r["iterations"] for r in real) / len(real),
        "mean_calls": sum(r["llm_calls"] for r in real) / len(real),
    }


def _rate(num: int, den: int) -> str:
    return f"{num}/{den} ({num / den:.0%})" if den else "n/a (0 cases)"


def write_report(rows: list[dict[str, Any]], sample: list[dict[str, Any]]) -> None:
    lines: list[str] = []
    a = lines.append

    a("# A/B: the \"all-clear findings are weak evidence\" paragraph")
    a("")
    a("Variant **A** is the current underwriting prompt. Variant **B** replaces one "
      "paragraph with a neutral statement that an absence of concerns is legitimate "
      "grounds to clear. Everything else - checks, findings, sample, seed - is held "
      "identical; findings are computed once per case and shared by both variants, so "
      "no difference here can come from the checks.")
    a("")
    a("Variant B was run only on the **underwriting** cases, because the paragraph "
      "under test exists only in the underwriting prompt: running claims cases twice "
      "would spend quota comparing a prompt against itself. The claims rows under A "
      "are still reported - they measure the claims-side clean clear rate, which the "
      "smoke test's sample never contained.")
    a("")
    a("```")
    a(sample_report(sample))
    a("```")
    a("")

    by_variant = {v: [r for r in rows if r["variant"] == v] for v in ("A", "B")}
    uw = {v: [r for r in by_variant[v] if r["agent_type"] == "underwriting"]
          for v in ("A", "B")}

    a("## Head to head, underwriting only (the cases where the prompts differ)")
    a("")
    a("| Metric | A (current) | B (neutral) |")
    a("|---|---|---|")
    sa, sb = _stats(uw["A"]), _stats(uw["B"])
    if sa.get("n") and sb.get("n"):
        a(f"| Cases adjudicated | {sa['n']} | {sb['n']} |")
        a(f"| **Clear rate on CLEAN** | **{_rate(sa['clean_cleared'], sa['clean_n'])}** "
          f"| **{_rate(sb['clean_cleared'], sb['clean_n'])}** |")
        a(f"| Clear rate on FRAUD (lower is better) | {_rate(sa['fraud_cleared'], sa['fraud_n'])} "
          f"| {_rate(sb['fraud_cleared'], sb['fraud_n'])} |")
        a(f"| Escalation rate | {_rate(sa['escalated'], sa['n'])} | {_rate(sb['escalated'], sb['n'])} |")
        a(f"| Mean tool calls | {sa['mean_tools']:.1f} | {sb['mean_tools']:.1f} |")
        a(f"| Mean iterations | {sa['mean_iters']:.1f} | {sb['mean_iters']:.1f} |")
        a(f"| Mean LLM calls | {sa['mean_calls']:.1f} | {sb['mean_calls']:.1f} |")
    else:
        a("| (insufficient data) | — | — |")
    a("")

    a("## All rows")
    a("")
    a("| Variant | Case | Cell | Archetype | Band | Tools | Iters |")
    a("|---|---|---|---|---|---|---|")
    for r in sorted(rows, key=lambda r: (r["variant"], r["cell"], r["case_id"])):
        a(f"| {r['variant']} | `{r['case_id']}` | {r['cell']} | {r['archetype']} | "
          f"**{r['risk_band']}** | {r['tool_calls']} | {r['iterations']} |")
    a("")

    a("## Claims side under A (new information - the smoke test never sampled it)")
    a("")
    claims_a = [r for r in by_variant["A"] if r["agent_type"] == "claims"]
    sc = _stats(claims_a)
    if sc.get("n"):
        a(f"- Clean claims cases cleared: **{_rate(sc['clean_cleared'], sc['clean_n'])}**")
        a(f"- Fraud claims cases cleared: {_rate(sc['fraud_cleared'], sc['fraud_n'])}")
        a(f"- Escalated: {_rate(sc['escalated'], sc['n'])}")
        a("")
        a("The claims prompt carries its own anti-clearing instruction - *\"prefer "
          "escalating to a human over clearing the case\"* - which this experiment does "
          "**not** vary. If the clean clear rate here is also low, that is a second, "
          "separate problem needing its own A/B, not evidence about the paragraph "
          "under test.")
    else:
        a("- not yet run")
    a("")

    a("---")
    a("")
    a(f"LLM usage this run: `{json.dumps(usage_stats().get('keys', {}), default=str)}`")

    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"\nreport -> {REPORT}")


if __name__ == "__main__":
    main()
