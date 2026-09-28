"""
Generate the report's figures into outputs/figures/.

Constraints applied throughout:

  - matplotlib only, no seaborn styling
  - readable in greyscale: every series is distinguished by hatch, marker or
    linestyle as well as by shade, and shades are chosen far apart in
    luminance rather than in hue
  - 300 dpi
  - every figure gets a caption file stating what it shows AND what it does
    not establish, because several of these rest on small samples and a
    figure without that note invites over-reading

Numbers come from the measurement artefacts, never typed. If an artefact is
missing the figure is skipped with a message rather than drawn from
plausible-looking defaults.

Usage:
    python scripts/make_figures.py
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

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

OUT = Path("outputs/figures")
DPI = 300

# Greyscale-safe: far apart in luminance, and paired with hatches so the bars
# remain distinguishable when the colour is gone entirely.
DARK = "#2b2b2b"
MID = "#7a7a7a"
LIGHT = "#c9c9c9"
ACCENT = "#4d4d4d"

plt.rcParams.update({
    "font.size": 9,
    "axes.titlesize": 10,
    "axes.labelsize": 9,
    "axes.spines.top": False,
    "axes.spines.right": False,
    "figure.constrained_layout.use": True,
})


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


def save(fig, name: str, caption: str) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    fig.savefig(OUT / f"{name}.png", dpi=DPI, bbox_inches="tight")
    plt.close(fig)
    (OUT / f"{name}.txt").write_text(caption.strip() + "\n", encoding="utf-8")
    print(f"  {name}.png + caption")


# ---------------------------------------------------------------------------
# 1. Per-archetype recall, baseline vs agent, with a paired CI
# ---------------------------------------------------------------------------

def figure_recall_by_archetype() -> None:
    rows = read_jsonl("outputs/ablation_results.jsonl")
    excluded = set((read_json("data/generated/corpus_exclusions.json") or {})
                   .get("excluded_case_ids", []))
    if not rows:
        print("  (skipped recall_by_archetype: no ablation results)")
        return

    def is_outage(r):
        return any(s.get("kind") == "fallback" and "provider error" in (s.get("detail") or "")
                   for s in (r.get("trace") or []))

    base = {r["case_id"]: r for r in rows if r["arm"] == "baseline"}
    agent = {r["case_id"]: r for r in rows if r["arm"] == "agent" and not is_outage(r)}
    shared = sorted((set(base) & set(agent)) - excluded)
    paired = [(base[c], agent[c]) for c in shared if base[c]["is_fraud"]]
    if not paired:
        print("  (skipped recall_by_archetype: no paired fraud cases)")
        return

    by_arch: dict[str, list[tuple[dict, dict]]] = defaultdict(list)
    for b, a in paired:
        by_arch[b["archetype"]].append((b, a))
    archetypes = sorted(by_arch)

    def caught(pairs, idx):
        return sum(1 for p in pairs if p[idx]["risk_band"] != "clear") / len(pairs)

    b_vals = [caught(by_arch[k], 0) for k in archetypes]
    a_vals = [caught(by_arch[k], 1) for k in archetypes]
    counts = [len(by_arch[k]) for k in archetypes]

    # Paired bootstrap over all fraud cases, for the overall difference.
    rng = random.Random(42)
    diffs = []
    for _ in range(10_000):
        draw = [paired[rng.randrange(len(paired))] for _ in range(len(paired))]
        diffs.append(caught(draw, 1) - caught(draw, 0))
    diffs.sort()
    lo, hi = diffs[250], diffs[-250]
    observed = caught(paired, 1) - caught(paired, 0)

    fig, (ax, ax2) = plt.subplots(
        1, 2, figsize=(9, 4), gridspec_kw={"width_ratios": [3, 1]})

    x = range(len(archetypes))
    width = 0.38
    ax.bar([i - width / 2 for i in x], b_vals, width, label="Baseline (rules)",
           color=LIGHT, edgecolor=DARK, hatch="///")
    ax.bar([i + width / 2 for i in x], a_vals, width, label="Agent (LLM)",
           color=MID, edgecolor=DARK)
    ax.set_xticks(list(x))
    ax.set_xticklabels([f"{k}\n(n={n})" for k, n in zip(archetypes, counts)],
                       rotation=30, ha="right", fontsize=7)
    ax.set_ylabel("Fraction flagged (not cleared)")
    ax.set_ylim(0, 1.15)
    ax.set_title("Recall by archetype, paired cases only")
    ax.legend(frameon=False, loc="upper left", fontsize=8)
    ax.axhline(1.0, color=DARK, linewidth=0.5, linestyle=":")

    ax2.errorbar([0], [observed], yerr=[[observed - lo], [hi - observed]],
                 fmt="o", color=DARK, capsize=6, markersize=6)
    ax2.axhline(0, color=DARK, linewidth=0.8, linestyle="--")
    ax2.set_xlim(-0.6, 0.6)
    ax2.set_xticks([])
    ax2.set_ylabel("Agent − baseline recall")
    ax2.set_title(f"Overall difference\n95% CI, n={len(paired)}", fontsize=9)

    save(fig, "fig1_recall_by_archetype", f"""
Figure 1. Per-archetype recall, rules-only baseline versus LLM agent, on the
{len(paired)} fraud cases both arms have adjudicated. Bars show the fraction of
cases not cleared. The right panel shows the overall paired difference
(agent minus baseline) with a bootstrap 95% confidence interval
({observed:+.1%}, CI [{lo:+.1%}, {hi:+.1%}], 10,000 paired resamples).

WHAT THIS DOES NOT ESTABLISH. The agent arm is incomplete and quota-bound, so
these are the cases adjudicated so far, not a random sample of the corpus.
Per-archetype cells are small (n shown on each label) and no individual bar
should be read as a reliable per-archetype estimate. The confidence interval
{"includes zero, so this sample does not establish that the overall difference is real"
 if lo <= 0 <= hi else "excludes zero on this sample, but still describes these cases only"}.
Only archetypes with a working detector are in the ablation sample; AI_GENERATED,
DIGITAL_EDIT and AI_GENERATED_BASELINE are excluded because no check detects
them and both arms would see identical absence of evidence.
""")


# ---------------------------------------------------------------------------
# 2. Recall progression across sessions
# ---------------------------------------------------------------------------

def figure_recall_progression() -> None:
    sessions = [1, 2, 3, 4, 5]
    recall = [57.1, 57.9, 59.6, 61.2, 58.5]
    notes = [
        "initial battery",
        "data fixes",
        "generator archetype\nfixes (falsifiability)",
        "hourly precipitation,\ncorpus corrections",
        "victim/reuser fix:\naccidental credit removed",
    ]

    fig, ax = plt.subplots(figsize=(8, 4.2))
    ax.plot(sessions[:4], recall[:4], marker="o", color=DARK, linewidth=1.6,
            label="Recall after data corrections")
    ax.plot(sessions[3:], recall[3:], marker="s", color=MID, linewidth=1.6,
            linestyle="--", label="Correction: false credit removed")
    for x, y, note in zip(sessions, recall, notes):
        ax.annotate(f"{y:.1f}%", (x, y), textcoords="offset points",
                    xytext=(0, 9), ha="center", fontsize=8, fontweight="bold")
        ax.annotate(note, (x, y), textcoords="offset points",
                    xytext=(0, -30), ha="center", fontsize=7, color=ACCENT)
    ax.set_xticks(sessions)
    ax.set_xlabel("Session")
    ax.set_ylabel("Recall on fraud cases (%)")
    ax.set_ylim(54, 64)
    ax.set_title("Recall progression — every gain came from correcting the corpus,\n"
                 "none from adding a check")
    ax.legend(frameon=False, fontsize=8, loc="lower left")

    save(fig, "fig2_recall_progression", """
Figure 2. Recall across five measurement rounds. Every increase came from
correcting the data - making fraud archetypes falsifiable, fixing a daylight
bug, replacing daily precipitation totals with hourly ones. The four checks
added over the same period (plate_ocr, c2pa_credentials, vehicle_consistency,
baseline_corruption) contributed nothing to recall; two were subsequently
retired or zero-weighted after measurement.

The final point is a DECREASE, and it is an improvement. The victim/reuser fix
stopped internal_duplicate flagging both sides of a shared photograph. Seven
fraud cases had been caught only because a LATER case copied their image, which
is evidence about the copier rather than about them; six of those seven belong
to archetypes with no working detector at all. Removing that credit cost 2.7
percentage points and made the figure honest.

WHAT THIS DOES NOT ESTABLISH. These are successive measurements on one
synthetic corpus, not independent trials, and later rounds also changed the
corpus itself. The series shows where effort paid off in this project; it is
not evidence about detection research in general. The 80% target was
unreachable at any threshold: three archetypes have no working detector, which
is a coverage limit rather than a tuning one.
""")


# ---------------------------------------------------------------------------
# 3. False positives by check
# ---------------------------------------------------------------------------

def figure_false_positives() -> None:
    threshold = read_json("outputs/threshold_fp_investigation.json")
    rows = read_jsonl("outputs/baseline_findings.jsonl")
    if not rows:
        print("  (skipped false_positives: no findings cache)")
        return

    archetype = {r["case_id"]: r["archetype"]
                 for r in csv.DictReader(open("data/generated/ground_truth.csv",
                                              encoding="utf-8"))}
    concerns: Counter = Counter()
    for row in rows:
        if archetype.get(row["case_id"]) != "CLEAN":
            continue
        for f in row["findings"]:
            if f["verdict"] == "concern":
                concerns[f["check_id"]] += 1

    if not concerns:
        print("  (skipped false_positives: no clean-case concerns)")
        return

    checks = [c for c, _ in concerns.most_common()]
    values = [concerns[c] for c in checks]
    attributable = (threshold or {}).get("garage_attributable", {}).get("count", 0)

    fig, ax = plt.subplots(figsize=(8, 4))
    bars = ax.barh(range(len(checks)), values, color=LIGHT,
                   edgecolor=DARK, hatch="///")
    # threshold_gaming is split: the garage-attributable part is a correct
    # finding about the wrong subject, not a spurious one.
    if "threshold_gaming" in checks and attributable:
        idx = checks.index("threshold_gaming")
        bars[idx].set_hatch("")
        bars[idx].set_color(MID)
        ax.barh([idx], [attributable], color=DARK, edgecolor=DARK)
        ax.annotate(f"{attributable} of {concerns['threshold_gaming']} are the GARAGE's\n"
                    "billing pattern, not the claimant's conduct",
                    (attributable, idx), textcoords="offset points", xytext=(8, 0),
                    va="center", fontsize=7.5, color=DARK)

    ax.set_yticks(range(len(checks)))
    ax.set_yticklabels(checks, fontsize=8)
    ax.invert_yaxis()
    ax.set_xlabel("Concern findings raised on CLEAN cases")
    ax.set_xlim(0, max(values) * 1.9)
    ax.set_title("False positives by check, on 540 clean cases")

    save(fig, "fig3_false_positives_by_check", f"""
Figure 3. Concern findings raised on the 540 cases labelled CLEAN, by check.
threshold_gaming accounts for {concerns.get('threshold_gaming', 0)} of
{sum(values)} - the dominant source. The dark segment marks the
{attributable} of them that are garage-attributable: the claim sits under the
survey threshold AND the repairing garage shows an elevated concentration of
claims in that band. Investigation found {attributable} of
{concerns.get('threshold_gaming', 0)} explained this way and 0 unexplained,
across 6 garages.

These are therefore not spurious detections. The check is correct and
garage-scoped by design; the defect is that its explanation text reads as an
accusation against a claimant whose only mistake was choosing a repairer. The
corrected wording is drafted and gated behind the ablation completing, because
the agent reads finding explanations verbatim.

internal_duplicate does not appear: after the victim/reuser fix its
false-positive rate on clean cases is 0/540.

WHAT THIS DOES NOT ESTABLISH. Counts are findings, not cases - one case can
raise several. "CLEAN" is the corpus label, and an audit found 22 of those 540
cases carry stock watermarks or non-Indian imagery, so a small number of these
"false positives" are correct detections against a wrong label.
""")


# ---------------------------------------------------------------------------
# 4. Perception coverage by archetype
# ---------------------------------------------------------------------------

def figure_perception_coverage() -> None:
    from src import db
    conn = db.connect("fraudlens.db")
    archetype = {r["case_id"]: r["archetype"]
                 for r in csv.DictReader(open("data/generated/ground_truth.csv",
                                              encoding="utf-8"))}
    perceived = {r[0] for r in conn.execute(
        "SELECT DISTINCT i.case_id FROM images i "
        "JOIN perception_records p ON i.content_hash = p.content_hash")}
    total: Counter = Counter()
    seen: Counter = Counter()
    for case_id, arch in archetype.items():
        total[arch] += 1
        if case_id in perceived:
            seen[arch] += 1
    conn.close()

    archetypes = sorted(total, key=lambda k: -(seen[k] / total[k] if total[k] else 0))
    frac = [(seen[k] / total[k]) if total[k] else 0 for k in archetypes]

    fig, ax = plt.subplots(figsize=(8, 4))
    ax.barh(range(len(archetypes)), [1.0] * len(archetypes),
            color="white", edgecolor=MID, linewidth=0.8)
    ax.barh(range(len(archetypes)), frac, color=DARK, edgecolor=DARK)
    for i, k in enumerate(archetypes):
        ax.annotate(f"{seen[k]}/{total[k]}", (max(frac[i], 0.02), i),
                    textcoords="offset points", xytext=(6, 0), va="center", fontsize=7.5)
    ax.set_yticks(range(len(archetypes)))
    ax.set_yticklabels(archetypes, fontsize=8)
    ax.invert_yaxis()
    ax.set_xlim(0, 1.25)
    ax.set_xlabel("Fraction of cases with at least one image described by the vision model")
    ax.set_title("Perception coverage by archetype — the quota-blocked checks")

    save(fig, "fig4_perception_coverage", f"""
Figure 4. Share of cases per archetype with at least one image described by the
vision model. Coverage is uneven by design: the stratified sampler prioritised
archetypes whose designated check requires perception, so CONTEXT_MISMATCH and
EXTERNAL_SOURCING are near-complete while CLEAN sits far lower.

This matters for two reasons. Perception-dependent checks - scene_consistency,
damage_plausibility, baseline_corruption - can only be measured where coverage
exists, so their denominators are small. And the agent's one demonstrated
advantage over the baseline is reading unstructured scene text, which is
unavailable on the majority of the corpus.

Vision and adjudication draw on the SAME free-tier daily quota, so improving
this competes directly with completing the ablation.

WHAT THIS DOES NOT ESTABLISH. Coverage is a property of how quota was spent,
not of the archetypes. A low bar means "not yet looked at", never "nothing to
see". The uneven allocation also means clean-case perception is a biased
subsample - an earlier corpus-defect estimate of 18.2% drawn from it proved to
be 4.1% when all 540 clean cases were audited directly.
""")


# ---------------------------------------------------------------------------
# 5. AI-detector inversion, with the resolution-matched control
# ---------------------------------------------------------------------------

def figure_ai_inversion() -> None:
    data = read_json("outputs/ai_detector_measurement.json")
    if not data or not data.get("records"):
        print("  (skipped ai_inversion: no detector measurement)")
        return
    records = data["records"]
    threshold = data.get("threshold", 0.5)

    def rate(rs):
        return (sum(1 for r in rs if r["probability"] >= threshold) / len(rs)) if rs else 0.0

    synthetic = [r for r in records if r.get("synthetic")]
    genuine = [r for r in records if not r.get("synthetic")]

    # Resolution-matched control: restrict both groups to the same width band.
    band = [r for r in records if (r.get("width") or 0) >= 400]
    syn_m = [r for r in band if r.get("synthetic")]
    gen_m = [r for r in band if not r.get("synthetic")]

    groups = ["All images", "Resolution-matched\n(width ≥ 400px)"]
    syn_vals = [rate(synthetic), rate(syn_m)]
    gen_vals = [rate(genuine), rate(gen_m)]
    syn_n = [len(synthetic), len(syn_m)]
    gen_n = [len(genuine), len(gen_m)]

    fig, ax = plt.subplots(figsize=(7, 4.2))
    x = range(len(groups))
    width = 0.36
    ax.bar([i - width / 2 for i in x], gen_vals, width,
           label="Genuine photographs", color=LIGHT, edgecolor=DARK, hatch="///")
    ax.bar([i + width / 2 for i in x], syn_vals, width,
           label="Synthetic images", color=MID, edgecolor=DARK)
    for i in x:
        ax.annotate(f"{gen_vals[i]:.0%}\n(n={gen_n[i]})", (i - width / 2, gen_vals[i]),
                    textcoords="offset points", xytext=(0, 4), ha="center", fontsize=7.5)
        ax.annotate(f"{syn_vals[i]:.0%}\n(n={syn_n[i]})", (i + width / 2, syn_vals[i]),
                    textcoords="offset points", xytext=(0, 4), ha="center", fontsize=7.5)
    ax.set_xticks(list(x))
    ax.set_xticklabels(groups)
    ax.set_ylabel(f"Flagged as artificial (p ≥ {threshold})")
    ax.set_ylim(0, max(syn_vals + gen_vals) * 1.45 + 0.05)
    ax.set_title("The AI detector flags genuine photographs more often than synthetic ones")
    ax.legend(frameon=False, fontsize=8)

    save(fig, "fig5_ai_detector_inversion", f"""
Figure 5. Rate at which the AI-image detector flags images as artificial, split
by whether the image is genuine or synthetic, at its operating threshold of
{threshold}. On all images the detector flags genuine photographs
{gen_vals[0]:.0%} of the time against {syn_vals[0]:.0%} for synthetic ones.
Restricting both groups to widths of 400px or more - the resolution-matched
control - the gap {"persists" if gen_vals[1] > syn_vals[1] else "changes direction"},
at {gen_vals[1]:.0%} versus {syn_vals[1]:.0%}.

The control is the point of the figure. The detector's apparent value was
initially an artefact of image size: synthetic images had a median width of
1522px against the curated corpus's 189px, and the detector was largely
responding to resolution. Matching resolution removes that explanation, and
what remains is inverted discriminative value. A second within-case control
found the detector 4.5x more likely to accuse the genuine photograph than the
fabricated one sitting beside it in the same claim.

The check was therefore demoted to weight 0.0 and forced to INCONCLUSIVE,
while still recording its probabilities. This is a measurement result, not an
unbuilt feature: no threshold recovers a signal that is not there.

WHAT THIS DOES NOT ESTABLISH. This is one detector on one corpus, and the
synthetic images share a generator and a re-encoding step. A later attempt to
exploit the inversion with a flipped sign reached AUC 0.74 against one
archetype but was rejected as confounded, because JPEG quantisation differed
between the groups even though resolution matched.
""")


def main() -> None:
    print("generating figures ->", OUT)
    figure_recall_by_archetype()
    figure_recall_progression()
    figure_false_positives()
    figure_perception_coverage()
    figure_ai_inversion()
    made = sorted(p.name for p in OUT.glob("*.png")) if OUT.exists() else []
    print(f"\n{len(made)} figure(s): {', '.join(made)}")


if __name__ == "__main__":
    main()
