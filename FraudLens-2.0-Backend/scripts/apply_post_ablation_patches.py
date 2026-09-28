"""
Apply the two changes that are queued behind the ablation.

Both are correct and both are blocked for the same reason: the agent reads
the policy prompt and reads `finding.explanation` verbatim, so changing
either mid-run would leave the agent arm internally inconsistent - some
cases judged under one set of stated facts and some under another. That is
a worse error than a stale number, so they wait.

  H1  The prompt tells the agent `internal_duplicate` has a 4.3%
      false-positive rate. Since the victim/reuser fix it is 0.00% (0/540).
      The prompt instructs the agent to follow these ratings over a
      finding's own confidence, so a wrong figure changes decisions.

  H2  `threshold_gaming`'s explanation reads as an accusation against the
      claimant. The investigation found 91 of 91 flags garage-attributable
      and 0 unexplained: the check is right and the wording is wrong.

This script refuses to run until the agent arm reports 99/99, applies both,
and re-runs the affected tests. It is idempotent - re-running after a
successful application is a no-op.

Usage:
    python scripts/apply_post_ablation_patches.py
    python scripts/apply_post_ablation_patches.py --check      # report readiness only
    python scripts/apply_post_ablation_patches.py --force      # override the gate
"""

from __future__ import annotations

import argparse
import io
import json
import subprocess
import sys
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]

RESULTS = Path("outputs/ablation_results.jsonl")
SAMPLE = Path("outputs/ablation_sample.json")
POLICY = Path("src/agent/policy.py")
THRESHOLD = Path("src/checks/threshold.py")

# --- H1 -------------------------------------------------------------------
H1_OLD = """    internal_duplicate   100% recall on image reuse (35/35), but 4.3% false positives
                         on clean cases (23/540) - NOT zero, as an earlier version of
                         this prompt claimed. A CONCERN means two submitted photographs
                         are near-identical, which is usually reuse and occasionally an
                         honest claimant photographing the same panel twice. Strong
                         evidence; not proof on its own."""

H1_NEW = """    internal_duplicate   100% recall on image reuse (35/35) and 0.00% false positives
                         on clean cases (0/540). A CONCERN means this case submitted a
                         photograph that had already been submitted by an EARLIER case -
                         the duplication is evidence against this claimant. Where the
                         earlier submission is the one you are reading, the check
                         returns INCONCLUSIVE naming the later case instead, because
                         being copied is not evidence of anything. Act on a CONCERN
                         directly."""

# --- H2 -------------------------------------------------------------------
H2_OLD = '''            explanation = (
                f"Claim of ₹{amount:,.0f} falls below the ₹{band_high:,.0f} survey threshold; "
                f"garage {case.garage_id} has {stats['garage_in_band_pct']:.0f}% of its "
                f"{stats['garage_claim_count']} claims in this band versus a "
                f"{stats['population_in_band_pct']:.0f}% population average."
            )'''

H2_NEW = '''            # Wording, not logic. Measured on this corpus: 91 of 91 flags on
            # clean claims were explained by the garage's billing pattern and
            # 0 were unexplained (outputs/threshold_fp_investigation.json).
            # The check is right; the previous sentence simply read as an
            # accusation against a claimant whose only mistake was choosing a
            # repairer. Both the baseline narrative and the agent consume this
            # text verbatim, so the subject of the sentence matters.
            explanation = (
                f"This finding concerns the repairing garage, not the claimant. "
                f"Garage {case.garage_id} bills {stats['garage_in_band_pct']:.0f}% of its "
                f"{stats['garage_claim_count']} claims into the band just under the "
                f"₹{band_high:,.0f} survey threshold, against a population average of "
                f"{stats['population_in_band_pct']:.0f}%. This claim of ₹{amount:,.0f} "
                f"falls in that band. The pattern is the garage's; nothing here indicates "
                f"the claimant did anything wrong, and this finding alone is not grounds "
                f"to challenge them."
            )'''


def agent_progress() -> tuple[int, int]:
    """(agent cases done, cases in the frozen sample)."""
    done = 0
    if RESULTS.exists():
        for line in RESULTS.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                if json.loads(line)["arm"] == "agent":
                    done += 1
            except (json.JSONDecodeError, KeyError):
                continue
    total = 0
    if SAMPLE.exists():
        total = len(json.loads(SAMPLE.read_text(encoding="utf-8"))["cases"])
    return done, total


def apply(path: Path, old: str, new: str, label: str) -> str:
    text = io.open(path, encoding="utf-8").read()
    if new in text:
        return f"  {label}: already applied"
    if old not in text:
        return (f"  {label}: TARGET NOT FOUND — the source has changed since this patch "
                "was written. Review manually; nothing was modified.")
    io.open(path, "w", encoding="utf-8").write(text.replace(old, new, 1))
    return f"  {label}: applied"


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="report readiness, change nothing")
    parser.add_argument("--force", action="store_true",
                        help="apply even though the agent arm is incomplete")
    args = parser.parse_args(argv)

    done, total = agent_progress()
    ready = total > 0 and done >= total
    print(f"agent arm: {done}/{total or '?'}")

    if args.check:
        print("READY" if ready else "NOT READY — patches must not be applied yet")
        return 0 if ready else 1

    if not ready and not args.force:
        print(
            "\nREFUSING TO APPLY.\n"
            "The agent reads both the policy prompt and finding explanations verbatim. "
            "Changing either while the arm is incomplete would leave some cases judged "
            "under different stated facts than others, which is a worse error than the "
            "stale figures these patches fix.\n"
            "Re-run when the arm reports its full sample, or pass --force if you have "
            "decided to discard the arm and start it over.",
            file=sys.stderr,
        )
        return 1

    if args.force and not ready:
        print("--force: applying with an incomplete arm; existing agent rows are now "
              "inconsistent with later ones and should be discarded.", file=sys.stderr)

    print("\napplying:")
    print(apply(POLICY, H1_OLD, H1_NEW, "H1 internal_duplicate reliability figure"))
    print(apply(THRESHOLD, H2_OLD, H2_NEW, "H2 threshold_gaming explanation wording"))

    print("\nre-running affected tests:")
    failures = 0
    for suite in ("test_agent.py", "test_checks.py"):
        print(f"  {suite} ...", flush=True)
        proc = subprocess.run([sys.executable, suite], capture_output=True, text=True)
        tail = [l for l in proc.stdout.splitlines() if "passed," in l]
        print(f"    {tail[-1] if tail else 'no result line'}")
        if proc.returncode != 0:
            failures += 1
            for line in proc.stdout.splitlines():
                if line.startswith("FAIL"):
                    print(f"    {line}")

    if failures:
        print(f"\n{failures} suite(s) failed — review before committing.", file=sys.stderr)
        return 1

    print("\nboth patches applied and the affected suites pass.")
    print("Regenerate the reports that quote these figures:")
    print("  python scripts/build_results_summary.py")
    print("  python scripts/run_ablation.py --report-only")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
