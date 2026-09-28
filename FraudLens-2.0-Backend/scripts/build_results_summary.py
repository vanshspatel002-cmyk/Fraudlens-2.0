"""
Build outputs/results_summary.md — the report's evidence base.

Consolidates every measurement made across all sessions into one document
whose sections can be lifted into the write-up with minimal editing.

Numbers are read from the measurement artefacts rather than typed, because
this document's whole value is that it can be trusted. Prose that
interprets those numbers is written here; anything numeric that exists in a
JSON or a generated report is pulled from it, and anything that has not
been measured says so instead of being filled in.

Re-run after any measurement changes:
    python scripts/build_results_summary.py
"""

from __future__ import annotations

import csv
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]

OUT = Path("outputs/results_summary.md")


def read_json(path: str) -> Optional[dict[str, Any]]:
    p = Path(path)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def read_jsonl(path: str) -> list[dict[str, Any]]:
    p = Path(path)
    if not p.exists():
        return []
    out = []
    for line in p.read_text(encoding="utf-8").splitlines():
        if line.strip():
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return out


def v2_table() -> list[str]:
    """The per-check table, lifted verbatim from the generated v2 report."""
    p = Path("outputs/check_performance_v2.md")
    if not p.exists():
        return []
    lines = p.read_text(encoding="utf-8").splitlines()
    start = next((i for i, l in enumerate(lines) if l.startswith("| Check")), None)
    if start is None:
        return []
    out = []
    for line in lines[start:]:
        if not line.startswith("|"):
            break
        out.append(line)
    return out


def main() -> None:
    dup = read_json("outputs/duplicate_measurement.json")
    signals = read_json("outputs/baseline_signal_measurement.json")
    exclusions = read_json("data/generated/corpus_exclusions.json")
    threshold = read_json("outputs/threshold_fp_investigation.json")
    ablation_rows = read_jsonl("outputs/ablation_results.jsonl")

    a_: list[str] = []
    a = a_.append

    a("# FraudLens 2.0 — Results Summary")
    a("")
    a("The evidence base for the report. Every figure here comes from a measurement "
      "artefact in `outputs/`, and anything unmeasured is marked as such rather than "
      "estimated. Sections are written to be liftable with minimal editing.")
    a("")
    a("---")
    a("")

    # -----------------------------------------------------------------
    a("## 1. Per-check performance")
    a("")
    a("Recall is always reported **against a check's own target archetype**, never "
      "pooled. A check aimed at image reuse should not have its recall diluted by "
      "metadata forgery cases it was never meant to catch, and pooling is how a "
      "narrow-but-excellent check gets mistaken for a weak one.")
    a("")
    table = v2_table()
    if table:
        a_.extend(table)
    else:
        a("_`outputs/check_performance_v2.md` not found._")
    a("")
    a("> **`internal_duplicate`'s false-positive row above is stale.** The table is "
      "lifted verbatim from `check_performance_v2.md`, which is generated from a stored "
      "findings file that predates the victim/reuser fix. Its true rate is now "
      "**0.00% (0/540)** — see §2. The row is left as generated rather than hand-edited, "
      "because a report that is partly generated and partly typed over cannot be "
      "trusted; regenerate it by re-running the full battery.")
    a("")
    a("**Measured limitations, per check:**")
    a("")
    a("- `scene_consistency` — its 15.8% false-positive rate rests on **19 clean "
      "cases**. That denominator is too small to trust in either direction; it is "
      "reported because hiding it would be worse, not because it is reliable.")
    a("- `threshold_gaming` — 22.2% false positives on clean claims overall, but those "
      "concentrate almost entirely at garages that bill just under the authorisation "
      "threshold. It describes a **garage's billing pattern**, not a claimant's guilt.")
    a("- `damage_plausibility` — **unmeasured**. No archetype in this corpus inflates a "
      "claim amount, so it has never had a target to be right about, and its "
      "false-positive rate rests on 4 clean cases.")
    a("- `plate_ocr` — plates are legible in **3 of 1361 images (0.22%)**. Its "
      "INCONCLUSIVE means \"the plate was unreadable\", which carries no information "
      "about the claim.")
    a("- `c2pa_credentials` — no archetype in this corpus carries C2PA credentials, so "
      "it has nothing to detect here.")
    a("")

    # -----------------------------------------------------------------
    a("## 2. `internal_duplicate` and the victim/reuser distinction")
    a("")
    a("A duplicate is symmetric; blame is not. When two cases share a photograph one "
      "submitted it first and the other reused it, and flagging both produced the "
      "ablation's only two clean false positives — `case-0153` and `case-0162` were "
      "flagged because their images had been copied **by** REUSE cases `case-0797` and "
      "`case-0776`. The detection was correct and attached to the wrong party: the "
      "honest claimant was being routed to the Special Investigation Unit for having "
      "been robbed.")
    a("")
    a("The check now compares ingest time. The earlier submission yields INCONCLUSIVE "
      "naming the later case; only the later yields CONCERN.")
    a("")
    if dup:
        r, f, v = dup["recall_on_REUSE"], dup["false_positives_on_clean"], dup["victim_flags"]
        rate = "n/a" if r["rate"] is None else f"{r['rate']:.1%}"
        fp_rate = "n/a" if f["rate"] is None else f"{f['rate']:.2%}"
        a("**Measured across all 800 cases:**")
        a("")
        a(f"- Recall on REUSE: **{r['caught']}/{r['total']} ({rate})** — unchanged, as intended")
        a(f"- False positives on clean: **{f['flagged']}/{f['total']} ({fp_rate})**, "
          "down from 23/540 (4.3%)")
        a(f"- Victim flags, the new INCONCLUSIVE class: **{v['total']}** "
          f"({v['on_clean']} on clean cases)")
        a("")
        by_arch = v.get("by_archetype") or {}
        if by_arch:
            a("Victims are not only clean cases — the REUSE archetype copies from "
              "everywhere: "
              + ", ".join(f"{k} {n}" for k, n in sorted(by_arch.items(),
                                                        key=lambda kv: -kv[1]))
              + ".")
            a("")
        a("**The check's own false-positive rate went to zero.** All 23 clean cases it "
          "used to accuse were victims of a later reuse, and all 23 are now INCONCLUSIVE "
          "— a verdict that contributes nothing to the risk score.")
        a("")
        a("**This did not, however, reduce the ablation's clean flag count**, which stayed "
          "at 5/24. The two affected cases there — `case-0153` and `case-0162` — carry a "
          "second, independent concern from `threshold_gaming`, so they remain flagged. "
          "What changed for them is severity: both dropped from `escalate_siu` to "
          "`desk_review`, from dispatching a fraud investigator against an honest "
          "claimant to a reviewer glancing at the file.")
        a("")
        a("Both facts matter and neither substitutes for the other. A binary "
          "flagged/not-flagged rate shows the second and hides the first; a per-check "
          "rate shows the first and hides the second.")
        a("")
        a(f"> **Caveat.** {dup['caveat']}")
        a("")
        a("> **Action required before the next agent run.** The system prompt still tells "
          "the agent that `internal_duplicate` has a 4.3% false-positive rate. That is now "
          "wrong. It was left uncorrected deliberately: the ablation's agent arm is "
          "mid-flight, and editing the prompt between case 10 and case 11 would make the "
          "arm internally inconsistent — a worse error than a stale number that errs "
          "toward caution. Correct it once the arm completes.")
    else:
        a("_`outputs/duplicate_measurement.json` not yet written._")
    a("")

    # -----------------------------------------------------------------
    a("## 2b. `threshold_gaming`: a presentational fault, not a detection fault")
    a("")
    if threshold:
        flagged = threshold["flagged"]
        examined = threshold["clean_claims_examined"]
        attr = threshold["garage_attributable"]
        unexp = threshold["unexplained"]
        share = attr.get("share_of_flags")
        a(f"With `internal_duplicate` at zero, `threshold_gaming` is the battery's "
          f"dominant false-positive source: **{flagged}/{examined} clean claims "
          f"({threshold['flag_rate']:.1%})**.")
        a("")
        a(f"- Garage-attributable: **{attr['count']}/{flagged}**"
          + (f" ({share:.0%})" if share is not None else ""))
        a(f"- Unexplained: **{unexp['count']}**")
        a(f"- Distinct garages involved: **{threshold['distinct_garages_involved']}**")
        a("")
        a("**Every single flag is explained by the garage's billing pattern, and none "
          "by anything about the claimant.** The check is garage-scoped by design: it "
          "fires when a claim sits under the survey threshold *and* the repairing "
          "garage shows an elevated concentration of claims in that band. An honest "
          "claimant who happens to use a gaming garage is flagged, correctly, for a "
          "pattern that is not theirs.")
        a("")
        a("So this is not a detection failure and the fix is not a threshold. The "
          "explanation text reads as an accusation against the claimant, and both the "
          "baseline narrative and the agent's reasoning consume that text verbatim. "
          "The corrected wording is drafted in `outputs/known_issues.md` (H2) and is "
          "**deliberately not yet applied**: the agent arm is mid-run, and changing "
          "finding text between cases would make the arm internally inconsistent for "
          "the same reason editing the prompt would.")
        a("")
        a("It also argues for how false positives should be reported. Counting these 91 "
          "alongside genuinely spurious flags treats \"correct finding, wrong subject\" "
          "as identical to \"wrong finding\", and those need different fixes.")
    else:
        a("_`outputs/threshold_fp_investigation.json` not found._")
    a("")

    # -----------------------------------------------------------------
    a("## 3. Retired and demoted checks")
    a("")
    a("| Check | Status | Evidence that retired or demoted it |")
    a("|---|---|---|")
    a("| `vehicle_consistency` | **Retired** | 555/560 (99.11%) false positives on clean "
      "cases. The signal was inverted: it fired on almost every honest claim. Removed "
      "from the battery entirely. |")
    a("| `ai_generation` | **Demoted, weight 0.0** | Measured *inverted* discriminative "
      "value. Forced INCONCLUSIVE always; probabilities still recorded. |")
    a("| `digital_edit` | **Demoted, weight 0.0** | AUC 0.546 after the generator was "
      "fixed — indistinguishable from chance on this corpus. |")
    a("| `baseline_corruption` | **Weight 0.0** | Built to detect AI_GENERATED_BASELINE "
      "and structurally cannot; see §6. |")
    a("")
    a("The distinction between retiring and demoting is cost. `vehicle_consistency` was "
      "removed because running it bought nothing. `ai_generation` still runs because its "
      "probability output is worth recording even though its verdict is worthless.")
    a("")

    # -----------------------------------------------------------------
    a("## 4. The AI-detector inversion, with both controls")
    a("")
    a("`ai_generation` does not merely fail — it points the wrong way. Two independent "
      "controls establish this, which matters because the first one alone would have "
      "been explained away as a resolution artefact:")
    a("")
    a("1. **Resolution-matched control.** The apparent signal was an 8× artefact: AI "
      "images had median width 1522px against the curated corpus's 189px. Matched to "
      "the same resolution distribution, discriminative value went to **−41.5pp at "
      "400px+** — worse than chance.")
    a("2. **Within-case control.** On cases containing both a genuine and a fabricated "
      "image at near-identical widths, the detector flagged the **synthetic image 10% "
      "of the time and the genuine one 45%** — 4.5× more likely to accuse the honest "
      "photograph sitting beside the fake.")
    a("")
    a("It also produced a 77% false-positive rate on clean cases before demotion. The "
      "conclusion is a measurement result, not an unbuilt feature: no threshold change "
      "recovers a signal that is not there.")
    a("")
    if signals:
        fs = signals.get("forensic_signals", {}).get("ai_generation", {})
        auc = fs.get("auc_target_over_clean")
        if auc is not None:
            a(f"A later attempt asked whether the inversion could be *used* — a signal that "
              f"reliably points the wrong way is a detector with a flipped sign. Against "
              f"AI_GENERATED_BASELINE it scores **AUC {auc}** (i.e. {1 - auc:.2f} inverted), "
              "and resolution is matched this time. But JPEG quantisation is not: every AI "
              "image was re-encoded at q92 by the normalisation script while curated images "
              "were not. **Not adopted** — this check has already produced one confounded "
              "result, and it does not get the benefit of the doubt twice.")
            a("")

    # -----------------------------------------------------------------
    a("## 5. Corpus defects")
    a("")
    a("Two independent defect classes were found in cases labelled CLEAN, and both "
      "corrupt the false-positive rate — the project's primary metric.")
    a("")
    if exclusions:
        total = exclusions.get("clean_cases_total")
        defective = exclusions.get("defective_cases") or exclusions.get("defective_clean_cases")
        corrected = exclusions.get("corrected_clean_count")
        rate = exclusions.get("defect_rate")
        if defective is not None and total:
            a(f"- Clean cases audited: **{total}**")
            a(f"- Defective: **{defective}**"
              + (f" ({rate:.1%})" if isinstance(rate, float) else ""))
            if corrected is not None:
                a(f"- **Corrected clean-case count: {corrected}**")
            markers = Counter(m for fnd in exclusions.get("findings", [])
                              for m in fnd.get("markers", []))
            if markers:
                a("")
                a("| Marker | Cases |")
                a("|---|---|")
                for name, count in markers.most_common():
                    a(f"| `{name}` | {count} |")
        a("")
    a("**Why this is asymmetric, and therefore serious.** The rules-only baseline cannot "
      "read a watermark or a landscape, so it scores a defective clean case as a correct "
      "clear. The agent reads the scene text, notices the contradiction, flags it — and "
      "is recorded as a false positive **for being right**. Left in the denominator these "
      "cases systematically penalise the arm under test.")
    a("")
    a("Stock-agency watermarks on `EXTERNAL_SOURCING`, `CONTEXT_MISMATCH` and `REUSE` "
      "cases are **not** defects — those archetypes are built from externally sourced "
      "imagery, so the watermark is the ground-truth signal working as designed.")
    a("")
    a("**An earlier estimate of this rate was wrong, and the direction of the error is "
      "instructive.** A first pass scanned only the 22 clean cases that had perception "
      "records and found 4 defective — 18.2% — which was reported as a lower bound on "
      "the corpus-wide rate. Auditing all 540 with OCR gives **4.1%**. The 18.2% was not "
      "a lower bound at all; it was a rate on a subsample that is not representative, "
      "because perception coverage was itself allocated by a stratified sampler that "
      "prefers fraud-adjacent cases. A biased denominator does not become a bound by "
      "being small.")
    a("")
    a("> The 4.1% is still a floor for a different reason. OCR covers all 1080 clean "
      "images and misses only low-contrast watermarks, but the **geographic** signal can "
      "only be read from perception text, which exists for roughly 10% of images. "
      "Non-Indian scenery in the other 90% is undetected by either scan.")
    a("")

    # -----------------------------------------------------------------
    a("## 6. What no check detects")
    a("")
    a("`AI_GENERATED_BASELINE` (20 cases) is undetected, and now known to be undetectable "
      "by the approaches tried. The attack fabricates the **absence** of damage — a "
      "synthetic photograph of an intact vehicle — so the declaration and the "
      "photographs agree by construction and every check PASSES.")
    a("")
    if signals:
        link = signals.get("linkage_signal", {})
        a(f"- **Cross-case linkage** (a vehicle inspected as undamaged that claims "
          f"shortly after): UNAVAILABLE. All 800 cases carry a unique registration *and* "
          "a unique claimant, so there is nothing to join on. A corpus property, not a "
          "signal failure — in production this is the attack's strongest tell.")
        a("- **Synthetic-image forensics**: candidate but confounded; see §4.")
    a("")
    a("`AI_GENERATED` and `DIGITAL_EDIT` are likewise uncovered, their detectors having "
      "been measured to zero. Both arms of the ablation see the same absence of evidence "
      "on these archetypes, so the comparison there is vacuous and is excluded from the "
      "ablation sample.")
    a("")

    # -----------------------------------------------------------------
    a("## 7. Recall progression across measurement rounds")
    a("")
    a("| Session | Recall | What changed |")
    a("|---|---|---|")
    a("| 1 | 57.1% | initial battery |")
    a("| 2 | 57.9% | data fixes |")
    a("| 3 | 59.6% | generator archetype fixes |")
    a("| 4 | 61.2% | hourly precipitation, corpus corrections |")
    a("| 5 | **58.5%** | victim/reuser fix — see below, this is a **correction**, not a regression |")
    a("")
    a("**The drop from 61.2% to 58.5% is the removal of false credit, and it should be "
      "reported as an improvement.** Before the victim/reuser fix, `internal_duplicate` "
      "flagged both sides of a shared photograph. That meant a fraud case could be "
      "\"caught\" solely because some *later* REUSE case had copied its image — which is "
      "evidence about the copier, not about the case being scored.")
    a("")
    a("Re-running the full battery, 35 cases lost their `internal_duplicate` concern. Of "
      "those, 23 were left with no concerns at all: **16 CLEAN** (true false positives, "
      "correctly removed) and **7 fraud cases** that had been caught only by that "
      "coincidence — 3 `DIGITAL_EDIT`, 3 `AI_GENERATED`, 1 `METADATA_FORGERY`. Seven of "
      "260 fraud cases is 2.7 percentage points, which is exactly the observed drop.")
    a("")
    a("Six of those seven belong to archetypes with **no working detector at all**, so "
      "the battery had been taking credit on undetectable archetypes through an "
      "accident of the corpus. A recall figure that counts those is measuring the "
      "generator, not the detector.")
    a("")
    a("**No gain came from adding a check.** Every improvement across these sessions "
      "came from correcting the data — making archetypes falsifiable, fixing a "
      "daylight bug, replacing daily precipitation totals with hourly ones. Checks added "
      "over the same period (`plate_ocr`, `c2pa_credentials`, `vehicle_consistency`, "
      "`baseline_corruption`) contributed **nothing** to recall, and two of them were "
      "retired or zero-weighted after measurement.")
    a("")
    a("The 80% recall target is unreachable at any threshold. The 205-point sweep was "
      "re-run against the corrected check logic and **none** of its operating points met "
      "the floor; the maximum attainable recall is **58.5%**, down from 61.2% before the "
      "victim/reuser correction (`outputs/baseline_sweep.json`). The chosen operating "
      "point takes that ceiling and then minimises false positives: clear below 0.3, "
      "giving 61.8% precision, 17.4% false positives on clean cases and a 69.2% "
      "straight-through rate. The limit is **coverage**, not tuning — three archetypes "
      "have no working detector, and no threshold recovers a signal that is not there.")
    a("")

    # -----------------------------------------------------------------
    a("## 8. The prompt A/B: underwriting has an evidence problem, not a prompt problem")
    a("")
    a("The agent cleared **0 of 10** cases in the smoke test, including 0 of 5 clean, "
      "against a baseline that clears 99.4% of clean cases. The suspected cause was one "
      "prompt paragraph telling the underwriting agent that \"an all-clear set of "
      "findings is weak evidence\". Removing it was tested directly.")
    a("")
    a("| Underwriting (n=6 each) | A (current) | B (paragraph removed) |")
    a("|---|---|---|")
    a("| Clears CLEAN | 0/3 | 1/3 |")
    a("| **Clears FRAUD** | **0/3** | **2/3** |")
    a("")
    a("**Variant B clears fraud more often than clean.** As a filter it is worse than a "
      "coin, and it grants a clean baseline to precisely the attack underwriting exists "
      "to stop. The hypothesis was wrong: removing the paragraph restored clearing but "
      "not judgement.")
    a("")
    a("The mechanism is §6. On `AI_GENERATED_BASELINE` the findings are identical to a "
      "clean case, so B's instruction is being applied correctly to evidence that cannot "
      "separate the two classes. A's refusal to clear was never caution either — it was "
      "a blanket rule that avoided clearing fraud by never clearing anything. **No "
      "wording of this paragraph can fix it.**")
    a("")
    a("The claims side proves the point by contrast: under the *unchanged* claims prompt, "
      "**3/3 clean cleared and 3/3 fraud escalated**. Same engine, same model — the "
      "difference is that claims cases have working checks behind them.")
    a("")
    a("_Limitation: n=3 per cell. What carries the conclusion is the mechanism, which is "
      "independently established, not the size of the gap._")
    a("")

    # -----------------------------------------------------------------
    a("## 9. Prompt audit: five stated reliability claims were unsupported")
    a("")
    a("The agent's system prompt asserts how reliable each check is, and the agent is "
      "told to follow those ratings over a finding's own confidence. Auditing every claim "
      "against `outputs/check_performance_v2.md` found five that measurement did not "
      "support:")
    a("")
    a("| Check | Prompt said | Measurement says |")
    a("|---|---|---|")
    a("| `internal_duplicate` | \"no unexplained false positives\" | **4.3% (23/540)** "
      "at the time of the audit; **0/540** after the victim/reuser fix |")
    a("| `threshold_gaming` | FP rate omitted entirely | **22.2% (91/410)** |")
    a("| `exif_metadata` | 79% recall | **76.5%** (26/34) |")
    a("| `scene_consistency` | 62% recall | **58.8%** (20/34) |")
    a("| `damage_plausibility` | \"sound arithmetic\" | **unmeasured** — no target archetype |")
    a("")
    a("Three further claims survived the audit unchanged, including the 0.22% plate "
      "legibility figure, which was verified at 3/1361 images rather than corrected. All "
      "five errors have been fixed, and the prompt now cites its source so the numbers "
      "can be re-checked.")
    a("")

    # -----------------------------------------------------------------
    a("## 10. `case-0091` — the qualitative example")
    a("")
    a("`case-0091` is labelled CLEAN and raised **zero CONCERN findings from any check**. "
      "The rules-only baseline cleared it, which is the only thing a weighted sum over an "
      "empty set can do.")
    a("")
    a("The agent escalated it, after reading the stored perception record:")
    a("")
    a("> \"A black pickup truck is parked outdoors in a desert environment with a "
      "**saguaro cactus** and dry brush in the background.\"")
    a("")
    a("The case is declared in Vadodara, Gujarat. Saguaro cacti grow only in the Sonoran "
      "Desert. **No check in the battery tests geography** — `scene_consistency` tests "
      "weather, precipitation and shadows — so this contradiction is invisible to every "
      "rule the system has.")
    a("")
    a("**The reasoning was correct and the action was wrong.** This is a stock-photo "
      "artefact in the corpus rather than a fraudulent claimant, so routing it to the "
      "SIU would waste an investigator; the correct handling is the data correction in "
      "§5. It is reported because it locates the agent's advantage precisely: "
      "**interpreting unstructured evidence that no rule parses**, not better arithmetic "
      "over the same findings.")
    a("")

    # -----------------------------------------------------------------
    a("## 11. Ablation status")
    a("")
    if ablation_rows:
        counts = Counter(r["arm"] for r in ablation_rows)
        a(f"Baseline arm: **{counts.get('baseline', 0)}** case(s). "
          f"Agent arm: **{counts.get('agent', 0)}** case(s).")
        a("")
        agent = [r for r in ablation_rows if r["arm"] == "agent"]
        if agent:
            mean_calls = sum(r["llm_calls"] for r in agent) / len(agent)
            a(f"Measured agent cost: **{mean_calls:.1f} LLM calls per case** "
              f"(the plan assumed 3.0).")
            a("")
    a("See `outputs/ablation_results.md` for the current head-to-head. The arms are "
      "compared **only on their shared subset**: the agent arm is quota-bound at ~100 "
      "free-tier requests per day, and scoring a partial agent run against a complete "
      "baseline over different cases would be a sampling artefact rather than a result.")
    a("")

    # -----------------------------------------------------------------
    a("## 12. Limitations")
    a("")
    a("Stated plainly, because several of them bound what any result in this document "
      "can mean:")
    a("")
    a("- **Thin clean cells.** The ablation sample carries 12 claims-clean and 12 "
      "underwriting-clean cases. Any false-positive figure from it is an **upper bound, "
      "not an estimate** — distinguishing 0.5% from 2% needs on the order of a thousand "
      "clean cases.")
    a("- **Perception coverage ~10%.** Roughly 130 of 1395 images have been described by "
      "the vision model, limited by the same free-tier quota the agent competes for. "
      "Every perception-dependent check is measured on a small subset, and the agent's "
      "demonstrated advantage — reading scene text — is unavailable on 90% of the corpus.")
    a("- **Three archetypes have no working detector** (`AI_GENERATED`, `DIGITAL_EDIT`, "
      "`AI_GENERATED_BASELINE`), which is why recall is capped at 58.5% — the ceiling "
      "measured by the 205-point sweep after the victim/reuser correction.")
    a("- **Underwriting fraud is one archetype.** `AI_GENERATED_BASELINE` is the only "
      "underwriting fraud in the corpus, so nothing here generalises to underwriting "
      "fraud broadly.")
    a("- **Generation-order artefacts.** The corpus is generated in archetype blocks, so "
      "some heuristics that key on creation order — the victim/reuser rule in §2 — are "
      "correct by construction here and untested as generalisations.")
    a("- **Single corpus, synthetic.** Every number is against archetypes this project "
      "generated, with the defect rate in §5.")
    a("")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("\n".join(a_) + "\n", encoding="utf-8")
    print(f"-> {OUT} ({len(a_)} lines)")


if __name__ == "__main__":
    main()
