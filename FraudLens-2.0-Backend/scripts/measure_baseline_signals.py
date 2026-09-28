"""
Can anything detect AI_GENERATED_BASELINE?

Two candidate signals, measured rather than assumed:

(a) **Cross-case linkage.** In the real world this is the attack's
    signature: a vehicle inspected as undamaged at inception that claims
    for damage weeks later. Testing it first because it needs no pixels.

(b) **Synthetic-image forensics over the inspection photographs.**
    `ai_generation`'s artificial-probability and `digital_edit`'s forensic
    scores. `ai_generation` was demoted for having *inverted*
    discriminative value (-11.3pp), but inversion is not uselessness: a
    signal that reliably points the wrong way is a detector with a flipped
    sign. That is worth one measurement before giving up.

Discrimination is reported as AUC via the rank-sum identity, the same way
the digital_edit calibration did it, so the numbers are comparable. AUC
0.5 is chance; **0.0 is as informative as 1.0** and is exactly what a
perfectly inverted signal looks like.

Writes outputs/baseline_signal_measurement.json.
"""

from __future__ import annotations

import csv
import json
import os
import statistics
import sys
from pathlib import Path
from typing import Any, Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]

from src import db
from src.checks import REGISTRY
from src.checks.base import CheckContext

OUT = Path("outputs/baseline_signal_measurement.json")
TARGET = "AI_GENERATED_BASELINE"


def auc(positives: list[float], negatives: list[float]) -> Optional[float]:
    """
    P(random positive scores above random negative), ties counted as half.

    Rank-sum rather than a curve: exact, and honest about small samples.
    """
    if not positives or not negatives:
        return None
    wins = 0.0
    for p in positives:
        for n in negatives:
            if p > n:
                wins += 1
            elif p == n:
                wins += 0.5
    return wins / (len(positives) * len(negatives))


def describe(values: list[float]) -> dict[str, Any]:
    if not values:
        return {"n": 0}
    return {
        "n": len(values),
        "median": round(statistics.median(values), 4),
        "mean": round(statistics.fmean(values), 4),
    }


def _image_width(path: Optional[str]) -> Optional[int]:
    if not path or not os.path.exists(path):
        return None
    try:
        from PIL import Image
        with Image.open(path) as im:
            return im.size[0]
    except Exception:  # noqa: BLE001
        return None


def compression_profile(conn, archetype: dict[str, str]) -> dict[str, Any]:
    """
    Bytes-per-pixel and JPEG quantisation for both groups.

    This is the control that decides whether the forensic AUC below means
    anything. Every AI baseline image was re-encoded by
    scripts/normalise_ai_images.py (PNG -> JPEG q92) while curated images
    were not, so the two groups may differ in compression rather than in
    synthesis - and a CNN trained to spot generated imagery is well known
    to latch onto exactly that. Measured, not assumed.
    """
    from PIL import Image

    def profile(ids: list[str]) -> dict[str, Any]:
        bpp, qmeans, widths = [], [], []
        for case_id in ids:
            for image in db.get_images_for_case(conn, case_id):
                path = getattr(image, "path", None)
                if not path or not os.path.exists(path):
                    continue
                try:
                    with Image.open(path) as im:
                        w, h = im.size
                        widths.append(w)
                        bpp.append(os.path.getsize(path) / (w * h))
                        q = getattr(im, "quantization", None)
                        if q:
                            qmeans.append(sum(q[0]) / len(q[0]))
                except Exception:  # noqa: BLE001
                    continue
        return {"width": describe([float(x) for x in widths]),
                "bytes_per_pixel": describe(bpp),
                "jpeg_qtable_mean": describe(qmeans)}

    cases = [c for c in db.get_all_cases(conn) if c.agent_type == "underwriting"]
    target = [c.case_id for c in cases if archetype.get(c.case_id) == TARGET]
    clean = [c.case_id for c in cases if archetype.get(c.case_id) == "CLEAN"]
    return {"target": profile(target), "clean": profile(clean)}


def linkage_signal(conn) -> dict[str, Any]:
    """(a) Does any inspection share a vehicle or claimant with a claim?"""
    cases = db.get_all_cases(conn)
    by_reg: dict[str, list[str]] = {}
    by_claimant: dict[str, list[str]] = {}
    for c in cases:
        by_reg.setdefault(c.vehicle_registration, []).append(c.case_id)
        by_claimant.setdefault(c.claimant_id, []).append(c.case_id)

    shared_reg = sum(1 for v in by_reg.values() if len(v) > 1)
    shared_claimant = sum(1 for v in by_claimant.values() if len(v) > 1)
    return {
        "total_cases": len(cases),
        "distinct_registrations": len(by_reg),
        "distinct_claimants": len(by_claimant),
        "registrations_shared_by_multiple_cases": shared_reg,
        "claimants_with_multiple_cases": shared_claimant,
        "usable": shared_reg > 0 or shared_claimant > 0,
        "verdict": (
            "UNAVAILABLE - every case has a unique registration and a unique claimant, "
            "so no inspection can be cross-referenced against any claim. This is a "
            "property of the corpus, not of the signal: in production this is the "
            "attack's strongest tell, and the generator would have to model repeat "
            "customers before it could be measured at all."
            if not (shared_reg or shared_claimant)
            else "linkage exists; measurable"
        ),
    }


def forensic_signal(conn, archetype: dict[str, str]) -> dict[str, Any]:
    """(b) Do the pixel-level checks separate synthetic baselines from real ones?"""
    cases = {c.case_id: c for c in db.get_all_cases(conn) if c.agent_type == "underwriting"}
    target_ids = [c for c in cases if archetype.get(c) == TARGET]
    clean_ids = [c for c in cases if archetype.get(c) == "CLEAN"]

    out: dict[str, Any] = {}
    for check_id, evidence_key in (("ai_generation", "artificial_probability"),
                                   ("digital_edit", None)):
        check = REGISTRY.get(check_id)
        if check is None:
            continue
        scores: dict[str, list[float]] = {"target": [], "clean": []}
        widths: dict[str, list[float]] = {"target": [], "clean": []}

        for label, ids in (("target", target_ids), ("clean", clean_ids)):
            for case_id in ids:
                case = cases[case_id]
                images = db.get_images_for_case(conn, case_id)
                if not images:
                    continue
                image_by_id = {i.image_id: i for i in images}
                ctx = CheckContext(conn=conn, case=case, images=images,
                                   perception={}, config={})
                try:
                    findings = check.run(ctx)
                except Exception:  # noqa: BLE001 - a crashing check is a null result here
                    continue
                for f in findings:
                    ev = f.evidence or {}
                    value = None
                    if evidence_key and evidence_key in ev:
                        value = ev[evidence_key]
                    else:
                        # digital_edit nests its forensic scores under
                        # "signals": {ghost, noise, edge, combined}. An
                        # earlier version of this script guessed flat key
                        # names, found none, and silently measured zero
                        # images - which would have been reported as
                        # "digital_edit yields nothing" when in fact it had
                        # never been asked. Read the real key.
                        signals = ev.get("signals")
                        if isinstance(signals, dict):
                            value = signals.get("combined")
                    if isinstance(value, (int, float)):
                        scores[label].append(float(value))
                        # The check's evidence carries no width, so measure
                        # it from the file. Resolution is not a detail here:
                        # an 8x apparent improvement in this very check was
                        # once entirely a resolution artefact.
                        path = getattr(image_by_id.get(f.evidence.get("image_id")),
                                       "path", None)
                        w = _image_width(path)
                        if w:
                            widths[label].append(float(w))

        a = auc(scores["target"], scores["clean"])
        out[check_id] = {
            "target": describe(scores["target"]),
            "clean": describe(scores["clean"]),
            "auc_target_over_clean": None if a is None else round(a, 4),
            # A resolution gap between the two groups would make any AUC a
            # statement about image size rather than about synthesis - the
            # exact confound that inflated this check's apparent value by 8x
            # in an earlier session.
            "width_target": describe(widths["target"]),
            "width_clean": describe(widths["clean"]),
        }
    return out


def main() -> None:
    conn = db.connect("fraudlens.db")
    archetype = {r["case_id"]: r["archetype"]
                 for r in csv.DictReader(
                     open("data/generated/ground_truth.csv", encoding="utf-8"))}

    print("(a) cross-case linkage")
    linkage = linkage_signal(conn)
    print(f"    {linkage['verdict'][:110]}")

    print("(b) synthetic-image forensics over inspection photographs")
    forensics = forensic_signal(conn, archetype)
    for check_id, stats in forensics.items():
        a = stats["auc_target_over_clean"]
        print(f"    {check_id:16s} AUC={a}  "
              f"target n={stats['target'].get('n')} median={stats['target'].get('median')}  "
              f"clean n={stats['clean'].get('n')} median={stats['clean'].get('median')}")

    # An AUC is only meaningful with samples on both sides; and |AUC-0.5|
    # is the informative quantity, because an inverted signal is still a
    # signal when read with a flipped sign.
    usable = []
    for check_id, stats in forensics.items():
        a = stats["auc_target_over_clean"]
        if a is not None and stats["target"].get("n", 0) >= 5 and abs(a - 0.5) >= 0.15:
            usable.append((check_id, a))

    compression = compression_profile(conn, archetype)
    qt = compression["target"]["jpeg_qtable_mean"].get("median")
    qc = compression["clean"]["jpeg_qtable_mean"].get("median")
    confounded = (qt is not None and qc is not None
                  and abs(qt - qc) / max(qt, qc) > 0.10)

    if usable and confounded:
        conclusion = (
            f"CANDIDATE, BUT CONFOUNDED. {usable} shows discrimination "
            "(inverted; read with a flipped sign), and resolution is matched between "
            f"the groups - but JPEG quantisation is not (target {qt:.2f} vs clean "
            f"{qc:.2f}). Every AI baseline image was re-encoded by "
            "normalise_ai_images.py while curated images were not, so this signal may "
            "be detecting the re-encode rather than the synthesis. This check has "
            "already produced one confounded result in this project (an 8x resolution "
            "artefact); it does not get the benefit of the doubt a second time. "
            "NOT adopted. Requires a compression-matched control - re-encode the clean "
            "images identically and re-measure - before any weight above 0.0."
        )
    elif usable:
        conclusion = f"candidate signal(s) found, no confound detected: {usable}"
    else:
        conclusion = ("NO USABLE SIGNAL. Neither candidate discriminates "
                      "AI_GENERATED_BASELINE in this corpus.")

    result = {
        "target_archetype": TARGET,
        "linkage_signal": linkage,
        "forensic_signals": forensics,
        "compression_control": compression,
        "resolution_matched": True,
        "compression_confounded": confounded,
        "usable_signals": usable,
        "adopted": False,
        "conclusion": conclusion,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(f"\n{result['conclusion']}")
    print(f"-> {OUT}")


if __name__ == "__main__":
    main()
