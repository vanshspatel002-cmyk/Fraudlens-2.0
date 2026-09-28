"""
Normalise the AI-generated source images to match the rest of the corpus.

Why this is not cosmetic
------------------------
Every other image in this project is a JPEG. The AI-generated sets arrive
as PNG. If they stayed PNG they would be the *only* PNGs in the corpus,
and any check could then separate AI_GENERATED from everything else by
reading the file header - scoring 100% while learning nothing about
synthesis. The whole point of the AI archetypes is to test whether a
detector can see generation artifacts, so the file container has to be
held constant or the experiment measures the wrong thing.

Quality 92 rather than the 85 used for DIGITAL_EDIT composites: this is a
one-time conversion of a source asset, not a simulated forgery, so it
should lose as little as possible. It is also the same quality the
digital-edit composite now saves at, which keeps the corpus's JPEG
history uniform.

RGBA is composited onto white rather than dropped, because discarding the
alpha channel outright turns transparent regions black and would put a
large black rectangle in some frames - a far louder artifact than
anything the detector is meant to find.

Idempotent: re-running finds the JPEGs already present, skips them, and
leaves everything alone. PNG originals are deleted only after their JPEG
has been written AND re-opened successfully.

Usage:
    python scripts/normalise_ai_images.py
    python scripts/normalise_ai_images.py --dry-run
"""

from __future__ import annotations

import argparse
import json
import random
import statistics
import sys
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]

from PIL import Image as PILImage

JPEG_QUALITY = 92

# The folders arrive from macOS and Windows machines and carry their
# metadata droppings. These are deleted rather than merely skipped: left
# in place they would be picked up by any future glob that is less
# careful than this one.
JUNK_NAMES = {".DS_Store", "Thumbs.db", "desktop.ini", ".localized"}

# Below this the image is too small for the vision model and the AI
# detector to say anything useful, and it is worth knowing by name which
# ones they are before they end up in an archetype.
MIN_USEFUL_SHORT_SIDE = 400

# Resolution has to be held constant for exactly the same reason the file
# container does, and this one is louder. Measured: the curated damaged
# pool is median 189px on its short side (p25 183, max 225); the
# AI-generated set arrives at median 1522px. An 8x difference means any
# check - the AI detector very much included - could separate
# AI_GENERATED from the rest of the corpus by reading image dimensions
# and score near-perfectly while learning nothing whatsoever about
# synthesis. That would be a worse experiment than not running one.
#
# So each AI image is downscaled to a short side drawn from the empirical
# distribution of the curated pool it will sit alongside: damaged AI
# images match data/curated/damaged, underwriting AI images match
# data/curated/whole. Seeded, so the assignment is reproducible.
#
# Downscale only, never up: enlarging a small source would invent detail
# and is a different kind of artifact.
MATCH_SEED = 42
RESIZE_MANIFEST = Path("data/cache/ai_resize_manifest.json")

TARGETS = [
    (Path("data/ai_generated"), "ai_{:03d}.jpg", Path("data/curated/damaged")),
    (Path("data/ai_generated_underwriting"), "ai_uw_{:03d}.jpg", Path("data/curated/whole")),
]


def corpus_short_sides(folder: Path, limit: int = 400) -> list[int]:
    """Empirical short-side distribution of a curated pool."""
    sides: list[int] = []
    for path in sorted(folder.glob("*.jpg"))[:limit]:
        try:
            with PILImage.open(path) as img:
                sides.append(min(img.size))
        except Exception:  # noqa: BLE001
            continue
    return sides


def load_manifest() -> dict:
    if RESIZE_MANIFEST.exists():
        try:
            return json.loads(RESIZE_MANIFEST.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
    return {}


def save_manifest(manifest: dict) -> None:
    RESIZE_MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    RESIZE_MANIFEST.write_text(json.dumps(manifest, indent=2), encoding="utf-8")


def match_resolution(folder: Path, reference: Path, rng: random.Random, dry_run: bool) -> dict:
    """
    Downscale each JPEG in `folder` to a short side sampled from
    `reference`'s distribution. Idempotent via a manifest, so re-running
    never shrinks an image twice.
    """
    out = {"resized": 0, "already": 0, "skipped": 0, "after": []}
    sides = corpus_short_sides(reference)
    if not sides:
        out["skipped"] = -1
        return out

    manifest = load_manifest()
    for path in sorted(folder.glob("*.jpg")):
        key = f"{folder.name}/{path.name}"
        if key in manifest:
            out["already"] += 1
            with PILImage.open(path) as img:
                out["after"].append(min(img.size))
            continue

        target = rng.choice(sides)
        with PILImage.open(path) as img:
            short = min(img.size)
            if short <= target:
                # Never upscale - inventing detail is its own artifact.
                out["skipped"] += 1
                out["after"].append(short)
                manifest[key] = {"target": short, "action": "kept"}
                continue
            scale = target / short
            new_size = (max(1, round(img.width * scale)), max(1, round(img.height * scale)))
            resized = img.convert("RGB").resize(new_size, PILImage.LANCZOS)
        if not dry_run:
            resized.save(path, format="JPEG", quality=JPEG_QUALITY)
            manifest[key] = {"target": target, "action": "resized"}
        out["resized"] += 1
        out["after"].append(min(new_size))

    if not dry_run:
        save_manifest(manifest)
    return out


def convert(source: Path, dest: Path) -> tuple[int, int]:
    """PNG -> JPEG at JPEG_QUALITY, flattening alpha onto white."""
    with PILImage.open(source) as img:
        if img.mode in ("RGBA", "LA", "P"):
            rgba = img.convert("RGBA")
            canvas = PILImage.new("RGB", rgba.size, (255, 255, 255))
            canvas.paste(rgba, mask=rgba.split()[-1])
            out = canvas
        else:
            out = img.convert("RGB")
        size = out.size
        out.save(dest, format="JPEG", quality=JPEG_QUALITY)
    return size


def verify(path: Path) -> Optional[tuple[int, int]]:
    """Re-open a written JPEG and confirm it is a real 3-channel image."""
    try:
        with PILImage.open(path) as img:
            img.load()
            if img.mode != "RGB":
                return None
            return img.size
    except Exception:  # noqa: BLE001 - truncated write, bad encoder, anything
        return None


def process(folder: Path, pattern: str, dry_run: bool) -> dict:
    result = {
        "folder": str(folder), "converted": 0, "already_jpeg": 0,
        "junk_deleted": [], "skipped": [], "sizes": [], "small": [], "failed": [],
    }
    if not folder.exists():
        result["skipped"].append(f"{folder} does not exist")
        return result

    for junk in sorted(folder.iterdir()):
        if junk.name in JUNK_NAMES or junk.name.startswith("._"):
            result["junk_deleted"].append(junk.name)
            if not dry_run:
                junk.unlink(missing_ok=True)

    # Sort by original filename, as specified, so numbering is stable
    # across runs and reproducible from the source set.
    candidates = sorted(
        (p for p in folder.iterdir() if p.is_file() and p.suffix.lower() in {".png", ".jpg", ".jpeg"}),
        key=lambda p: p.name.lower(),
    )

    for index, source in enumerate(candidates, start=1):
        dest = folder / pattern.format(index)
        if source.suffix.lower() in {".jpg", ".jpeg"}:
            # Already normalised on a previous run. Confirm it still
            # loads rather than trusting the extension.
            size = verify(source)
            if size is None:
                result["failed"].append(f"{source.name}: existing JPEG will not load")
                continue
            result["already_jpeg"] += 1
            result["sizes"].append(min(size))
            if min(size) < MIN_USEFUL_SHORT_SIDE:
                result["small"].append(f"{source.name} ({size[0]}x{size[1]})")
            continue

        if dry_run:
            result["converted"] += 1
            continue

        try:
            convert(source, dest)
        except Exception as e:  # noqa: BLE001
            result["failed"].append(f"{source.name}: {type(e).__name__}: {e}")
            continue

        size = verify(dest)
        if size is None:
            result["failed"].append(f"{source.name}: JPEG written but will not re-open; PNG kept")
            continue

        # Only now is it safe to drop the original.
        source.unlink(missing_ok=True)
        result["converted"] += 1
        result["sizes"].append(min(size))
        if min(size) < MIN_USEFUL_SHORT_SIDE:
            result["small"].append(f"{dest.name} ({size[0]}x{size[1]})")

    return result


def main(argv: Optional[list[str]] = None) -> None:
    parser = argparse.ArgumentParser(description="Normalise AI-generated images to corpus-standard JPEG.")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    rng = random.Random(MATCH_SEED)
    for folder, pattern, reference in TARGETS:
        r = process(folder, pattern, args.dry_run)
        print(f"\n=== {r['folder']}")
        total = r["converted"] + r["already_jpeg"]
        print(f"  final count: {total}  (converted {r['converted']}, already JPEG {r['already_jpeg']})")
        if r["sizes"]:
            s = sorted(r["sizes"])
            print(f"  short side: min {s[0]}  median {int(statistics.median(s))}  max {s[-1]}")
        if r["junk_deleted"]:
            print(f"  junk deleted ({len(r['junk_deleted'])}): {', '.join(r['junk_deleted'])}")
        else:
            print("  junk deleted: none")
        if r["small"]:
            print(f"  UNDER {MIN_USEFUL_SHORT_SIDE}px short side ({len(r['small'])}):")
            for name in r["small"]:
                print(f"    {name}")
        else:
            print(f"  none under {MIN_USEFUL_SHORT_SIDE}px short side")
        for label in ("skipped", "failed"):
            if r[label]:
                print(f"  {label}: {'; '.join(str(x) for x in r[label])}")

        m = match_resolution(folder, reference, rng, args.dry_run)
        if m["after"]:
            a = sorted(m["after"])
            print(f"  resolution-matched to {reference.name}: "
                  f"{m['resized']} resized, {m['already']} already done, {m['skipped']} left as-is")
            print(f"  short side after: min {a[0]}  median {int(statistics.median(a))}  max {a[-1]}")


if __name__ == "__main__":
    main()
