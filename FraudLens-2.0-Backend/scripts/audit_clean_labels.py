"""
Audit every CLEAN case for evidence that it is not clean.

--------------------------------------------------------------------------
Why
--------------------------------------------------------------------------
The perception-based scan in scripts/audit_corpus_geography.py found 4
defective clean cases out of the 22 it could see - 18.2% - and it could only
see cases the vision pass had already described. One of those, `case-0353`,
carries a **Getty Images watermark** and was counted as a claims-clean
success in the prompt A/B.

A CLEAN case whose photograph carries a stock-agency watermark is
indistinguishable from the EXTERNAL_SOURCING fraud archetype. Running the
ablation against those labels would score both arms against a ground truth
that is wrong, and would do so asymmetrically: the baseline cannot read a
watermark and scores a correct clear, while the agent reads it, flags it,
and is scored as a false positive for being right.

So this does not wait for perception coverage. It runs OCR directly over
every clean case's images.

--------------------------------------------------------------------------
Method
--------------------------------------------------------------------------
OCR (easyocr, CPU) on a downscaled copy of each image. Downscaling is not
only for speed: watermarks are typically large, high-contrast overlays, so
they survive downscaling while fine detail that produces OCR noise does not.

Results are cached per image content hash, so this is resumable and a second
run costs nothing. Combined with the perception-text geographic scan, which
catches what OCR cannot (a desert landscape has no text).

Conservative by design. A token must be a recognised stock agency, a URL, or
an explicit recycling/salvage brand. Generic words that happen to appear on
real Indian vehicles and signage are not evidence, and inflating this count
by loosening the patterns would make the corpus worse while making the audit
look thorough.

Writes outputs/clean_label_audit.md and updates
data/generated/corpus_exclusions.json.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]

from src import db

CACHE = Path("outputs/.ocr_cache.json")
REPORT = Path("outputs/clean_label_audit.md")
EXCLUSIONS = Path("data/generated/corpus_exclusions.json")
GROUND_TRUTH = Path("data/generated/ground_truth.csv")

OCR_MAX_WIDTH = 900          # watermarks survive this; OCR noise mostly does not
OCR_MIN_CONFIDENCE = 0.30    # easyocr's own score; below this is mostly hallucination

# Stock agencies and republication marks. Each is a brand or a URL - things
# that cannot appear on an original photograph taken by a claimant.
WATERMARK_PATTERNS: tuple[tuple[str, str], ...] = (
    ("stock_agency",
     r"getty\s*images?|shutterstock|alamy|istock|dreamstime|depositphotos|123rf|"
     r"adobe\s*stock|bigstock|can\s*stock|stockphoto|vectorstock"),
    ("republication_url", r"\bwww\.[a-z0-9\-]+\.(?:com|net|org|co\.uk|in)\b|"
                          r"\b[a-z0-9\-]{4,}\.(?:com|net)\b"),
    ("salvage_brand", r"auto\s*recycl|salvage\s*yard|copart|iaai|autobodyrepair"),
)
COMPILED = [(name, re.compile(p, re.I)) for name, p in WATERMARK_PATTERNS]

# Geographic markers, reused from the perception scan so both signals land
# in one corrected label set.
GEO_PATTERNS: tuple[tuple[str, str], ...] = (
    ("non_indian_flora", r"\bsaguaro\b|\bcactus\b|\bcacti\b"),
    ("non_indian_climate", r"\bdesert environment\b|\bsnow\b|\bslush\b|\bsnowy\b"),
    ("stock_studio", r"stock photo|stock photograph|studio shot|studio background"),
    ("commercial_overlay", r"watermark reading|website watermark|promotional text overlay"),
)
GEO_COMPILED = [(name, re.compile(p, re.I)) for name, p in GEO_PATTERNS]

_reader = None


def get_reader():
    global _reader
    if _reader is None:
        import easyocr  # imported lazily; loading the model costs ~10s
        _reader = easyocr.Reader(["en"], gpu=False, verbose=False)
    return _reader


def load_cache() -> dict[str, Any]:
    if CACHE.exists():
        try:
            return json.loads(CACHE.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}
    return {}


def ocr_image(path: str) -> list[str]:
    """Text strings found in a downscaled copy, above the confidence floor."""
    from PIL import Image
    import numpy as np

    with Image.open(path) as im:
        im = im.convert("RGB")
        if im.width > OCR_MAX_WIDTH:
            ratio = OCR_MAX_WIDTH / im.width
            im = im.resize((OCR_MAX_WIDTH, max(1, int(im.height * ratio))))
        arr = np.array(im)

    out = []
    for item in get_reader().readtext(arr):
        # easyocr returns (bbox, text, confidence)
        if len(item) >= 3 and item[2] >= OCR_MIN_CONFIDENCE:
            out.append(str(item[1]))
    return out


def main(argv: Optional[list[str]] = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=None, help="cap images, for a smoke run")
    parser.add_argument("--sample-size", type=int, default=100,
                        help="ablation sample size, used only to order the work")
    parser.add_argument("--no-priority", action="store_true",
                        help="audit in plain case order instead of ablation-first")
    args = parser.parse_args(argv)

    conn = db.connect("fraudlens.db")
    archetype = {r["case_id"]: r["archetype"]
                 for r in csv.DictReader(open(GROUND_TRUTH, encoding="utf-8"))}
    clean_ids = sorted(c for c, a in archetype.items() if a == "CLEAN")

    rows = conn.execute(
        "SELECT case_id, image_id, content_hash, path FROM images"
    ).fetchall()
    by_case: dict[str, list[tuple[str, str, str]]] = {}
    for case_id, image_id, content_hash, path in rows:
        by_case.setdefault(case_id, []).append((image_id, content_hash, path))

    cache = load_cache()
    todo = [(cid, img) for cid in clean_ids for img in by_case.get(cid, [])
            if img[1] not in cache]

    # Audit the ablation's own clean cases first.
    #
    # OCR runs at ~10s/image on CPU, so a full pass over 1080 images is about
    # three hours - during which the ablation would either sit idle or run
    # against labels this script exists to correct. The ablation only needs
    # ITS clean cases to be trustworthy, and there are ~25 of them. Ordering
    # by that gets the experiment unblocked in minutes while the remaining
    # cases keep being audited behind it. Same work, same cache, better order.
    if not args.no_priority:
        try:
            from src.sampling import stratified_sample
            sample = stratified_sample(conn, args.sample_size, seed=42)
            priority = {r["case_id"] for r in sample if r["archetype"] == "CLEAN"}
        except Exception as e:  # noqa: BLE001 - ordering is an optimisation, not a requirement
            print(f"  (could not load ablation sample for prioritisation: {e})")
            priority = set()
        if priority:
            todo.sort(key=lambda item: item[0] not in priority)
            print(f"  prioritising {len(priority)} clean case(s) from the ablation sample")

    if args.limit:
        todo = todo[: args.limit]

    total_images = sum(len(by_case.get(c, [])) for c in clean_ids)
    print(f"{len(clean_ids)} clean case(s), {total_images} image(s); "
          f"{len(cache)} cached, {len(todo)} to OCR")

    done = 0
    for case_id, (image_id, content_hash, path) in todo:
        if not path or not os.path.exists(path):
            cache[content_hash] = {"error": "missing_file", "text": []}
        else:
            try:
                cache[content_hash] = {"text": ocr_image(path)}
            except Exception as e:  # noqa: BLE001 - one unreadable image must not end the pass
                cache[content_hash] = {"error": f"{type(e).__name__}: {e}", "text": []}
        done += 1
        if done % 10 == 0:
            CACHE.write_text(json.dumps(cache), encoding="utf-8")
            print(f"  {done}/{len(todo)} OCR'd", flush=True)
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    CACHE.write_text(json.dumps(cache), encoding="utf-8")

    # ---- perception text, for what OCR cannot see -------------------------
    perception_text: dict[str, str] = {}
    for content_hash, scene, anomaly, caption in conn.execute(
        "SELECT content_hash, scene_context, anomaly_notes, caption FROM perception_records"
    ):
        perception_text[content_hash] = " | ".join(
            x for x in (scene, anomaly, caption) if x)

    # ---- evaluate ---------------------------------------------------------
    defective: dict[str, dict[str, Any]] = {}
    for case_id in clean_ids:
        markers: set[str] = set()
        evidence: list[str] = []
        for image_id, content_hash, _path in by_case.get(case_id, []):
            for text in cache.get(content_hash, {}).get("text", []):
                for name, pattern in COMPILED:
                    if pattern.search(text):
                        markers.add(name)
                        if len(evidence) < 3:
                            evidence.append(f"OCR: \"{text.strip()[:80]}\"")
            ptext = perception_text.get(content_hash, "")
            if ptext:
                for name, pattern in GEO_COMPILED:
                    if pattern.search(ptext):
                        markers.add(name)
                        if len(evidence) < 3:
                            evidence.append(f"perception: \"{ptext[:140]}\"")
        if markers:
            defective[case_id] = {"case_id": case_id, "archetype": "CLEAN",
                                  "markers": sorted(markers), "evidence": evidence}

    ocr_errors = sum(1 for v in cache.values() if v.get("error"))
    payload = {
        "generated_by": "scripts/audit_clean_labels.py",
        "clean_cases_total": len(clean_ids),
        "clean_images_total": total_images,
        "images_ocred": len(cache),
        "ocr_errors": ocr_errors,
        "defective_clean_cases": len(defective),
        "corrected_clean_count": len(clean_ids) - len(defective),
        "defect_rate": round(len(defective) / len(clean_ids), 4) if clean_ids else None,
        "excluded_case_ids": sorted(defective),
        "findings": [defective[c] for c in sorted(defective)],
        "note": (
            "These cases are labelled CLEAN but carry stock-agency watermarks, "
            "republication URLs, or imagery inconsistent with the declared Indian "
            "location. They must be excluded from the clean denominator for BOTH arms "
            "of the ablation."
        ),
    }
    EXCLUSIONS.parent.mkdir(parents=True, exist_ok=True)
    EXCLUSIONS.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    write_report(payload, Counter(m for f in payload["findings"] for m in f["markers"]))
    print(f"\ndefective clean cases: {len(defective)}/{len(clean_ids)} "
          f"({payload['defect_rate']:.1%}); corrected clean count = "
          f"{payload['corrected_clean_count']}")
    print(f"-> {EXCLUSIONS}\n-> {REPORT}")


def write_report(payload: dict[str, Any], marker_counts: Counter) -> None:
    a_: list[str] = []
    a = a_.append
    a("# Clean-label audit — every clean case, OCR plus perception")
    a("")
    a(f"- Clean cases: **{payload['clean_cases_total']}**")
    a(f"- Images OCR'd: **{payload['images_ocred']}** "
      f"(errors: {payload['ocr_errors']})")
    a(f"- **Defective: {payload['defective_clean_cases']}** "
      f"({payload['defect_rate']:.1%})")
    a(f"- **Corrected clean-case count: {payload['corrected_clean_count']}**")
    a("")
    a("A CLEAN case carrying a stock-agency watermark is indistinguishable from the "
      "`EXTERNAL_SOURCING` fraud archetype. Scoring the ablation against such labels "
      "penalises the agent asymmetrically: the baseline cannot read a watermark and is "
      "credited with a correct clear, while the agent reads it, flags it, and is "
      "recorded as a false positive for being right.")
    a("")
    if marker_counts:
        a("| Marker | Cases |")
        a("|---|---|")
        for name, count in marker_counts.most_common():
            a(f"| `{name}` | {count} |")
        a("")
    a("## Affected cases")
    a("")
    if not payload["findings"]:
        a("None.")
    for f in payload["findings"]:
        a(f"### `{f['case_id']}`")
        a("")
        a(f"Markers: {', '.join('`' + m + '`' for m in f['markers'])}")
        a("")
        for e in f["evidence"]:
            a(f"> {e}")
            a("")
    a("## Method and its limits")
    a("")
    a(f"OCR (easyocr, CPU) on copies downscaled to {OCR_MAX_WIDTH}px wide, keeping "
      f"strings above confidence {OCR_MIN_CONFIDENCE}. Downscaling helps rather than "
      "hurts here: watermarks are large high-contrast overlays that survive it, while "
      "fine detail that generates OCR noise does not.")
    a("")
    a("Patterns are deliberately narrow — a recognised stock agency, a URL, or a "
      "salvage brand. Generic words that appear on real Indian signage are not "
      "evidence. Loosening them would inflate this count by relabelling honest cases, "
      "making the audit look thorough while making the corpus worse.")
    a("")
    a("**Still a lower bound.** OCR misses watermarks rendered at very low contrast, "
      "and the geographic signal only covers images the vision pass has described.")
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text("\n".join(a_) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
