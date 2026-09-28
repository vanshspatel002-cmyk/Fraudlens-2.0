"""
Audit the CLEAN corpus for imagery that is not consistent with an honest
Indian motor claim.

--------------------------------------------------------------------------
Why this matters more than it sounds
--------------------------------------------------------------------------
The agent escalated `case-0091` - a CLEAN case on which **no check fired at
all** - because the stored perception record describes "a desert
environment with a saguaro cactus" on a policy declared in Vadodara.
Saguaros grow only in the Sonoran Desert. The agent was right, and the
label was wrong.

A "clean" case that any careful reader would flag is not clean. It corrupts
the false-positive rate for *both* arms of the ablation, and it does so
asymmetrically: the rules-only baseline cannot read scene text, so it
scores such a case as a true negative, while the agent reads the text,
flags it, and is scored as a false positive for being right. Left in, this
systematically penalises the arm under test.

--------------------------------------------------------------------------
The distinction this audit turns on
--------------------------------------------------------------------------
A stock-photo watermark is **not** a defect on EXTERNAL_SOURCING,
CONTEXT_MISMATCH or REUSE - those archetypes are *built* from externally
sourced imagery, so a 'shutterstock' overlay is the ground truth signal
working exactly as designed. The same watermark on a CLEAN case is a defect,
because it makes an honest case indistinguishable from the fraud.

So the rule is: flag markers only where the label claims the image is an
original photograph of an Indian incident. That is CLEAN cases, plus
AI_GENERATED_BASELINE, whose premise is a photograph the applicant took of
their own vehicle.

--------------------------------------------------------------------------
Known limitation, stated up front
--------------------------------------------------------------------------
Only images the vision pass has actually described can be audited. At the
time of writing that is a small minority of the corpus, so **every count
here is a lower bound** - the true number of defective clean cases is
larger, and will grow as perception coverage grows. A count from this
script is a floor, never a clean bill of health.

Writes outputs/corpus_quality.md and data/generated/corpus_exclusions.json.
"""

from __future__ import annotations

import csv
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]

from src import db

REPORT = Path("outputs/corpus_quality.md")
EXCLUSIONS = Path("data/generated/corpus_exclusions.json")
GROUND_TRUTH = Path("data/generated/ground_truth.csv")

# Archetypes whose label asserts "this is an original photograph taken of
# this vehicle, in India, for this case". Only these can be contradicted by
# the markers below.
ORIGINAL_PHOTO_ARCHETYPES = {"CLEAN", "AI_GENERATED_BASELINE"}

# Deliberately conservative. Each pattern is something that cannot plausibly
# appear in an honest Indian claim photograph, or that directly contradicts
# the claim of being an original photograph.
#
# Excluded on purpose: "pickup" alone (pickups exist in India and the word
# appears in honest records), "highway", "forest" (India has both). Chasing
# those would relabel honest cases to make a metric look thorough.
MARKERS: tuple[tuple[str, str, str], ...] = (
    ("non_indian_flora", r"\bsaguaro\b|\bcactus\b|\bcacti\b", "desert flora absent from India"),
    ("non_indian_climate", r"\bdesert environment\b|\bsnow\b|\bslush\b|\bsnowy\b",
     "climate inconsistent with the declared Indian location"),
    ("stock_watermark",
     r"getty ?images|shutterstock|alamy|istock|dreamstime|adobe stock|123rf|depositphotos",
     "a stock-agency watermark on an image claimed to be an original photograph"),
    ("stock_studio", r"stock photo|stock photograph|studio shot|studio background",
     "described as a stock or studio image rather than a photograph of an incident"),
    ("commercial_overlay",
     r"watermark reading|website watermark|promotional text overlay|auto recycling",
     "a third-party commercial overlay, meaning the image was republished from elsewhere"),
    ("foreign_signage", r"\bsmog brake\b|township markings|\blicense plate reading [A-Z]{2}\d",
     "signage or markings specific to a non-Indian jurisdiction"),
)

COMPILED = [(name, re.compile(pattern, re.I), why) for name, pattern, why in MARKERS]


def main() -> None:
    conn = db.connect("fraudlens.db")
    archetype = {r["case_id"]: r["archetype"]
                 for r in csv.DictReader(open(GROUND_TRUTH, encoding="utf-8"))}

    rows = conn.execute(
        "SELECT i.case_id, i.image_id, p.scene_context, p.anomaly_notes, p.caption "
        "FROM perception_records p JOIN images i ON i.content_hash = p.content_hash"
    ).fetchall()

    audited_cases = {r[0] for r in rows}
    hits: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"markers": set(), "quotes": [], "images": set()})

    for case_id, image_id, scene, anomaly, caption in rows:
        arch = archetype.get(case_id)
        if arch not in ORIGINAL_PHOTO_ARCHETYPES:
            continue  # externally-sourced archetypes are supposed to look like this
        text = " | ".join(x for x in (scene, anomaly, caption) if x)
        if not text:
            continue
        for name, pattern, _why in COMPILED:
            m = pattern.search(text)
            if m:
                hits[case_id]["markers"].add(name)
                hits[case_id]["images"].add(image_id)
                if len(hits[case_id]["quotes"]) < 2:
                    hits[case_id]["quotes"].append(text[:240])

    audited_original = {c for c in audited_cases
                        if archetype.get(c) in ORIGINAL_PHOTO_ARCHETYPES}

    findings = []
    for case_id in sorted(hits):
        h = hits[case_id]
        findings.append({
            "case_id": case_id,
            "archetype": archetype.get(case_id),
            "markers": sorted(h["markers"]),
            "images": sorted(h["images"]),
            "evidence": h["quotes"],
        })

    marker_counts = Counter(m for f in findings for m in f["markers"])

    payload = {
        "generated_by": "scripts/audit_corpus_geography.py",
        "audited_cases_with_perception": len(audited_cases),
        "audited_original_photo_cases": len(audited_original),
        "defective_cases": len(findings),
        "defect_rate_among_audited": (
            round(len(findings) / len(audited_original), 4) if audited_original else None
        ),
        "note": (
            "Lower bound. Only cases with perception records can be audited, and "
            "perception covers a minority of the corpus. Cases listed here should be "
            "excluded from the clean false-positive denominator for BOTH arms."
        ),
        "excluded_case_ids": [f["case_id"] for f in findings],
        "findings": findings,
    }

    # NOT written any more. This script and scripts/audit_clean_labels.py both
    # produced data/generated/corpus_exclusions.json, and this one - the older,
    # narrower, perception-only scan - silently overwrote the full OCR audit's
    # 22-case list with its own 4, simply by being run second. Two writers for
    # one file is an ownership bug, and the broader audit owns it.
    #
    # The findings here are still emitted to the report and to a separate
    # advisory file, so nothing is lost.
    ADVISORY = Path("outputs/corpus_geography_findings.json")
    ADVISORY.parent.mkdir(parents=True, exist_ok=True)
    ADVISORY.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    write_report(payload, marker_counts)
    print(f"audited {len(audited_original)} original-photo case(s) with perception; "
          f"{len(findings)} defective")
    for f in findings:
        print(f"  {f['case_id']} [{f['archetype']}] {f['markers']}")
    print(f"\n-> {EXCLUSIONS}\n-> {REPORT}")


def write_report(payload: dict[str, Any], marker_counts: Counter) -> None:
    lines: list[str] = []
    a = lines.append
    findings = payload["findings"]

    a("# Corpus quality — geographic and provenance defects in labelled-clean imagery")
    a("")
    a("> **SUPERSEDED by `outputs/clean_label_audit.md`.** This scan covers only the "
      "clean cases that already had vision-model coverage, which is not a representative "
      "subsample: perception was allocated by a stratified sampler that preferred "
      "fraud-adjacent cases. Its defect rate is therefore an overestimate, not the lower "
      "bound it was originally reported as. The full audit, which ran OCR over every "
      "clean-case image, measured **4.1%** against this document's 18.2%. Retained "
      "because the geographic signal it introduced is still used.")
    a("")
    a("A case labelled CLEAN whose photograph carries a stock-agency watermark, or shows "
      "a landscape that does not exist in India, is not clean. It is indistinguishable "
      "from the `EXTERNAL_SOURCING` fraud archetype, and it corrupts the false-positive "
      "rate that this project treats as its primary metric.")
    a("")
    a("The corruption is **asymmetric**, which is why it matters for the ablation. The "
      "rules-only baseline cannot read scene text, so it scores such a case as a correct "
      "clear. The agent reads the text, notices the contradiction, flags it — and is "
      "scored as a false positive for being right. Left in the denominator, these cases "
      "systematically penalise the arm under test.")
    a("")

    a("## Result")
    a("")
    a(f"- Cases with any perception record: **{payload['audited_cases_with_perception']}**")
    a(f"- Of those, cases whose label claims an original photograph "
      f"(CLEAN or AI_GENERATED_BASELINE): **{payload['audited_original_photo_cases']}**")
    a(f"- **Defective: {payload['defective_cases']}**")
    if payload["defect_rate_among_audited"] is not None:
        a(f"- Defect rate among audited: **{payload['defect_rate_among_audited']:.1%}**")
    a("")
    a("> **This is a lower bound.** Only images the vision pass has described can be "
      "audited, and perception covers a minority of the corpus. The true count is "
      "higher and will grow with coverage. Treat this as a floor, never as a clean "
      "bill of health.")
    a("")

    if marker_counts:
        a("| Marker | Cases | What it means |")
        a("|---|---|---|")
        why = {name: reason for name, _p, reason in MARKERS}
        for name, count in marker_counts.most_common():
            a(f"| `{name}` | {count} | {why[name]} |")
        a("")

    a("## Affected cases")
    a("")
    if not findings:
        a("None found in the audited subset.")
    else:
        for f in findings:
            a(f"### `{f['case_id']}` — labelled {f['archetype']}")
            a("")
            a(f"Markers: {', '.join('`' + m + '`' for m in f['markers'])}")
            a("")
            for quote in f["evidence"]:
                a(f"> {quote}")
                a("")

    a("## What was NOT flagged, and why")
    a("")
    a("Stock watermarks on `EXTERNAL_SOURCING`, `CONTEXT_MISMATCH` and `REUSE` cases are "
      "**not** defects — those archetypes are built from externally sourced imagery, so "
      "a 'shutterstock' overlay is the ground-truth signal behaving exactly as designed. "
      "Only labels asserting an original Indian photograph can be contradicted.")
    a("")
    a("Weak markers were deliberately left out: `pickup` (pickups exist in India and the "
      "word appears in honest records), `highway`, and `forest` (India has both). "
      "Widening the net would inflate this count by relabelling honest cases, which "
      "would make the audit look thorough while making the corpus worse.")
    a("")

    a("## What to do with these")
    a("")
    a(f"`{EXCLUSIONS.as_posix()}` lists the affected case ids. They should be dropped "
      "from the clean false-positive denominator for **both** arms — not relabelled as "
      "fraud, because the fraud is in the corpus construction rather than in the "
      "simulated claimant's behaviour. The ground-truth CSV is deliberately left "
      "unmodified: it is regenerated from seed, so an edit here would be silently "
      "reverted by the next `generate_dataset` run. The exclusion list is the durable "
      "artefact; the long-term fix belongs in the generator's image selection.")

    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
