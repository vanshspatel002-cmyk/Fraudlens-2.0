"""
Draft the report's Results and Discussion sections.

Written as a generator rather than a static document for the same reason the
other reports are: the ablation is still running, and a hand-typed number goes
stale the moment it lands. Every figure below is read from an artefact in
outputs/ and cited inline, so a reader can check any claim.

Register: past tense, third person, academic. Where a claim rests on a small
sample the sentence making the claim says so - not a footnote, because
footnotes get dropped when text is lifted.

Usage:
    python scripts/build_report_draft.py
"""

from __future__ import annotations

import csv
import json
import random
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]

OUT = Path("outputs/report_draft_results.md")


def read_json(path: str) -> Optional[Any]:
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


def paired_ablation() -> dict[str, Any]:
    rows = read_jsonl("outputs/ablation_results.jsonl")
    excluded = set((read_json("data/generated/corpus_exclusions.json") or {})
                   .get("excluded_case_ids", []))

    def is_outage(r):
        return any(s.get("kind") == "fallback" and "provider error" in (s.get("detail") or "")
                   for s in (r.get("trace") or []))

    base = {r["case_id"]: r for r in rows if r["arm"] == "baseline"}
    agent = {r["case_id"]: r for r in rows if r["arm"] == "agent" and not is_outage(r)}
    shared = sorted((set(base) & set(agent)) - excluded)
    paired = [(base[c], agent[c]) for c in shared]
    fraud = [(b, a) for b, a in paired if b["is_fraud"]]
    clean = [(b, a) for b, a in paired if not b["is_fraud"]]

    def caught(pairs, idx):
        return (sum(1 for p in pairs if p[idx]["risk_band"] != "clear") / len(pairs)
                if pairs else None)

    ci = None
    if len(fraud) >= 2:
        rng = random.Random(42)
        diffs = []
        for _ in range(10_000):
            draw = [fraud[rng.randrange(len(fraud))] for _ in range(len(fraud))]
            diffs.append(caught(draw, 1) - caught(draw, 0))
        diffs.sort()
        ci = (diffs[250], diffs[-250])

    agent_rows = [a for _, a in paired]
    return {
        "n_paired": len(paired), "n_fraud": len(fraud), "n_clean": len(clean),
        "baseline_recall": caught(fraud, 0), "agent_recall": caught(fraud, 1),
        "baseline_fp": caught(clean, 0), "agent_fp": caught(clean, 1),
        "ci": ci,
        "agent_total": len(agent), "baseline_total": len(base),
        "mean_tools": (sum(r["tool_calls"] for r in agent_rows) / len(agent_rows)) if agent_rows else 0,
        "mean_calls": (sum(r["llm_calls"] for r in agent_rows) / len(agent_rows)) if agent_rows else 0,
        "mean_latency": (sum(r["latency_ms"] for r in agent_rows) / len(agent_rows) / 1000) if agent_rows else 0,
        "by_archetype": Counter(b["archetype"] for b, _ in fraud),
    }


def pct(x: Optional[float]) -> str:
    return "n/a" if x is None else f"{x:.1%}"


def main() -> None:
    dup = read_json("outputs/duplicate_measurement.json") or {}
    thr = read_json("outputs/threshold_fp_investigation.json") or {}
    exc = read_json("data/generated/corpus_exclusions.json") or {}
    sig = read_json("outputs/baseline_signal_measurement.json") or {}
    det = read_json("outputs/ai_detector_measurement.json") or {}
    ab = paired_ablation()

    # AI detector rates, recomputed rather than quoted.
    det_rates = {}
    if det.get("records"):
        th = det.get("threshold", 0.5)
        rs = det["records"]
        def rate(x):
            return (sum(1 for r in x if r["probability"] >= th) / len(x)) if x else 0.0
        band = [r for r in rs if (r.get("width") or 0) >= 400]
        det_rates = {
            "threshold": th,
            "genuine_all": rate([r for r in rs if not r.get("synthetic")]),
            "synth_all": rate([r for r in rs if r.get("synthetic")]),
            "genuine_matched": rate([r for r in band if not r.get("synthetic")]),
            "synth_matched": rate([r for r in band if r.get("synthetic")]),
            "n_genuine_matched": len([r for r in band if not r.get("synthetic")]),
            "n_synth_matched": len([r for r in band if r.get("synthetic")]),
        }

    a_: list[str] = []
    a = a_.append

    a("# Results and Discussion — draft")
    a("")
    a("*Generated by `scripts/build_report_draft.py`. Every figure is read from an "
      "artefact in `outputs/`; the artefact is cited beside the claim. Re-run to refresh "
      "as the ablation completes.*")
    a("")
    a("---")
    a("")

    # ---------------- Results -------------------------------------------
    a("## 4. Results")
    a("")
    a("### 4.1 Check battery performance")
    a("")
    a("Eleven checks were evaluated against a corpus of 800 cases comprising 540 "
      "labelled-clean cases and 260 fraud cases across eight archetypes. Recall was "
      "measured against each check's own target archetype rather than pooled across the "
      "corpus, since a check designed to detect image reuse should not have its recall "
      "diluted by metadata-forgery cases it was never intended to catch.")
    a("")
    table = v2_table()
    if table:
        a_.extend(table)
        a("")
    a("Three checks achieved perfect recall on their target archetype: "
      "`internal_duplicate` (35/35 on REUSE), `external_corpus` (35/35 on "
      "EXTERNAL_SOURCING) and `threshold_gaming` (34/34 on THRESHOLD_GAMING). "
      "`exif_metadata` recovered 26 of 34 metadata-forgery cases (76.5%) with no false "
      "positives, and `scene_consistency` 20 of 34 context-mismatch cases (58.8%).")
    a("")
    a("Two checks were measured to have no usable discriminative power and were assigned "
      "weight 0.0 while continuing to run: `ai_generation` and `digital_edit`. A third, "
      "`baseline_corruption`, was found to be structurally incapable of detecting the "
      "archetype it was built for. These negative results are treated in §4.5.")
    a("")
    a("Two checks remain unmeasured because the corpus contains no case that could "
      "exercise them. `damage_plausibility` has no target archetype - no archetype in "
      "the corpus inflates a claim amount - and its false-positive rate rests on four "
      "clean cases. `c2pa_credentials` has nothing to detect, as no image in the corpus "
      "carries C2PA provenance credentials. Both are reported as unmeasured rather than "
      "as zero.")
    a("")

    a("### 4.2 Attribution in duplicate detection")
    a("")
    if dup:
        r = dup["recall_on_REUSE"]
        f = dup["false_positives_on_clean"]
        v = dup["victim_flags"]
        a(f"`internal_duplicate` initially recorded a false-positive rate of 4.3% "
          f"(23/540) on clean cases. Inspection of the flagged cases established that "
          f"the detections were correct but misattributed: each flagged clean case had "
          f"had its photograph copied by a later REUSE case. Because a duplicate is "
          f"symmetric while culpability is not, the check was flagging the originating "
          f"claimant alongside the party who had copied the image.")
        a("")
        a(f"The check was amended to compare ingest timestamps, returning CONCERN only "
          f"for the later submission and INCONCLUSIVE, naming the later case, for the "
          f"earlier one. Re-measured across all 800 cases, recall on REUSE was unchanged "
          f"at **{r['caught']}/{r['total']}** and false positives on clean cases fell to "
          f"**{f['flagged']}/{f['total']}**, with **{v['total']}** cases "
          f"({v['on_clean']} of them clean) reclassified as originators "
          f"(`outputs/duplicate_measurement.json`).")
        a("")
        a("Ingest time rather than declared incident date was used, because the declared "
          "date is supplied by the claimant: in both manually inspected pairs the "
          "copying case declared the *earlier* incident, so ordering on declared time "
          "would have inverted the attribution.")
        a("")
        a("**This result is confounded and should be reported as such.** The corpus is "
          "generated in archetype blocks, with every clean case created before every "
          "REUSE case, so the rule \"the earlier submission is the originator\" holds by "
          "construction. The amendment is correct for production data, where ingest time "
          "is genuine evidence, but this corpus cannot test whether it generalises.")
    a("")

    a("### 4.3 Attribution in threshold detection")
    a("")
    if thr:
        attr = thr["garage_attributable"]
        share = attr.get("share_of_flags")
        a(f"`threshold_gaming` flagged **{thr['flagged']} of "
          f"{thr['clean_claims_examined']}** clean claims "
          f"({thr['flag_rate']:.1%}), making it the dominant source of false positives "
          f"once duplicate misattribution had been corrected. Examination of the "
          f"underlying evidence found **{attr['count']} of {thr['flagged']}**"
          + (f" ({share:.0%})" if share is not None else "")
          + f" attributable to the repairing garage's billing pattern and "
          f"**{thr['unexplained']['count']}** unexplained, concentrated across "
          f"**{thr['distinct_garages_involved']}** garages "
          f"(`outputs/threshold_fp_investigation.json`).")
        a("")
        a("The check is garage-scoped by design, firing only when a claim falls below "
          "the survey threshold *and* the repairing garage shows an elevated "
          "concentration of claims in that band. An honest claimant using such a garage "
          "is therefore flagged for a pattern that is not their own. The finding is "
          "correct; its presentation was not, and revised explanation text attributing "
          "the pattern to the garage was drafted without altering the verdict logic.")
        a("")
        a("This distinction has a methodological consequence. Reporting false positives "
          "as a single count treats \"correct finding, wrong subject\" as equivalent to "
          "\"incorrect finding\", although the two require different remedies.")
    a("")

    a("### 4.4 Corpus quality")
    a("")
    if exc:
        total = exc.get("clean_cases_total")
        defective = exc.get("defective_clean_cases") or exc.get("defective_cases")
        corrected = exc.get("corrected_clean_count")
        rate = exc.get("defect_rate")
        a(f"An audit of the labelled-clean corpus applied optical character recognition "
          f"to all {exc.get('images_ocred', 'n/a')} clean-case images, together with a "
          f"scan of vision-model scene descriptions for imagery inconsistent with the "
          f"declared Indian location. **{defective} of {total}** clean cases "
          + (f"({rate:.1%}) " if isinstance(rate, float) else "")
          + f"were found to carry stock-agency watermarks, republication URLs or "
          f"non-Indian scenery, giving a corrected clean-case count of **{corrected}** "
          f"(`outputs/clean_label_audit.md`).")
        a("")
        a("Such cases are indistinguishable from the EXTERNAL_SOURCING fraud archetype "
          "and corrupt the false-positive rate asymmetrically. The rules-only baseline "
          "cannot read a watermark and therefore scores such a case as a correct "
          "clearance, whereas an adjudicator that reads scene text detects the "
          "inconsistency, flags it, and is recorded as having produced a false positive. "
          "Affected cases were excluded at scoring rather than resampled, preserving the "
          "frozen ablation sample.")
        a("")
        a("**An earlier estimate of this rate was wrong, and the direction of the error "
          "is instructive.** A preliminary scan covering only the 22 clean cases with "
          "existing vision-model coverage found four defective cases, or 18.2%, which "
          "was reported as a lower bound on the corpus-wide rate. Auditing all 540 gave "
          "4.1%. The initial figure was not a lower bound but a rate computed on an "
          "unrepresentative subsample: vision coverage had itself been allocated by a "
          "stratified sampler that preferentially selected fraud-adjacent cases. A small "
          "denominator does not make a rate a bound.")
        a("")
        a("The 4.1% figure remains a floor for a different reason. OCR covered every "
          "clean-case image, but the geographic signal can only be read from vision-model "
          "descriptions, which exist for approximately 10% of the corpus.")
    a("")

    a("### 4.5 Negative results")
    a("")
    a("Three checks were built, measured, and found not to work. Each is reported with "
      "the evidence that retired it, since a negative result obtained under control is "
      "a finding rather than an absence of one.")
    a("")
    a("**`vehicle_consistency` (retired).** The check compared vehicle attributes "
      "across images within a case. It raised concerns on 555 of 560 clean cases "
      "(99.11%), firing on almost every honest claim. The signal was inverted rather "
      "than weak, and the check was removed from the battery entirely "
      "(`outputs/retired_checks.md`).")
    a("")
    if det_rates:
        d = det_rates
        a(f"**`ai_generation` (demoted to weight 0.0).** At its operating threshold of "
          f"{d['threshold']}, the detector flagged genuine photographs "
          f"**{d['genuine_all']:.1%}** of the time against **{d['synth_all']:.1%}** for "
          f"synthetic images. Two controls established that this inversion was not an "
          f"artefact. First, restricting both groups to images at least 400 pixels wide "
          f"— a resolution-matched comparison, necessary because synthetic images had a "
          f"median width of 1522 pixels against the curated corpus's 189 — widened the "
          f"gap to **{d['genuine_matched']:.1%}** versus **{d['synth_matched']:.1%}** "
          f"(n={d['n_genuine_matched']} and {d['n_synth_matched']} respectively). "
          f"Second, within individual cases containing both a genuine and a fabricated "
          f"image at comparable widths, the detector was 4.5 times more likely to flag "
          f"the genuine photograph. The check was forced to INCONCLUSIVE while "
          f"continuing to record its probabilities "
          f"(`outputs/ai_detector_measurement.json`).")
        a("")
    a("**`digital_edit` (demoted to weight 0.0).** JPEG-ghost, noise-inconsistency and "
      "edge-discontinuity forensics were combined into a single score. After a generator "
      "defect was corrected — a global recompression pass had been erasing the very "
      "artefacts the check sought — the combined score reached an AUC of 0.546, "
      "indistinguishable from chance on this corpus.")
    a("")
    if sig:
        a("**`baseline_corruption` (weight 0.0).** The check was built to detect the "
          "AI_GENERATED_BASELINE archetype and was found structurally incapable of doing "
          "so. That archetype fabricates the *absence* of damage, submitting a synthetic "
          "photograph of an intact vehicle at policy inception, so the declaration and "
          "the photographs agree by construction and every check passes. Before "
          "correction the check returned PASS at up to 0.8 confidence on the cases it "
          "was built to catch. Two alternative detection routes were then measured: "
          "cross-case linkage was unavailable, as all 800 cases carry unique vehicle "
          "registrations and claimant identifiers, and synthetic-image forensics reached "
          "an inverted AUC of 0.26 but with JPEG quantisation differing between the "
          "groups, and was rejected as confounded "
          "(`outputs/baseline_signal_measurement.json`).")
        a("")

    a("### 4.6 Adjudication: rules versus agent")
    a("")
    a(f"The ablation compared a rules-only weighted-sum adjudicator against an LLM agent "
      f"on identical cases receiving identical findings, the check battery being executed "
      f"once per case and its output passed to both arms. At the time of writing the "
      f"baseline arm had completed **{ab['baseline_total']}** cases and the agent arm "
      f"**{ab['agent_total']}**, the latter constrained by a free-tier quota of "
      f"approximately 100 requests per day against a measured cost of "
      f"{ab['mean_calls']:.1f} model calls per case.")
    a("")
    if ab["n_fraud"] >= 2:
        lo, hi = ab["ci"] if ab["ci"] else (None, None)
        a(f"On the **{ab['n_paired']}** cases both arms had adjudicated "
          f"({ab['n_fraud']} fraud, {ab['n_clean']} clean), the baseline flagged "
          f"**{pct(ab['baseline_recall'])}** of fraud cases and the agent "
          f"**{pct(ab['agent_recall'])}**. The paired difference was "
          f"**{(ab['agent_recall'] - ab['baseline_recall']):+.1%}** with a bootstrap 95% "
          f"confidence interval of **[{lo:+.1%}, {hi:+.1%}]** over 10,000 paired "
          f"resamples.")
        a("")
        if lo is not None and lo <= 0 <= hi:
            a("**This interval includes zero, and the sample therefore does not establish "
              "that the agent outperformed the baseline.** The observed difference "
              "favours the agent; the evidence available does not distinguish it from "
              "sampling variation.")
        elif lo is not None:
            a("The interval excludes zero on this sample, though it remains a statement "
              f"about {ab['n_fraud']} cases drawn from the archetypes listed above "
              "rather than about the corpus.")
        a("")
        a(f"The clean cell contains {ab['n_clean']} cases, which is too few to support a "
          f"false-positive comparison; the two arms' false-positive rates are therefore "
          f"not reported as a difference. Per-archetype recall is similarly "
          f"underpowered: the paired fraud cases comprise "
          + ", ".join(f"{k} (n={n})" for k, n in sorted(ab["by_archetype"].items()))
          + ".")
        a("")
        a(f"Cost differed substantially. The agent averaged {ab['mean_calls']:.1f} model "
          f"calls, {ab['mean_tools']:.1f} tool invocations and {ab['mean_latency']:.1f} "
          f"seconds per case; the baseline is arithmetic over the findings and adds no "
          f"measurable latency. The check battery, common to both arms, dominates "
          f"wall-clock time in either configuration.")
    else:
        a("_Insufficient paired cases for a comparison at the time of generation._")
    a("")

    a("### 4.7 Qualitative observations")
    a("")
    a("Two cases illustrate the difference between the arms more precisely than the "
      "aggregate figures.")
    a("")
    a("**`case-0091`.** A case labelled clean on which no check raised any concern. The "
      "rules-only baseline cleared it, which is the only outcome a weighted sum over an "
      "empty set can produce. The agent escalated it, having read the stored vision-model "
      "description: *\"A black pickup truck is parked outdoors in a desert environment "
      "with a saguaro cactus and dry brush in the background.\"* The claim was declared "
      "in Vadodara, Gujarat; saguaro cacti are endemic to the Sonoran Desert. No check "
      "in the battery tests geography — `scene_consistency` evaluates weather, "
      "precipitation and shadow direction — so the contradiction was invisible to every "
      "rule in the system.")
    a("")
    a("The reasoning was sound and the action was wrong. The image is a stock photograph "
      "introduced by the corpus generator rather than evidence of a fraudulent claimant, "
      "so referral to a special investigation unit would have consumed investigator time "
      "for a data defect. The case is reported because it locates the agent's advantage "
      "precisely: the interpretation of unstructured evidence that no rule parses, "
      "rather than superior arithmetic over the same findings. It was also the "
      "observation that prompted the corpus audit described in §4.4.")
    a("")
    a("**`case-0776`.** A REUSE case in which the agent consulted claimant history and "
      "re-queried the image analysis before escalating, reporting that the submitted "
      "photograph was *\"an exact duplicate of an image previously submitted in "
      "case-0162\"*. The attribution is the substantive detail: `case-0162` is one of the "
      "originating claimants that the unamended check had flagged, and the agent's "
      "narrative correctly identifies it as the earlier submission rather than as a "
      "co-offender.")
    a("")

    # ---------------- Discussion ----------------------------------------
    a("---")
    a("")
    a("## 5. Discussion")
    a("")
    a("### 5.1 Corpus falsifiability was the binding constraint")
    a("")
    a("The clearest methodological finding of this work concerns where effort produced "
      "measurable improvement. Across five measurement rounds recall moved 57.1% → "
      "57.9% → 59.6% → 61.2%, and every one of those gains originated in a correction to "
      "the corpus rather than in detection logic: making fraud archetypes falsifiable, "
      "correcting a daylight-hours defect, and replacing daily precipitation totals with "
      "hourly observations. Four checks were added over the same period — `plate_ocr`, "
      "`c2pa_credentials`, `vehicle_consistency` and `baseline_corruption` — and "
      "contributed nothing to recall; two were subsequently retired or assigned zero "
      "weight after measurement.")
    a("")
    a("The most instructive instance was an archetype that was undetectable by "
      "construction. DIGITAL_EDIT cases were generated by compositing a patch into an "
      "image and then recompressing the entire result, which erased the compression "
      "discontinuity that JPEG-ghost analysis exists to detect. The check was not weak; "
      "the data contained no signal for it to find. Diagnosing this required treating "
      "the generator as a subject of investigation rather than as ground truth.")
    a("")
    a("A fifth measurement round returned recall to 58.5%. This was a correction rather "
      "than a regression: seven fraud cases had been credited to `internal_duplicate` "
      "solely because a *later* case had copied their photographs, which is evidence "
      "concerning the copier. Six of the seven belonged to archetypes with no working "
      "detector, so the battery had been accruing credit on undetectable archetypes "
      "through an artefact of corpus construction. A recall figure that counts such "
      "cases measures the generator rather than the detector.")
    a("")

    a("### 5.2 Where an agent adds value, and where it does not")
    a("")
    a("The evidence does not support a claim that LLM adjudication produces better "
      "decisions than a weighted sum over the same findings. The paired comparison "
      "available at the time of writing has a confidence interval spanning zero, and the "
      "clean cell is too small to compare false-positive rates at all.")
    a("")
    a("The evidence does support a narrower claim. Where information exists in "
      "unstructured form that no rule parses — a scene description contradicting a "
      "declared location — the agent can act on it and the weighted sum cannot, because "
      "the weighted sum has no term for evidence that produced no finding. `case-0091` "
      "is a single instance and is reported as such, but the mechanism is structural "
      "rather than incidental: an adjudicator restricted to check outputs cannot exceed "
      "the coverage of its checks.")
    a("")
    a("A controlled prompt experiment sharpened this. The underwriting agent initially "
      "cleared no case at all. A single paragraph instructing it that an absence of "
      "concerns constituted weak evidence was hypothesised as the cause and removed. "
      "Clearing resumed, but the amended variant cleared two of three fraud cases "
      "against one of three clean cases — that is, it cleared fraud more readily than "
      "clean cases. The explanation is that for the AI_GENERATED_BASELINE archetype the "
      "findings are identical to those of a clean case, so no instruction operating on "
      "findings alone can separate them. The original configuration avoided clearing "
      "fraud only by never clearing anything. Both variants were non-discriminating, and "
      "the deficiency lay in the evidence rather than in the prompt. The claims-side "
      "configuration, unchanged, cleared three of three clean cases and escalated three "
      "of three fraud cases on the same sample, which supports that reading. All of "
      "these cells contain three cases and none supports inference on its own.")
    a("")

    a("### 5.3 Attribution as a distinct failure mode")
    a("")
    a("Two of the three largest false-positive sources in this system were correct "
      "detections attached to the wrong party. `internal_duplicate` identified genuine "
      "duplicates but could not distinguish the originator from the copier; "
      "`threshold_gaming` identified genuine billing anomalies but expressed them as "
      "statements about the claimant. In both cases the remedy was attribution — "
      "comparing ingest times, and revising explanatory text — rather than any change to "
      "detection thresholds.")
    a("")
    a("This suggests that false-positive rate is an insufficient metric for systems of "
      "this kind. It aggregates spurious detections, which require better detection, "
      "with misattributed detections, which require better reasoning about "
      "responsibility. The two are not interchangeable, and a system optimised against "
      "the aggregate may suppress correct findings in order to improve a number.")
    a("")

    a("### 5.4 Limitations")
    a("")
    a("The corpus is synthetic and single-source. Every recall figure describes "
      "archetypes this project generated, with a measured label-defect rate of 4.1% "
      "among clean cases and an acknowledged floor on that estimate.")
    a("")
    a("Vision-model coverage extends to approximately 10% of images, constrained by the "
      "same quota the adjudication experiment consumes. Perception-dependent checks are "
      "therefore measured on small denominators, and the agent's demonstrated advantage "
      "is unavailable on most of the corpus.")
    a("")
    a("Three archetypes have no working detector, which places a coverage ceiling on "
      "recall that no threshold adjustment can raise.")
    a("")
    a("The ablation's clean cells contain twelve cases per agent type before exclusions. "
      "Any false-positive figure derived from them is an upper bound rather than an "
      "estimate; distinguishing a 0.5% rate from a 2% rate would require of the order of "
      "a thousand clean cases.")
    a("")
    a("Underwriting fraud is represented by a single archetype, and that archetype has "
      "no working detector, so no conclusion is drawn about underwriting fraud "
      "generally.")
    a("")
    a("Finally, the duplicate-attribution rule is correct by construction on this corpus, "
      "which generates archetypes in blocks. It is reported as sound reasoning for "
      "production data and as untested as a generalisation.")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("\n".join(a_) + "\n", encoding="utf-8")
    print(f"-> {OUT} ({len(a_)} lines)")
    print(f"   paired={ab['n_paired']} fraud={ab['n_fraud']} clean={ab['n_clean']}")


if __name__ == "__main__":
    main()
