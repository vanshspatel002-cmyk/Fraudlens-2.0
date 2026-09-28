"""
Localised JPEG-ghost / noise / edge forensics for digital_edit.

--------------------------------------------------------------------------
The defect being fixed
--------------------------------------------------------------------------
All three existing signals are whole-frame aggregates. `ghost_score` computes
the share of 8x8 blocks disagreeing with the frame's MODAL compression
quality; a composited patch covering 5% of the frame moves that share by 5%
at most, and sensor noise moves it by more. The statistic averages away the
very discontinuity it is meant to find. Measured combined AUC was 0.546.

The fix is to stop asking "is this frame globally coherent?" and start asking
"does any REGION of this frame disagree with the rest of it?" - which is the
question a composite actually answers.

--------------------------------------------------------------------------
Why this is cheap
--------------------------------------------------------------------------
The expensive parts - eight JPEG re-encodes for the ghost map, the median
residual, the gradient magnitudes - are computed ONCE per frame. Region
scoring then indexes into those maps. Localisation therefore costs array
slicing, not re-analysis.

--------------------------------------------------------------------------
Validation beyond AUC
--------------------------------------------------------------------------
The generator records `patch_box` for every DIGITAL_EDIT case, so this also
measures whether the highest-scoring region actually OVERLAPS the composited
patch. A detector that separates classes without localising the edit is
probably keying on something else, and AUC alone would not reveal that.

Writes outputs/digital_edit_localised.json.
"""

from __future__ import annotations

import csv
import json
import statistics
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]

import numpy as np

from src import db

OUT = Path("outputs/digital_edit_localised.json")
GHOST_QUALITIES = (55, 65, 70, 75, 80, 85, 90, 95)

# Region proposal geometry. Windows are a fraction of the smaller image side,
# so the same settings work across the corpus's wide resolution range.
# Matched to the target, not chosen for convenience. The generator's recorded
# patch_box values occupy a median 4.4% of frame area (min 0.4%, max 24.9%) on
# a median 635x464 image - roughly 114px square at the median and 34px at the
# smallest. The first attempt used windows of 0.25 and 0.4 of the smaller side
# (116px and 186px), which are as large as or larger than the patch itself, so
# the edit was diluted inside the window and the localised statistic
# reproduced the whole-frame one. These scales bracket the actual patch sizes.
WINDOW_FRACTIONS = (0.07, 0.12, 0.22)
STRIDE_FRACTION = 0.4      # of the window size
MIN_WINDOW_PX = 24


def frame_maps(bgr: "np.ndarray") -> Optional[dict[str, Any]]:
    """Every per-pixel/per-block map the region scorers need, computed once."""
    import cv2

    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY).astype(np.float32)
    h, w = gray.shape
    bh, bw = h // 8, w // 8
    if bh < 4 or bw < 4:
        return None

    # Ghost: per-8x8-block index of the best-matching re-encode quality.
    errors = np.empty((len(GHOST_QUALITIES), bh, bw), dtype=np.float32)
    for qi, quality in enumerate(GHOST_QUALITIES):
        ok, buf = cv2.imencode(".jpg", bgr, [int(cv2.IMWRITE_JPEG_QUALITY), quality])
        if not ok:
            return None
        recoded = cv2.cvtColor(cv2.imdecode(buf, cv2.IMREAD_COLOR),
                               cv2.COLOR_BGR2GRAY).astype(np.float32)
        diff = (gray - recoded) ** 2
        errors[qi] = diff[: bh * 8, : bw * 8].reshape(bh, 8, bw, 8).mean(axis=(1, 3))
    best_quality = errors.argmin(axis=0).astype(np.int16)   # (bh, bw)

    # Noise: high-pass residual.
    residual = gray - cv2.medianBlur(gray.astype(np.uint8), 3).astype(np.float32)

    # Edge: gradient magnitude before and after a small blur.
    gx = cv2.Sobel(gray, cv2.CV_32F, 1, 0, ksize=3)
    gy = cv2.Sobel(gray, cv2.CV_32F, 0, 1, ksize=3)
    magnitude = np.sqrt(gx * gx + gy * gy)
    blurred = cv2.GaussianBlur(gray, (0, 0), 1.0)
    bx = cv2.Sobel(blurred, cv2.CV_32F, 1, 0, ksize=3)
    by = cv2.Sobel(blurred, cv2.CV_32F, 0, 1, ksize=3)
    blurred_magnitude = np.sqrt(bx * bx + by * by)

    return {"gray": gray, "shape": (h, w), "best_quality": best_quality,
            "residual": residual, "magnitude": magnitude,
            "blurred_magnitude": blurred_magnitude}


def propose_regions(shape: tuple[int, int]) -> list[tuple[int, int, int, int]]:
    """
    Sliding windows at two scales, as (x0, y0, x1, y1) in pixels.

    Contour-based proposals were considered and rejected: contours follow
    object boundaries, and a composited patch is usually pasted ACROSS an
    object boundary rather than along one, so contours tend to propose the
    wrong shape. A dense sliding window makes no assumption about what the
    edit looks like.
    """
    h, w = shape
    smaller = min(h, w)
    regions: list[tuple[int, int, int, int]] = []
    for frac in WINDOW_FRACTIONS:
        win = max(MIN_WINDOW_PX, int(smaller * frac))
        if win >= min(h, w):
            continue
        stride = max(8, int(win * STRIDE_FRACTION))
        for y0 in range(0, h - win + 1, stride):
            for x0 in range(0, w - win + 1, stride):
                regions.append((x0, y0, x0 + win, y0 + win))
    if not regions:
        regions.append((0, 0, w, h))
    return regions


def score_regions(maps: dict[str, Any]) -> dict[str, Any]:
    """
    Per-signal maximum regional deviation from the frame's own median.

    Deviation from the frame median, not from a global constant: the
    question is internal inconsistency, and every image has its own baseline
    noise level and compression history.
    """
    h, w = maps["shape"]
    regions = propose_regions((h, w))
    best_quality = maps["best_quality"]
    residual = maps["residual"]
    magnitude = maps["magnitude"]
    blurred_magnitude = maps["blurred_magnitude"]

    strong_cut = float(np.percentile(magnitude, 98))
    strong_mask = magnitude >= strong_cut if strong_cut > 1e-6 else None

    frame_modal = int(np.bincount(best_quality.ravel(),
                                  minlength=len(GHOST_QUALITIES)).argmax())

    ghost_vals, noise_vals, edge_vals, boxes = [], [], [], []
    for (x0, y0, x1, y1) in regions:
        by0, by1 = y0 // 8, max(y0 // 8 + 1, y1 // 8)
        bx0, bx1 = x0 // 8, max(x0 // 8 + 1, x1 // 8)
        block = best_quality[by0:by1, bx0:bx1]
        if block.size < 4:
            continue

        # Ghost: how much of this region prefers a quality other than the
        # frame's modal one. A patch saved at a different quality shows up
        # here even when it is a small share of the whole frame.
        ghost_vals.append(float((block != frame_modal).mean()))

        cell = residual[y0:y1, x0:x1]
        noise_vals.append(float(cell.std()))

        if strong_mask is not None:
            m = strong_mask[y0:y1, x0:x1]
            if m.sum() >= 10:
                r = blurred_magnitude[y0:y1, x0:x1][m] / (magnitude[y0:y1, x0:x1][m] + 1e-6)
                edge_vals.append(float(np.mean(r < 0.35)))
            else:
                edge_vals.append(0.0)
        else:
            edge_vals.append(0.0)
        boxes.append((x0, y0, x1, y1))

    if not ghost_vals:
        return {"ghost": 0.0, "noise": 0.0, "edge": 0.0, "top_box": None}

    def deviation(values: list[float]) -> tuple[float, int]:
        med = float(np.median(values))
        spread = float(np.median(np.abs(np.array(values) - med))) or 1e-6
        # Robust z-like score: how far the most extreme region sits from the
        # bulk, in units of the bulk's own spread.
        z = [(v - med) / spread for v in values]
        i = int(np.argmax(z))
        return float(np.clip(z[i] / 10.0, 0.0, 1.0)), i

    g, gi = deviation(ghost_vals)
    n, ni = deviation(noise_vals)
    e, ei = deviation(edge_vals)
    return {"ghost": g, "noise": n, "edge": e,
            "top_box": boxes[gi] if gi < len(boxes) else None,
            "top_noise_box": boxes[ni] if ni < len(boxes) else None}


def iou(a: tuple[int, int, int, int], b: tuple[int, int, int, int]) -> float:
    ax0, ay0, ax1, ay1 = a
    bx0, by0, bx1, by1 = b
    ix0, iy0 = max(ax0, bx0), max(ay0, by0)
    ix1, iy1 = min(ax1, bx1), min(ay1, by1)
    if ix1 <= ix0 or iy1 <= iy0:
        return 0.0
    inter = (ix1 - ix0) * (iy1 - iy0)
    union = (ax1 - ax0) * (ay1 - ay0) + (bx1 - bx0) * (by1 - by0) - inter
    return inter / union if union else 0.0


def auc(pos: list[float], neg: list[float]) -> Optional[float]:
    if not pos or not neg:
        return None
    wins = 0.0
    for p in pos:
        for n in neg:
            wins += 1.0 if p > n else (0.5 if p == n else 0.0)
    return wins / (len(pos) * len(neg))


def main() -> None:
    import cv2

    conn = db.connect("fraudlens.db")
    rows = list(csv.DictReader(open("data/generated/ground_truth.csv", encoding="utf-8")))
    meta = {}
    for r in rows:
        try:
            meta[r["case_id"]] = json.loads(r["fraud_metadata"]) if r["fraud_metadata"] else {}
        except json.JSONDecodeError:
            meta[r["case_id"]] = {}
    archetype = {r["case_id"]: r["archetype"] for r in rows}

    edited = [c for c, a in archetype.items() if a == "DIGITAL_EDIT"]
    clean = [c for c, a in archetype.items() if a == "CLEAN"]
    # Cap the clean sample: 34 positives against 300 negatives is ample for an
    # AUC and keeps the run to minutes.
    clean = sorted(clean)[:300]

    scores: dict[str, list[dict[str, Any]]] = defaultdict(list)
    localised_hits, localised_total = 0, 0

    for label, ids in (("edited", edited), ("clean", clean)):
        for i, case_id in enumerate(ids, 1):
            for image in db.get_images_for_case(conn, case_id):
                path = image.path
                if not path or not Path(path).exists():
                    continue
                bgr = cv2.imread(path, cv2.IMREAD_COLOR)
                if bgr is None:
                    continue
                maps = frame_maps(bgr)
                if maps is None:
                    continue
                s = score_regions(maps)
                s["case_id"] = case_id
                s["variant"] = meta.get(case_id, {}).get("variant")
                scores[label].append(s)

                box = meta.get(case_id, {}).get("patch_box")
                if label == "edited" and box and s.get("top_box"):
                    localised_total += 1
                    if iou(tuple(s["top_box"]), tuple(box)) > 0.1:
                        localised_hits += 1
            if i % 25 == 0:
                print(f"  {label}: {i}/{len(ids)}", flush=True)

    # Weights fitted by each signal's own discrimination, normalised. A
    # logistic fit on 34 positives would overfit; AUC-proportional weighting
    # is the honest amount of model this sample supports.
    aucs = {}
    for sig in ("ghost", "noise", "edge"):
        aucs[sig] = auc([s[sig] for s in scores["edited"]],
                        [s[sig] for s in scores["clean"]]) or 0.5
    lift = {k: max(0.0, v - 0.5) for k, v in aucs.items()}
    total_lift = sum(lift.values()) or 1.0
    weights = {k: v / total_lift for k, v in lift.items()}

    def combined(s: dict[str, Any]) -> float:
        return sum(weights[k] * s[k] for k in ("ghost", "noise", "edge"))

    combined_auc = auc([combined(s) for s in scores["edited"]],
                       [combined(s) for s in scores["clean"]])

    per_variant = {}
    for variant in ("single_save", "recompressed_patch"):
        pos = [combined(s) for s in scores["edited"] if s.get("variant") == variant]
        per_variant[variant] = {
            "n": len(pos),
            "auc": auc(pos, [combined(s) for s in scores["clean"]]),
        }

    result = {
        "method": "localised region deviation (sliding window, two scales)",
        "n_edited_images": len(scores["edited"]),
        "n_clean_images": len(scores["clean"]),
        "signal_auc": aucs,
        "fitted_weights": weights,
        "combined_auc": combined_auc,
        "per_variant": per_variant,
        "localisation": {
            "evaluated": localised_total,
            "top_region_overlaps_patch": localised_hits,
            "rate": (localised_hits / localised_total) if localised_total else None,
            "note": ("Whether the highest-ghost-deviation region overlaps the "
                     "generator's recorded patch_box (IoU > 0.1). A detector that "
                     "separates the classes without localising the edit is keying on "
                     "something other than the composite."),
        },
        "previous_whole_frame_auc": 0.5458245798319328,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(result, indent=2), encoding="utf-8")

    print(f"\nsignal AUCs      : { - 0 if False else {k: round(v, 3) for k, v in aucs.items()}}")
    print(f"fitted weights   : {{k: round(v, 3) for k, v in weights.items()}}".replace(
        "{k: round(v, 3) for k, v in weights.items()}",
        str({k: round(v, 3) for k, v in weights.items()})))
    print(f"combined AUC     : {combined_auc:.4f}  (whole-frame was 0.5458)")
    for v, d in per_variant.items():
        print(f"  {v:22s} n={d['n']:3d} AUC={d['auc']}")
    if localised_total:
        print(f"localisation     : {localised_hits}/{localised_total} "
              f"({localised_hits / localised_total:.0%}) top region overlaps the patch")
    print(f"-> {OUT}")


if __name__ == "__main__":
    main()
