"""
fraudlens.generate_dataset
===========================

Builds the synthetic 800-case corpus FraudLens is evaluated against,
from the Kaggle car-damage dataset under data/raw/data1a.

Run with (from the project root, so `src` is importable as a package):
    python -m src.generate_dataset [--count 800] [--seed 42] [--db-path fraudlens.db]

Design decision that matters most: ground truth (archetype, fraud_metadata)
is written ONLY to data/generated/ground_truth.csv, never into the
sqlite database. A Case row looks exactly like a real claim intake
would produce - see the docstring on Case in models.py. Anything that
needs to check its own work (an evaluation script) reads the CSV;
anything that's supposed to be finding fraud blind (every check, the
agent) only ever sees the database.

Second decision that matters: clean-case images are drawn from
pre-shuffled, never-replaced pools (see the *_stack lists below), so
disjointness across clean cases is true by construction, not by luck.
The assert at the end of build_case_specs() is a sanity check on that
construction, not the only thing standing between this script and a
meaningless false-positive rate.

That construction has one hole a path-based check can't see: this raw
dataset itself contains byte-identical images saved twice under two
different filenames (confirmed by hashing the whole corpus - a couple
of dozen exact content collisions across ~2,300 files). Two different
paths handed to two different "clean" cases would still produce the
exact false-positive-rate-destroying scenario the disjointness rule
exists to prevent. dedupe_by_content_hash() removes that hole before
any pool is drawn from, and the final assert checks sha256, not path.

Third decision, added after test_checks.py's first real run against this
corpus: byte-identical isn't the only kind of duplicate this raw dataset
contains. 27 of 30 CLEAN-vs-CLEAN false flags InternalDuplicateCheck
produced traced back to genuinely near-duplicate photos - same
underlying frame, re-saved or re-cropped, different sha256 - sitting in
two different "clean" cases' pools. dedupe_near_duplicates() closes that
second hole the same way dedupe_by_content_hash() closes the first: it
runs over the whole curated pool before any pool is drawn from, using
the exact same Hamming<=8-or-cosine>=0.95 thresholds
src/checks/duplicate.py's InternalDuplicateCheck uses for CONCERN, so
nothing left in the pool after it runs is something that check would
flag between two independent cases. assert_clean_images_disjoint()'s
pairwise near-duplicate assert is the sanity check on that construction,
exactly like its sha256 half already was.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import itertools
import json
import math
import random
import shutil
import string
import sys
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

import numpy as np
from PIL import Image as PILImage
from PIL import ImageDraw, ImageFilter
from tqdm import tqdm

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import db, ingest
from src.models import Case, Claimant

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

RAW_ROOT = Path("data/raw/data1a")
CURATED_DAMAGED = Path("data/curated/damaged")
CURATED_WHOLE = Path("data/curated/whole")
CURATED_MANIFEST = Path("data/curated/manifest.json")
NEAR_DUP_MANIFEST = Path("data/curated/near_dup_manifest.json")
EMBEDDING_CACHE = Path("data/curated/embedding_cache.npz")
EXTERNAL_CORPUS = Path("data/external/corpus")
AI_GENERATED_DIR = Path("data/ai_generated")
AI_GENERATED_UNDERWRITING_DIR = Path("data/ai_generated_underwriting")
GENERATED_DIR = Path("data/generated")
DIGITAL_EDIT_DIR = GENERATED_DIR / "digital_edit"
METADATA_FORGERY_DIR = GENERATED_DIR / "metadata_forgery"
GROUND_TRUTH_CSV = GENERATED_DIR / "ground_truth.csv"

SOURCE_EXTENSIONS = ("*.JPEG", "*.jpeg", "*.jpg", "*.JPG")
# The dataset's own docs describe extensions as uppercase .JPEG, but the
# files on disk are actually a mix of .JPEG/.jpeg/.jpg - glob all of them.

# The stated 300px-minimum-side rule turns out to drop 100% of
# 00-damage (this dataset's damage crops are natively ~180-280px on
# their short side) - a literal reading leaves zero damage photos to
# build any claims case from. Lowered to 150px, which still drops the
# genuinely tiny/degenerate tail (~1% of the corpus) without gutting an
# entire class; see the kept/dropped counts step0 prints for the real
# numbers this produces.
MIN_SIDE_PX = 150
EXTERNAL_CORPUS_SIZE = 400
DEFAULT_CASE_COUNT = 800
DEFAULT_SEED = 42

# Same thresholds as src/checks/duplicate.py's InternalDuplicateCheck
# CONCERN defaults, deliberately: dedupe_near_duplicates() exists to
# remove from the pool anything that check would flag as a duplicate
# between two independent cases, so using any other numbers here would
# just reopen the gap under a different threshold.
NEAR_DUP_HAMMING_CONCERN = 8
NEAR_DUP_COSINE_CONCERN = 0.95

ARCHETYPES = [
    "REUSE",
    "EXTERNAL_SOURCING",
    "DIGITAL_EDIT",
    "AI_GENERATED",
    "METADATA_FORGERY",
    "CONTEXT_MISMATCH",
    "THRESHOLD_GAMING",
]
# AI_GENERATED_BASELINE is deliberately absent from ARCHETYPES above.
# ARCHETYPES divides the claims-side fraud budget between archetypes that
# all describe a fraudulent *claim*; this one is an underwriting attack
# and is drawn from the underwriting pool instead (see
# AI_BASELINE_TOTAL). Adding it to that list would silently shrink every
# other archetype's count and mix an underwriting case into a claims
# denominator.
AI_BASELINE_TOTAL = 20

GAMING_BAND_INR = (45500.0, 49800.0)
GAMING_GARAGE_COUNT = 6
GAMING_LEGIT_PER_GARAGE = 15

# ---------------------------------------------------------------------------
# Step 2 - Indian context data
# ---------------------------------------------------------------------------

RTO_CODES = {
    "GJ01": "Ahmedabad",
    "GJ05": "Surat",
    "GJ06": "Vadodara",
    "GJ18": "Gandhinagar",
    "GJ27": "Ahmedabad East",
    "MH01": "Mumbai Central",
    "MH02": "Mumbai West",
    "MH12": "Pune",
}

# name, lat, lng, city - real Vadodara/Ahmedabad localities, >= 15 required.
LOCATIONS = [
    ("Alkapuri", 22.3072, 73.1812, "Vadodara"),
    ("Fatehgunj", 22.3178, 73.1957, "Vadodara"),
    ("Gotri", 22.3149, 73.1467, "Vadodara"),
    ("Manjalpur", 22.2762, 73.1943, "Vadodara"),
    ("Sayajigunj", 22.3126, 73.1900, "Vadodara"),
    ("Karelibaug", 22.3181, 73.2101, "Vadodara"),
    ("Akota", 22.2975, 73.1789, "Vadodara"),
    ("Vasna Road", 22.2809, 73.1751, "Vadodara"),
    ("Waghodia Road", 22.3241, 73.2367, "Vadodara"),
    ("Nizampura", 22.3251, 73.1889, "Vadodara"),
    ("Navrangpura", 23.0339, 72.5620, "Ahmedabad"),
    ("Bopal", 23.0326, 72.4661, "Ahmedabad"),
    ("Maninagar", 23.0058, 72.6019, "Ahmedabad"),
    ("Satellite", 23.0304, 72.5100, "Ahmedabad"),
    ("Vastrapur", 23.0368, 72.5289, "Ahmedabad"),
    ("Paldi", 23.0169, 72.5645, "Ahmedabad"),
    ("Chandkheda", 23.1039, 72.5972, "Ahmedabad"),
]

FIRST_NAMES = [
    "Aarav", "Vivaan", "Aditya", "Vihaan", "Arjun", "Sai", "Krishna", "Ishaan",
    "Rohan", "Kabir", "Ananya", "Diya", "Ishita", "Kavya", "Meera", "Priya",
    "Riya", "Saanvi", "Tanvi", "Zara", "Nikhil", "Rajesh", "Sanjay", "Mehul",
    "Bhavesh", "Falguni", "Hetal", "Jigna", "Kiran", "Nisha",
]
LAST_NAMES = [
    "Patel", "Shah", "Mehta", "Desai", "Trivedi", "Joshi", "Pandya", "Rana",
    "Chauhan", "Solanki", "Parikh", "Vyas", "Thakor", "Bhatt", "Modi", "Rathod",
]

GARAGE_CITIES = ["VAD", "AHM"]


def build_garages(rng: random.Random, total: int = 40) -> list[dict]:
    """40 garages split across two cities, GAR-VAD-01 style. Six are flagged
    "gaming" - this flag lives only in memory / the generator's own return
    value, never in the database (see module docstring: it's the answer key)."""
    garages = []
    for city in GARAGE_CITIES:
        for i in range(1, total // len(GARAGE_CITIES) + 1):
            garages.append({"garage_id": f"GAR-{city}-{i:02d}", "city": city, "is_gaming": False})
    for garage in rng.sample(garages, GAMING_GARAGE_COUNT):
        garage["is_gaming"] = True
    return garages


def random_registration(rng: random.Random) -> str:
    rto = rng.choice(list(RTO_CODES))
    series = "".join(rng.choice(string.ascii_uppercase) for _ in range(2))
    return f"{rto}{series}{rng.randint(1, 9999):04d}"


def random_claimant(rng: random.Random, index: int) -> Claimant:
    location = rng.choice(LOCATIONS)
    phone = f"{rng.choice('6789')}{''.join(rng.choice('0123456789') for _ in range(9))}"
    bank_account = "".join(rng.choice("0123456789") for _ in range(rng.choice([11, 14, 16])))
    return Claimant(
        claimant_id=f"CLM-{index:05d}",
        name=f"{rng.choice(FIRST_NAMES)} {rng.choice(LAST_NAMES)}",
        phone=phone,
        bank_account=bank_account,
        address=f"{rng.randint(1, 400)}, {location[0]}, {location[3]}",
    )


def sample_claim_amount(rng: random.Random) -> float:
    """
    Log-normal-ish, clipped to [8000, 80000]. Deliberately not centred
    near 50,000 - the threshold-gaming cluster needs a flat, unremarkable
    background to stand out against, not a coincidental spike the normal
    distribution happened to produce on its own.
    """
    amount = rng.lognormvariate(math.log(20000), 0.55)
    return round(min(max(amount, 8000.0), 80000.0) / 100) * 100


def sample_gaming_amount(rng: random.Random) -> float:
    return round(rng.uniform(*GAMING_BAND_INR) / 50) * 50


def _dates_in_last_12_months(reference: datetime) -> list:
    start = (reference - timedelta(days=365)).date()
    end = reference.date()
    return [start + timedelta(days=i) for i in range((end - start).days + 1)]


# India Standard Time. The declared timestamp's wall-clock is LOCAL time
# even though it is tagged UTC (see random_declared_time); this offset is
# what converts between the two, and it must match
# src/checks/scene_consistency.py::local_wallclock_to_utc or the generator
# and the check will disagree about where the sun was.
IST_OFFSET_HOURS = 5.5

# Civil twilight. Above this the sky is unambiguously lit.
CIVIL_TWILIGHT_DEG = -6.0

# Must match src/checks/scene_consistency.py's COMPASS ordering.
COMPASS_POINTS = ("N", "NE", "E", "SE", "S", "SW", "W", "NW")


def solar_elevation_local(day: date, hour: int, minute: int, latitude: float, longitude: float) -> Optional[float]:
    """
    Sun elevation in degrees for a LOCAL wall-clock time, or None if
    pysolar is unavailable.
    """
    try:
        from pysolar.solar import get_altitude
    except ImportError:
        return None
    naive = datetime(day.year, day.month, day.day, hour, minute)
    when_utc = (naive - timedelta(hours=IST_OFFSET_HOURS)).replace(tzinfo=timezone.utc)
    return float(get_altitude(latitude, longitude, when_utc))


def daylight_hours(day: date, latitude: float, longitude: float) -> list[int]:
    """
    Local hours on `day` at which the sun is above civil twilight.

    Falls back to a fixed 8..17 window if pysolar is missing, which is
    conservative for Gujarat year-round.
    """
    lit = [h for h in range(4, 21)
           if (e := solar_elevation_local(day, h, 30, latitude, longitude)) is not None
           and e > CIVIL_TWILIGHT_DEG]
    return lit or list(range(8, 18))


def random_declared_time(rng: random.Random, reference: datetime, months: Optional[set[int]] = None,
                          hour_choices: Optional[list[int]] = None,
                          latitude: Optional[float] = None, longitude: Optional[float] = None,
                          daylight_only: bool = False) -> datetime:
    """
    Incident/inspection time spread across the last 12 months (Open-Meteo
    needs dates that exist).

    daylight_only exists to fix a corpus bug that produced a predicted
    8.6% false-positive rate on scene_consistency. The hour used to be
    drawn uniformly from 7..19 and paired with an arbitrary daytime
    photograph, never checking the two agreed - so 48 of 560 clean cases
    declared a time at which the sun was actually below civil twilight
    while carrying a photo taken in broad daylight. Those are genuine
    physical contradictions sitting inside cases labelled clean, and the
    check was right to flag them; the label was wrong.

    So a clean case now samples its hour from the daylight window computed
    for its own date and coordinates. Fixed here rather than by dulling
    the check, because the signal is real and only the data was wrong.
    """
    days = _dates_in_last_12_months(reference)
    if months:
        days = [d for d in days if d.month in months] or days
    day = rng.choice(days)

    if hour_choices:
        hour = rng.choice(hour_choices)
        minute = rng.randint(0, 59)
    elif daylight_only and latitude is not None and longitude is not None:
        lit = daylight_hours(day, latitude, longitude)
        hour = rng.choice(lit)
        minute = rng.randint(0, 59)
        # daylight_hours() tests each hour at :30, but the minute is then
        # drawn across the whole hour - so the last lit hour can still
        # produce a timestamp past civil twilight (17:58 in December, say,
        # when 17:30 was fine). Verify the actual chosen instant and pull
        # it back into the window rather than trusting the proxy. This
        # boundary case was 13 of the 48 original bad clean cases; without
        # it the fix would look complete and would not be.
        elevation = solar_elevation_local(day, hour, minute, latitude, longitude)
        if elevation is not None and elevation <= CIVIL_TWILIGHT_DEG:
            safe = [h for h in lit if h != hour] or lit
            hour = rng.choice(safe)
            minute = rng.randint(0, 45)
    else:
        hour = rng.randint(7, 19)
        minute = rng.randint(0, 59)
    return datetime(day.year, day.month, day.day, hour, minute, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# Step 0 - normalise source images (idempotent)
# ---------------------------------------------------------------------------


def normalize_source_images() -> tuple[list[Path], list[Path]]:
    if CURATED_MANIFEST.exists():
        manifest = json.loads(CURATED_MANIFEST.read_text())
        print(f"[step0] already normalised - skipping (see {CURATED_MANIFEST})")
        for label, stats in manifest.items():
            print(f"        {label}: kept {stats['kept']}, dropped {stats['dropped']}")
        return (
            sorted(CURATED_DAMAGED.glob("*.jpg")),
            sorted(CURATED_WHOLE.glob("*.jpg")),
        )

    CURATED_DAMAGED.mkdir(parents=True, exist_ok=True)
    CURATED_WHOLE.mkdir(parents=True, exist_ok=True)

    def _find_source_images(category: str) -> list[Path]:
        found: set[Path] = set()
        for ext in SOURCE_EXTENSIONS:
            found.update(RAW_ROOT.glob(f"*/{category}/{ext}"))
        return sorted(found)

    sources = {
        "damaged": (_find_source_images("00-damage"), CURATED_DAMAGED),
        "whole": (_find_source_images("01-whole"), CURATED_WHOLE),
    }
    manifest: dict[str, dict] = {}
    results: dict[str, list[Path]] = {}

    for label, (src_paths, dest_dir) in sources.items():
        kept, dropped, seq = [], 0, 1
        for src_path in src_paths:
            try:
                with PILImage.open(src_path) as img:
                    img.load()
                    if min(img.size) < MIN_SIDE_PX:
                        dropped += 1
                        continue
                    dest_path = dest_dir / f"{label}_{seq:04d}.jpg"
                    img.convert("RGB").save(dest_path, format="JPEG", quality=95)
            except Exception:
                dropped += 1
                continue
            kept.append(dest_path)
            seq += 1
        print(f"[step0] {label}: kept {len(kept)}, dropped {dropped}")
        manifest[label] = {"kept": len(kept), "dropped": dropped}
        results[label] = kept

    CURATED_MANIFEST.write_text(json.dumps(manifest, indent=2))
    return results["damaged"], results["whole"]


def dedupe_by_content_hash(paths: list[Path], label: str) -> list[Path]:
    """
    Drops byte-identical images that survived normalisation under two
    different filenames - a real artifact of this dataset, not a
    hypothetical. Must run before external-corpus reservation and
    before any case draws a single image: a content duplicate that
    slips through here could hand the "same" photo to two different
    clean cases under two different names, which is exactly the
    disjointness rule's blind spot (see module docstring).
    """
    seen: set[str] = set()
    unique: list[Path] = []
    for path in paths:
        content_hash = ingest.compute_sha256(path)
        if content_hash in seen:
            continue
        seen.add(content_hash)
        unique.append(path)
    dropped = len(paths) - len(unique)
    if dropped:
        print(f"[step0b] {label}: dropped {dropped} byte-identical duplicate(s) under a different filename")
    return unique


def _load_near_dup_manifest() -> dict[str, dict]:
    if NEAR_DUP_MANIFEST.exists():
        return json.loads(NEAR_DUP_MANIFEST.read_text())
    return {}


def _save_near_dup_manifest(manifest: dict[str, dict]) -> None:
    NEAR_DUP_MANIFEST.write_text(json.dumps(manifest, indent=2))


def _reference_signature(reference_paths: list[Path]) -> str:
    """
    Short stable fingerprint of *which* images formed the reference set,
    stored alongside each manifest entry. Without this, extending
    dedupe_near_duplicates() to compare against a new reference set would
    be silently a no-op on any machine with an existing manifest: the
    cached "kept" list from a run that never saw the reference set would
    be reused verbatim, and the very images the extension exists to
    remove would stay in the pool. Keyed on names rather than content
    because the external corpus is populated by moving already-hashed
    curated files (see reserve_external_corpus), so a name change there
    means a different image.
    """
    joined = "|".join(sorted(p.name for p in reference_paths))
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()[:16]


def _load_embedding_cache() -> dict[str, tuple[str, np.ndarray]]:
    """
    Persistent pHash + CLIP embedding cache, keyed by path string.

    Not an optimisation so much as what makes this step iterable at all:
    embedding the ~2,200 images in the curated pool plus the external
    corpus takes hours on CPU (measured: ~3.5h for 1,845 images on this
    machine), and any change to the dedup logic - like adding the
    external corpus as a reference set - invalidates the manifest and
    would otherwise re-pay that cost in full every time. With this, only
    genuinely new images are embedded.
    """
    if not EMBEDDING_CACHE.exists():
        return {}
    try:
        data = np.load(EMBEDDING_CACHE, allow_pickle=False)
        keys = data["keys"]
        phashes = data["phashes"]
        embeddings = data["embeddings"]
    except Exception as e:  # noqa: BLE001 - a corrupt cache must never break the pipeline
        print(f"[step0c] embedding cache unreadable ({type(e).__name__}), recomputing from scratch")
        return {}
    return {str(k): (str(p), embeddings[i]) for i, (k, p) in enumerate(zip(keys, phashes))}


def _save_embedding_cache(cache: dict[str, tuple[str, np.ndarray]]) -> None:
    if not cache:
        return
    EMBEDDING_CACHE.parent.mkdir(parents=True, exist_ok=True)
    keys = sorted(cache)
    np.savez_compressed(
        EMBEDDING_CACHE,
        keys=np.array(keys),
        phashes=np.array([cache[k][0] for k in keys]),
        embeddings=np.stack([cache[k][1] for k in keys]),
    )


def _phash_and_embedding(
    path: Path, cache: dict[str, tuple[str, np.ndarray]]
) -> tuple[str, np.ndarray]:
    key = str(path)
    hit = cache.get(key)
    if hit is not None:
        return hit
    phash, _ = ingest.compute_hashes(path)
    embedding = np.asarray(ingest._default_embedder.embed(path), dtype=np.float64)
    cache[key] = (phash, embedding)
    return phash, embedding


def dedupe_near_duplicates(
    paths: list[Path],
    label: str,
    reference_paths: Optional[list[Path]] = None,
    hamming_concern: int = NEAR_DUP_HAMMING_CONCERN,
    cosine_concern: float = NEAR_DUP_COSINE_CONCERN,
) -> list[Path]:
    """
    Greedy near-duplicate removal, run once over the whole curated pool
    before any of it is drawn from (external corpus reservation or case
    assignment): walk `paths` in order, and for each image, keep it only
    if it is not within `hamming_concern` pHash distance OR
    `cosine_concern` CLIP cosine similarity of any image already kept.
    "Greedy" and order-dependent by design, same as
    dedupe_by_content_hash() - given a cluster of three near-identical
    photos, the first one seen survives and the other two are dropped,
    not some notion of "the best" one; which one that is doesn't matter
    for this dataset's purposes, only that at most one of them ends up in
    the pool clean cases draw from.

    `reference_paths` seeds the comparison set with images that are
    themselves never returned - used to pass data/external/corpus/. The
    external corpus is reserved (physically moved out of the curated
    pool) *before* this function runs, so without it those 400 images
    were never compared against the pool that stays behind: a clean case
    could draw a photo that is a near-duplicate of an EXTERNAL_SOURCING
    case's photo, and InternalDuplicateCheck would correctly link the
    two. That is exactly what scripts/evaluate_checks.py measured as the
    2 residual EXTERNAL_SOURCING matches. Seeding them here removes the
    pool side of any such pair while leaving the corpus itself intact -
    the corpus must keep those images, since EXTERNAL_SOURCING cases are
    built from them.

    Cached in NEAR_DUP_MANIFEST the same way normalize_source_images()
    caches in CURATED_MANIFEST. The cached entry records which reference
    set produced it (see _reference_signature) and is ignored when that
    changes - otherwise extending the reference set would be silently a
    no-op against an existing manifest. Per-image pHash/embedding work is
    cached separately and more durably in EMBEDDING_CACHE, so an
    invalidated manifest costs a re-run of the comparison, not a re-run
    of hours of CLIP inference.
    """
    reference_paths = reference_paths or []
    signature = _reference_signature(reference_paths)

    manifest = _load_near_dup_manifest()
    entry = manifest.get(label)
    if entry is not None and entry.get("reference_signature") == signature:
        kept_names = set(entry["kept"])
        kept = [p for p in paths if p.name in kept_names]
        print(
            f"[step0c] {label}: already deduplicated (cached) - "
            f"{len(kept)} kept, {entry['removed']} removed previously"
        )
        return kept
    if entry is not None:
        print(f"[step0c] {label}: cached result ignored - reference set changed, recomputing")

    cache = _load_embedding_cache()
    cache_size_before = len(cache)

    total = len(reference_paths) + len(paths)
    kept_paths: list[Path] = []
    kept_phash: list[str] = []
    kept_matrix = np.zeros((total, 512), dtype=np.float64)
    count = 0
    removed = 0
    removed_vs_reference = 0

    # Reference images occupy the comparison set from the start but are
    # never appended to kept_paths - they are a filter, not candidates.
    for path in tqdm(reference_paths, desc=f"embed reference ({label})", unit="image"):
        phash, embedding = _phash_and_embedding(path, cache)
        kept_phash.append(phash)
        kept_matrix[count] = embedding
        count += 1
    reference_count = count

    for path in tqdm(paths, desc=f"dedupe near-duplicates ({label})", unit="image"):
        phash, embedding = _phash_and_embedding(path, cache)

        matched_index = -1
        if count:
            # Embeddings are L2-normalised (see CLIPEmbedder.embed's own
            # docstring), so this one matrix-vector product against every
            # already-kept image at once IS cosine similarity - far
            # cheaper than calling ingest.cosine_similarity() in a
            # per-pair Python loop over a set that can be thousands long.
            cosines = kept_matrix[:count] @ embedding
            best = int(np.argmax(cosines))
            if float(cosines[best]) >= cosine_concern:
                matched_index = best
            else:
                for i, other_phash in enumerate(kept_phash):
                    if ingest.hamming_distance(phash, other_phash) <= hamming_concern:
                        matched_index = i
                        break

        if matched_index >= 0:
            removed += 1
            if matched_index < reference_count:
                removed_vs_reference += 1
            continue

        kept_paths.append(path)
        kept_phash.append(phash)
        kept_matrix[count] = embedding
        count += 1

    if len(cache) != cache_size_before:
        _save_embedding_cache(cache)

    kept_count = count - reference_count
    reference_note = (
        f" ({removed_vs_reference} of them matching the {len(reference_paths)}-image reference set)"
        if reference_paths
        else ""
    )
    print(
        f"[step0c] {label}: removed {removed} near-duplicate(s){reference_note} "
        f"(Hamming<={hamming_concern} or cosine>={cosine_concern}), {kept_count} remain"
    )

    manifest[label] = {
        "kept": [p.name for p in kept_paths],
        "removed": removed,
        "removed_vs_reference": removed_vs_reference,
        "reference_signature": signature,
        "reference_count": len(reference_paths),
    }
    _save_near_dup_manifest(manifest)
    return kept_paths


# ---------------------------------------------------------------------------
# Step 1 - reserve the external corpus
# ---------------------------------------------------------------------------


def reserve_external_corpus(damaged_pool: list[Path], seed: int) -> tuple[list[Path], set[str]]:
    """
    Moves EXTERNAL_CORPUS_SIZE damaged images into data/external/corpus/,
    physically out of the curated pool, and returns the explicit
    exclusion set (by filename) alongside the shrunken pool. Enforced by
    the move itself, not by convention - nothing downstream can
    accidentally hand out an external-corpus image as a "genuine" one
    because it is no longer sitting in data/curated/damaged/ to be handed
    out.
    """
    EXTERNAL_CORPUS.mkdir(parents=True, exist_ok=True)
    already_reserved = sorted(EXTERNAL_CORPUS.glob("*.jpg"))
    if already_reserved:
        reserved_names = {p.name for p in already_reserved}
        remaining = [p for p in damaged_pool if p.name not in reserved_names]
        print(f"[step1] external corpus already reserved ({len(already_reserved)} images) - skipping")
        return remaining, reserved_names

    rng = random.Random(seed)
    chosen = rng.sample(damaged_pool, min(EXTERNAL_CORPUS_SIZE, len(damaged_pool)))
    chosen_names = {p.name for p in chosen}
    for src in chosen:
        shutil.move(str(src), str(EXTERNAL_CORPUS / src.name))
    remaining = [p for p in damaged_pool if p.name not in chosen_names]
    print(f"[step1] moved {len(chosen)} damaged images to {EXTERNAL_CORPUS}")
    return remaining, chosen_names


# ---------------------------------------------------------------------------
# Archetype image production
# ---------------------------------------------------------------------------


# Quality the finished composite is saved at. Single save, and higher
# than the host images' own encoding, so the composite does not impose a
# fresh uniform quantisation over the whole frame.
DIGITAL_EDIT_SAVE_QUALITY = 92

# Quality the pasted patch is pre-compressed at in the "recompressed_patch"
# variant. Deliberately far from DIGITAL_EDIT_SAVE_QUALITY: the point is
# for the spliced region to carry a visibly different compression history
# from its host, which is exactly what JPEG-ghost analysis looks for.
DIGITAL_EDIT_PATCH_QUALITY = 55


def make_digital_edit_composite(
    damage_source: Path, whole_base: Path, dest_path: Path, rng: random.Random,
    recompress_patch: bool = False,
) -> dict[str, Any]:
    """
    Paste a damage crop onto an undamaged car under a feathered elliptical
    mask, and save the result ONCE.

    Why this changed, because it matters and is easy to undo by accident:

    The previous version re-saved the whole composite at quality 85 twice.
    That was intended to add "generation-loss artifacts a genuine phone
    photo won't have", but it did the opposite of what the forensics need.
    Re-encoding the *entire frame* at one quality gives every 8x8 block the
    same, most recent compression history - which is precisely the thing
    JPEG-ghost analysis tests for the absence of. The forgery ironed its own
    evidence flat. Measured result: src/checks/digital_edit.py scored AUC
    0.531 with the ghost signal *inverted* at 0.331, i.e. edited images
    looked MORE compression-uniform than honest ones.

    So now:

      - one save, at DIGITAL_EDIT_SAVE_QUALITY, so the host's own history
        survives instead of being overwritten; and
      - for half the cases (recompress_patch=True), the patch is pushed
        through its own compression cycle at DIGITAL_EDIT_PATCH_QUALITY
        *before* being pasted, so the spliced region genuinely carries a
        different history from its surroundings.

    The two variants are recorded in fraud_metadata so evaluation can
    report detection per variant: "recompressed_patch" should be findable
    by ghost analysis, "single_save" only by noise or edge signals. If the
    detector catches one and not the other, that is a real result about
    which mechanism works, not a single opaque recall number.

    The feathered mask is kept exactly as it was. It is realistic - a
    careless forger leaves a hard edge, a careful one feathers - and
    keeping it means the edge-discontinuity signal still faces the harder
    case rather than being handed an easy win.
    """
    with PILImage.open(whole_base) as base_img, PILImage.open(damage_source) as damage_img:
        base = base_img.convert("RGB")
        damage = damage_img.convert("RGB")

        bw, bh = base.size
        dw, dh = damage.size
        patch_w = max(min(dw, bw) // 2, 40)
        patch_h = max(min(dh, bh) // 2, 40)
        px = rng.randint(0, max(0, dw - patch_w))
        py = rng.randint(0, max(0, dh - patch_h))
        patch = damage.crop((px, py, px + patch_w, py + patch_h))

        if recompress_patch:
            # The patch alone goes through its own JPEG cycle, so its
            # quantisation signature differs from the host's.
            patch_buffer = io.BytesIO()
            patch.save(patch_buffer, format="JPEG", quality=DIGITAL_EDIT_PATCH_QUALITY)
            patch_buffer.seek(0)
            with PILImage.open(patch_buffer) as recompressed:
                patch = recompressed.convert("RGB").copy()

        mask = PILImage.new("L", (patch_w, patch_h), 0)
        ImageDraw.Draw(mask).ellipse((0, 0, patch_w, patch_h), fill=255)
        mask = mask.filter(ImageFilter.GaussianBlur(radius=max(4, patch_w // 15)))

        tx = rng.randint(0, max(0, bw - patch_w))
        ty = rng.randint(bh // 3, max(bh // 3, bh - patch_h))

        composite = base.copy()
        composite.paste(patch, (tx, ty), mask)

    # ONE save. No second cycle.
    composite.save(dest_path, format="JPEG", quality=DIGITAL_EDIT_SAVE_QUALITY)

    return {
        "variant": "recompressed_patch" if recompress_patch else "single_save",
        "save_quality": DIGITAL_EDIT_SAVE_QUALITY,
        "patch_quality": DIGITAL_EDIT_PATCH_QUALITY if recompress_patch else None,
        "recompress_cycles": 1,
        "patch_box": [tx, ty, tx + patch_w, ty + patch_h],
    }


# ---------------------------------------------------------------------------
# Scene heuristics - used to build CONTEXT_MISMATCH around what a photo
# actually shows, instead of relabelling an arbitrary one.
#
# The previous CONTEXT_MISMATCH changed the declared date or hour and
# attached whatever damaged-car photo came next off the stack. That made
# the archetype unfalsifiable: measured on the 9 cases perception reached,
# all 9 photographs showed clear skies and dry ground - including the 5
# labelled "declared monsoon rain but dry-season date". There was nothing
# in the evidence to contradict, so no weather check could ever find it,
# and recall against the archetype measured how often the corpus happened
# to attach a suitable photo rather than how well the physics worked.
#
# These heuristics are deliberately crude and cheap - mean brightness,
# blue dominance, ground saturation, directional shadow energy. They do
# not need to be accurate; they need to be good enough to *sort* photos so
# the declaration can be built around one whose visible conditions the
# declaration will contradict. The check under test never sees them.
# ---------------------------------------------------------------------------


def scene_features(path: Path) -> Optional[dict[str, float]]:
    """
    Cheap visual descriptors for one image, or None if unreadable.

    brightness      : mean luma, 0-255
    blue_dominance  : how much the top third leans blue - a clear-sky proxy
    sky_brightness  : mean luma of the top third
    ground_saturation: mean saturation of the bottom third; wet asphalt is
                       darker and less saturated than dry, dusty ground
    ground_darkness : 1 - (bottom-third luma / 255); wet ground reads dark
    shadow_energy   : share of strong directional gradients in the bottom
                      two thirds - a standing-shadow proxy
    """
    try:
        import cv2
        import numpy as np
    except ImportError:
        return None

    bgr = cv2.imread(str(path), cv2.IMREAD_COLOR)
    if bgr is None or bgr.size == 0:
        return None

    h, w = bgr.shape[:2]
    if h < 30 or w < 30:
        return None

    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY).astype("float32")

    top = bgr[: h // 3]
    bottom = bgr[2 * h // 3 :]
    bottom_hsv = hsv[2 * h // 3 :]

    blue = float(top[:, :, 0].mean())
    red = float(top[:, :, 2].mean())
    green = float(top[:, :, 1].mean())

    gx = cv2.Sobel(gray, cv2.CV_32F, 1, 0, ksize=3)
    gy = cv2.Sobel(gray, cv2.CV_32F, 0, 1, ksize=3)
    magnitude = (gx * gx + gy * gy) ** 0.5
    lower = magnitude[h // 3 :]
    cut = float(lower.mean()) * 2.5 if lower.size else 0.0

    return {
        "brightness": float(gray.mean()),
        "sky_brightness": float(cv2.cvtColor(top, cv2.COLOR_BGR2GRAY).mean()),
        "blue_dominance": blue - (red + green) / 2.0,
        "ground_saturation": float(bottom_hsv[:, :, 1].mean()),
        "ground_darkness": 1.0 - float(cv2.cvtColor(bottom, cv2.COLOR_BGR2GRAY).mean()) / 255.0,
        "shadow_energy": float((lower > cut).mean()) if lower.size and cut > 0 else 0.0,
    }


# Ranking, not thresholding. Measured over 200 curated damaged-car photos:
#
#   brightness       p10  83.5  med 115.0  p90 140.8
#   sky_brightness   p10  77.9  med 132.0  p90 174.4
#   blue_dominance   p10 -19.1  med   1.6  p90  19.4
#   ground_darkness  p10  0.40  med  0.64  p90  0.77
#   shadow_energy    p10  0.08  med  0.11  p90  0.12
#
# Absolute cutoffs on these were a mistake: ground_darkness sits high on
# almost every frame because a damage close-up's lower third is car body,
# not ground, so a "dry ground" threshold rejected essentially everything.
# What the generator actually needs is not "is this photo dry?" but "which
# of these photos is the *most* dry-and-clear-looking", and a score
# answers that without pretending to a precision these features do not
# have. Only the ordering is load-bearing.


def dry_clear_score(f: dict[str, float]) -> float:
    """Higher = more convincingly a bright, dry, clear-sky scene."""
    return (
        (f["brightness"] - 115.0) / 30.0
        + (f["sky_brightness"] - 132.0) / 50.0
        + (f["blue_dominance"] - 1.6) / 20.0
        + (0.64 - f["ground_darkness"]) / 0.2
    )


def shadow_score(f: dict[str, float]) -> float:
    """Higher = stronger directional shadow structure in a well-lit scene."""
    return (
        (f["shadow_energy"] - 0.11) / 0.02
        + (f["brightness"] - 115.0) / 60.0
    )


# ---------------------------------------------------------------------------
# Real rain dates, for CONTEXT_MISMATCH variant (a)
#
# Variant (a) needs a declared date on which it *demonstrably* rained hard
# at the declared coordinates, so that a photograph showing dry ground and
# clear sky is a genuine contradiction rather than a guess. The same
# Open-Meteo archive the check queries is used here, so generator and
# check agree by construction on what the weather was.
#
# Cached to disk: the archive is a free public service and this asks for
# one year per location, which should happen once rather than on every
# regeneration.
# ---------------------------------------------------------------------------

RAIN_DATES_CACHE = Path("data/cache/rain_dates.json")
RAINY_HOURS_CACHE = Path("data/cache/rainy_hours.json")
# Where the regeneration wrapper parks the perception export so this
# module can still align clean declarations after the database is dropped.
PERCEPTION_EXPORT = Path("data/cache/perception_export.json")
# mm in a single hour above which rain is "demonstrably falling" rather
# than a trace. Deliberately low: the check's own DRY_MM floor is 0.1 mm
# per day, so anything meaningfully above drizzle qualifies.
RAINY_HOUR_MM = 0.5
HEAVY_RAIN_MM = 10.0


def heavy_rain_dates(latitude: float, longitude: float, reference: datetime) -> list[date]:
    """
    Dates in the last 12 months with more than HEAVY_RAIN_MM of rain at
    this location. Returns [] if the archive cannot be reached - callers
    must cope, because a generator that silently produced an
    undetectable archetype is exactly the failure being fixed here.
    """
    RAIN_DATES_CACHE.parent.mkdir(parents=True, exist_ok=True)
    key = f"{latitude:.2f},{longitude:.2f}"
    cache: dict[str, list[str]] = {}
    if RAIN_DATES_CACHE.exists():
        try:
            cache = json.loads(RAIN_DATES_CACHE.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            cache = {}
    if key in cache:
        return [date.fromisoformat(d) for d in cache[key]]

    days = _dates_in_last_12_months(reference)
    start, end = days[0].isoformat(), days[-1].isoformat()
    try:
        import requests

        response = requests.get(
            "https://archive-api.open-meteo.com/v1/archive",
            params={
                "latitude": round(latitude, 2), "longitude": round(longitude, 2),
                "start_date": start, "end_date": end,
                "daily": "precipitation_sum", "timezone": "UTC",
            },
            timeout=30.0,
        )
        response.raise_for_status()
        daily = response.json().get("daily", {})
        times = daily.get("time", []) or []
        sums = daily.get("precipitation_sum", []) or []
        wet = [t for t, mm in zip(times, sums) if mm is not None and mm > HEAVY_RAIN_MM]
    except Exception as e:  # noqa: BLE001 - offline, rate-limited, malformed
        print(f"[context] rain lookup failed for {key}: {type(e).__name__}: {e}", file=sys.stderr)
        return []

    cache[key] = wet
    RAIN_DATES_CACHE.write_text(json.dumps(cache), encoding="utf-8")
    return [date.fromisoformat(d) for d in wet]


def dry_dates(latitude: float, longitude: float, reference: datetime) -> list[date]:
    """
    Dates in the last 12 months with essentially no rain at this location.

    Task-3 counterpart to heavy_rain_dates(). Clean cases must not carry a
    declared date whose recorded weather contradicts their own photograph,
    and the overwhelming majority of curated photos show dry ground under
    a clear sky - so a clean case's date should be one on which it did not
    rain. Uses the same archive and the same cache file the check will
    later query, so generator and check cannot disagree about what the
    weather was.
    """
    key = f"dry:{latitude:.2f},{longitude:.2f}"
    cache: dict[str, list[str]] = {}
    if RAIN_DATES_CACHE.exists():
        try:
            cache = json.loads(RAIN_DATES_CACHE.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            cache = {}
    if key in cache:
        return [date.fromisoformat(d) for d in cache[key]]

    days = _dates_in_last_12_months(reference)
    try:
        import requests

        response = requests.get(
            "https://archive-api.open-meteo.com/v1/archive",
            params={
                "latitude": round(latitude, 2), "longitude": round(longitude, 2),
                "start_date": days[0].isoformat(), "end_date": days[-1].isoformat(),
                "daily": "precipitation_sum", "timezone": "UTC",
            },
            timeout=30.0,
        )
        response.raise_for_status()
        daily = response.json().get("daily", {})
        dry = [
            t for t, mm in zip(daily.get("time", []) or [], daily.get("precipitation_sum", []) or [])
            if mm is not None and mm < 0.1
        ]
    except Exception as e:  # noqa: BLE001
        print(f"[clean] dry-date lookup failed for {key}: {type(e).__name__}: {e}", file=sys.stderr)
        return []

    cache[key] = dry
    RAIN_DATES_CACHE.parent.mkdir(parents=True, exist_ok=True)
    RAIN_DATES_CACHE.write_text(json.dumps(cache), encoding="utf-8")
    return [date.fromisoformat(d) for d in dry]


def hour_matching_shadow(day: date, latitude: float, longitude: float,
                          shadow_direction: str) -> Optional[int]:
    """
    The local daylight hour whose solar geometry best matches an observed
    shadow bearing, or None if the direction carries no information.

    Third and last axis of the same corpus fix. The lighting axis was
    corrected first (clean-case hours drawn from the daylight window),
    which then exposed the identical flaw here: a clean case's declared
    time had no relation to the direction the shadows in its photograph
    actually fall, so scene_consistency's solar-geometry sub-check
    correctly flagged honest cases as contradictions.

    Shadows point opposite the sun, so the target solar azimuth is the
    observed shadow bearing + 180 degrees; this returns the daylight hour
    that comes closest to it.
    """
    if not shadow_direction or shadow_direction.strip().upper() not in COMPASS_POINTS:
        return None
    observed = COMPASS_POINTS.index(shadow_direction.strip().upper()) * 45.0
    target_sun_azimuth = (observed + 180.0) % 360.0

    try:
        from pysolar.solar import get_azimuth
    except ImportError:
        return None

    best_hour, best_gap = None, 999.0
    for hour in daylight_hours(day, latitude, longitude):
        naive = datetime(day.year, day.month, day.day, hour, 30)
        when_utc = (naive - timedelta(hours=IST_OFFSET_HOURS)).replace(tzinfo=timezone.utc)
        azimuth = float(get_azimuth(latitude, longitude, when_utc)) % 360.0
        gap = abs((azimuth - target_sun_azimuth + 180.0) % 360.0 - 180.0)
        if gap < best_gap:
            best_hour, best_gap = hour, gap
    # Only accept a genuinely close match; the check allows 90 degrees of
    # slack, so landing inside 45 leaves real margin.
    return best_hour if best_gap <= 45.0 else None


def rainy_hours(latitude: float, longitude: float, day: date) -> list[int]:
    """
    Local hours on `day` during which rain was actually falling.

    This exists because the previous variant (a) was undetectable by
    construction and the reason was subtle. It picked a date whose DAILY
    precipitation total was high and declared an arbitrary daylight hour
    on it. But scene_consistency deliberately refuses to treat "clear
    photograph on a rainy day" as a contradiction, and it is right to:
    monsoon rain in Gujarat is intermittent, so 30 mm spread across a day
    is entirely compatible with a dry, bright hour at the declared
    minute. Firing there would accuse honest claimants of photographing
    their car between showers.

    So the generator now has to meet the check's standard rather than the
    check being lowered to the generator's. Declaring an hour in which
    rain was demonstrably falling makes "the photograph shows dry ground
    and clear sky" a genuine contradiction that the check can act on
    without guessing.

    Returns local hours (IST) whose hourly precipitation exceeds
    RAINY_HOUR_MM. Empty if the archive cannot be reached.
    """
    key = f"{latitude:.2f},{longitude:.2f}@{day.isoformat()}"
    cache: dict[str, list[int]] = {}
    if RAINY_HOURS_CACHE.exists():
        try:
            cache = json.loads(RAINY_HOURS_CACHE.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            cache = {}
    if key in cache:
        return cache[key]

    try:
        import requests

        response = requests.get(
            "https://archive-api.open-meteo.com/v1/archive",
            params={
                "latitude": round(latitude, 2), "longitude": round(longitude, 2),
                "start_date": day.isoformat(), "end_date": day.isoformat(),
                "hourly": "precipitation", "timezone": "UTC",
            },
            timeout=30.0,
        )
        response.raise_for_status()
        hourly = response.json().get("hourly", {})
        times = hourly.get("time", []) or []
        values = hourly.get("precipitation", []) or []
    except Exception as e:  # noqa: BLE001
        print(f"[context] hourly rain lookup failed for {key}: {type(e).__name__}: {e}", file=sys.stderr)
        return []

    wet_local: list[int] = []
    for stamp, mm in zip(times, values):
        if mm is None or mm <= RAINY_HOUR_MM:
            continue
        try:
            utc_hour = int(stamp[11:13])
        except (ValueError, IndexError):
            continue
        # Open-Meteo was asked for UTC; the declared wall-clock is local.
        local_hour = int((utc_hour + IST_OFFSET_HOURS) % 24)
        wet_local.append(local_hour)

    wet_local = sorted(set(wet_local))
    cache[key] = wet_local
    RAINY_HOURS_CACHE.parent.mkdir(parents=True, exist_ok=True)
    RAINY_HOURS_CACHE.write_text(json.dumps(cache), encoding="utf-8")
    return wet_local


def sunset_hour(day: date, latitude: float, longitude: float) -> int:
    """
    The last local hour on `day` at which the sun is still above civil
    twilight. Used by CONTEXT_MISMATCH variant (b): declaring the hour
    *after* this one means the photograph's strong shadows and daylight
    contradict a claim made after dark.
    """
    lit = daylight_hours(day, latitude, longitude)
    return lit[-1] if lit else 18


def _to_dms_rational(value: float) -> tuple:
    deg = int(abs(value))
    minutes_full = (abs(value) - deg) * 60
    minutes = int(minutes_full)
    seconds = round((minutes_full - minutes) * 60 * 100)
    return ((deg, 1), (minutes, 1), (seconds, 100))


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlambda / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def forge_exif(source: Path, dest_path: Path, declared_lat: float, declared_lon: float,
               declared_time: datetime, rng: random.Random) -> dict[str, Any]:
    """
    Copies `source` to `dest_path` with EXIF written via piexif: GPS in a
    city other than the declared one, and a capture timestamp offset a
    few hours from the declared incident time. Returns the fraud_metadata
    describing exactly what was forged, so evaluation can check whether
    Check 8 caught the right thing.
    """
    import piexif

    far_locations = [loc for loc in LOCATIONS if _haversine_km(loc[1], loc[2], declared_lat, declared_lon) > 50]
    forged = rng.choice(far_locations or LOCATIONS)
    hour_offset = rng.choice([-6, -5, -4, 4, 5, 6])
    forged_time = declared_time + timedelta(hours=hour_offset)

    with PILImage.open(source) as img:
        img.convert("RGB").save(dest_path, format="JPEG", quality=95)

    exif_dict = {
        "0th": {},
        "Exif": {piexif.ExifIFD.DateTimeOriginal: forged_time.strftime("%Y:%m:%d %H:%M:%S").encode()},
        "GPS": {
            piexif.GPSIFD.GPSLatitudeRef: b"N" if forged[1] >= 0 else b"S",
            piexif.GPSIFD.GPSLatitude: _to_dms_rational(forged[1]),
            piexif.GPSIFD.GPSLongitudeRef: b"E" if forged[2] >= 0 else b"W",
            piexif.GPSIFD.GPSLongitude: _to_dms_rational(forged[2]),
        },
        "1st": {},
        "thumbnail": None,
    }
    piexif.insert(piexif.dump(exif_dict), str(dest_path))

    return {
        "forged_gps": {"lat": forged[1], "lon": forged[2], "locality": f"{forged[0]}, {forged[3]}"},
        "declared_gps": {"lat": declared_lat, "lon": declared_lon},
        "forged_timestamp": forged_time.isoformat(),
        "declared_timestamp": declared_time.isoformat(),
        "hour_offset": hour_offset,
    }


# ---------------------------------------------------------------------------
# Step 3 - case specs
# ---------------------------------------------------------------------------


@dataclass
class CaseSpec:
    """Staging record for one generated case - not a models.py entity.
    Everything except fraud_metadata gets written to the database (via
    a real Case); fraud_metadata goes only to ground_truth.csv."""

    case_id: str
    agent_type: str
    archetype: str  # "CLEAN" or one of ARCHETYPES
    claimant: Claimant
    garage_id: str
    declared_time: datetime
    declared_location: str
    latitude: float
    longitude: float
    claim_type: str
    claim_amount: Optional[float]
    vehicle_registration: str
    image_paths: list[Path] = field(default_factory=list)
    fraud_metadata: dict[str, Any] = field(default_factory=dict)


def align_clean_declarations(specs: list["CaseSpec"], rng: random.Random,
                              reference: datetime, db_path: str) -> dict[str, int]:
    """
    Make every clean case's declaration agree with its own photograph.

    Third pass of the same fix, applied on the two axes the first pass did
    not reach. The lighting axis was corrected inside random_declared_time
    (clean hours drawn from the daylight window, 48/560 bad -> 0/560).
    Correcting it exposed the identical flaw on two more:

      weather  - a clean case could declare a date on which heavy rain
                 fell while its photograph shows dry ground and clear sky
      shadows  - a clean case's declared hour had no relation to the
                 direction the shadows in its photograph actually fall

    Both produced scene_consistency CONCERNs on clean cases that were
    *correct detections* of contradictions the generator had created by
    accident. The fix belongs here, not in the check: the signal is real
    and only the label was wrong.

    Where a perception record already exists for the case's first image,
    its observed weather and shadow direction drive the declaration.
    Where none exists - most of the corpus, since vision quota is the
    binding constraint - the photograph is assumed dry and clear, which
    matches the overwhelming majority of the curated pool, and only the
    date is constrained.

    Returns per-axis counts of what was corrected.
    """
    stats = {"weather_aligned": 0, "shadow_aligned": 0, "no_dry_dates": 0, "perception_used": 0}

    # Perception is read from the live database when there is one, and
    # otherwise from the export the regeneration wrapper leaves behind.
    #
    # That fallback is not belt-and-braces, it is load-bearing. A full
    # regeneration drops the database *before* generation runs, so by the
    # time this function executes the perception table is empty and every
    # clean case would silently fall back to "assume dry and clear" -
    # exactly the alignment this pass exists to do properly. The wrapper
    # (scripts/regenerate_preserving_perception.py) writes the export to
    # PERCEPTION_EXPORT first for this reason; records are keyed by image
    # sha256, so they stay valid across the reshuffle.
    perception: dict[str, dict] = {}
    try:
        conn = db.connect(db_path)
        for row in conn.execute(
            "SELECT content_hash, weather_observed, shadow_direction FROM perception_records"
        ):
            perception[row[0]] = {"weather": row[1], "shadow": row[2]}
        conn.close()
    except Exception:  # noqa: BLE001 - table may not exist yet
        perception = {}

    if not perception and PERCEPTION_EXPORT.exists():
        try:
            for row in json.loads(PERCEPTION_EXPORT.read_text(encoding="utf-8")):
                perception[row["content_hash"]] = {
                    "weather": row.get("weather_observed"),
                    "shadow": row.get("shadow_direction"),
                }
            print(f"[clean] using {len(perception)} perception record(s) from {PERCEPTION_EXPORT}")
        except (OSError, json.JSONDecodeError, KeyError, TypeError):
            perception = {}

    dry_cache: dict[tuple[float, float], list[date]] = {}
    wet_cache: dict[tuple[float, float], list[date]] = {}

    for spec in specs:
        if spec.archetype != "CLEAN" or not spec.image_paths:
            continue

        key = (round(spec.latitude, 2), round(spec.longitude, 2))
        observed = None
        if perception:
            try:
                first_hash = ingest.compute_sha256(spec.image_paths[0])
            except Exception:  # noqa: BLE001
                first_hash = None
            if first_hash and first_hash in perception:
                observed = perception[first_hash]
                stats["perception_used"] += 1

        wants_wet = bool(observed) and (observed["weather"] or "").strip().lower() in {"rain", "wet_ground"}

        if wants_wet:
            if key not in wet_cache:
                wet_cache[key] = heavy_rain_dates(spec.latitude, spec.longitude, reference)
            pool = wet_cache[key]
        else:
            if key not in dry_cache:
                dry_cache[key] = dry_dates(spec.latitude, spec.longitude, reference)
            pool = dry_cache[key]

        if not pool:
            stats["no_dry_dates"] += 1
            continue

        day = rng.choice(pool)
        stats["weather_aligned"] += 1

        hour = None
        if observed:
            hour = hour_matching_shadow(day, spec.latitude, spec.longitude, observed["shadow"] or "")
            if hour is not None:
                stats["shadow_aligned"] += 1
        if hour is None:
            hour = rng.choice(daylight_hours(day, spec.latitude, spec.longitude))

        spec.declared_time = datetime(
            day.year, day.month, day.day, hour, rng.randint(0, 45), tzinfo=timezone.utc
        )

    return stats



# Interval between a corrupted baseline inspection and the claim it was
# created to legitimise. Short enough that the two records contradict each
# other, long enough not to look immediately staged.
BASELINE_CLAIM_GAP_DAYS = (5, 25)


def link_baseline_inspections_to_claims(specs: list, rng) -> list[dict]:
    """
    Give each AI_GENERATED_BASELINE inspection a matching later claim.

    The baseline-corruption attack's real signature is temporal rather than
    visual: a vehicle certified undamaged at inception that claims for damage
    weeks later. Neither the inspection nor the claim is detectable alone -
    both are internally consistent - so the contradiction exists only in the
    relationship between two cases.

    The corpus originally assigned every case a unique registration, which
    made that relationship impossible to express and left
    src/checks/baseline_linkage.py with nothing to join on. This pass gives
    each inspection a claims counterpart sharing its registration, dated
    BASELINE_CLAIM_GAP_DAYS later.

    The claim chosen is an existing fraud case rather than a clean one: the
    claimant really is claiming for damage they concealed, so labelling it
    clean would be wrong. Its own archetype is preserved - a case can be
    both, and the linkage label is recorded in fraud_metadata rather than by
    changing the archetype, so no existing recall denominator moves.

    Returns the link records, for the ground-truth CSV.
    """
    inspections = [s for s in specs
                   if s.archetype == "AI_GENERATED_BASELINE"]
    # Claims with real damage: a linked claim has to be claiming for
    # something, and these archetypes carry damaged vehicle imagery.
    claimable = [s for s in specs
                 if s.agent_type == "claims"
                 and s.archetype in ("EXTERNAL_SOURCING", "CONTEXT_MISMATCH",
                                     "DIGITAL_EDIT", "REUSE")]
    rng.shuffle(claimable)

    links = []
    for inspection, claim in zip(inspections, claimable):
        gap = rng.randint(*BASELINE_CLAIM_GAP_DAYS)
        claim.vehicle_registration = inspection.vehicle_registration
        if getattr(inspection, "declared_time", None) is not None:
            claim.declared_time = inspection.declared_time + timedelta(days=gap)
        meta = dict(getattr(claim, "fraud_metadata", None) or {})
        meta["linked_baseline_inspection"] = inspection.case_id
        meta["days_after_inspection"] = gap
        meta["linkage_note"] = (
            "This claim is the payoff for the corrupted baseline established in the "
            "linked inspection. Its own archetype is unchanged; the linkage is "
            "additional ground truth, not a relabelling."
        )
        claim.fraud_metadata = meta
        links.append({
            "inspection_case": inspection.case_id,
            "claim_case": claim.case_id,
            "vehicle_registration": inspection.vehicle_registration,
            "days_after_inspection": gap,
        })
    return links


def build_case_specs(
    count: int,
    rng: random.Random,
    damaged_pool: list[Path],
    whole_pool: list[Path],
    external_names: set[str],
    garages: list[dict],
) -> tuple[list[CaseSpec], list[str]]:
    reference_now = datetime.now(timezone.utc)

    damaged_stack = list(damaged_pool)
    rng.shuffle(damaged_stack)
    whole_stack = list(whole_pool)
    rng.shuffle(whole_stack)
    external_stack = sorted(EXTERNAL_CORPUS.glob("*.jpg"))
    rng.shuffle(external_stack)
    ai_stack = sorted(p for p in AI_GENERATED_DIR.glob("*") if p.suffix.lower() in {".jpg", ".jpeg", ".png"}) \
        if AI_GENERATED_DIR.exists() else []
    ai_uw_stack = sorted(
        q for q in AI_GENERATED_UNDERWRITING_DIR.glob("*") if q.suffix.lower() in {".jpg", ".jpeg", ".png"}
    ) if AI_GENERATED_UNDERWRITING_DIR.exists() else []

    gaming_garages = [g for g in garages if g["is_gaming"]]

    # -- counts (see module docstring's derivation: claims_total = clean_claims + fraud_total, always) --
    underwriting_total = round(count * 150 / 800)
    claims_total = count - underwriting_total
    fraud_total = min(round(count * 0.30), claims_total)
    clean_claims_total = claims_total - fraud_total
    base, remainder = divmod(fraud_total, len(ARCHETYPES))
    archetype_counts = {name: base + (1 if i < remainder else 0) for i, name in enumerate(ARCHETYPES)}

    gaming_legit_total = min(len(gaming_garages) * GAMING_LEGIT_PER_GARAGE, clean_claims_total)
    plain_clean_claims_total = clean_claims_total - gaming_legit_total

    ids = itertools.count(1)
    claimants = itertools.count(1)
    specs: list[CaseSpec] = []
    used_registry: list[tuple[str, Path, datetime]] = []  # (case_id, damage image path, declared_time)
    pending_ai_cases: list[str] = []

    def new_id() -> str:
        return f"case-{next(ids):04d}"

    def new_claimant() -> Claimant:
        return random_claimant(rng, next(claimants))

    def location() -> tuple[str, float, float, str]:
        return rng.choice(LOCATIONS)

    def base_kwargs(agent_type: str, archetype: str, garage_id: str, claim_type: str,
                     claim_amount: Optional[float], declared_time: Optional[datetime] = None) -> dict:
        name, lat, lon, city = location()
        # Every case's default time is sampled from the daylight window at
        # its own date and coordinates. Archetypes that deliberately want a
        # contradictory hour pass declared_time explicitly and so bypass
        # this - which is the point: after this change a case whose photo
        # and clock disagree is a *constructed* contradiction, never an
        # accident of sampling.
        return dict(
            case_id=new_id(),
            agent_type=agent_type,
            archetype=archetype,
            claimant=new_claimant(),
            garage_id=garage_id,
            declared_time=declared_time or random_declared_time(
                rng, reference_now, latitude=lat, longitude=lon, daylight_only=True
            ),
            declared_location=f"{name}, {city}",
            latitude=lat,
            longitude=lon,
            claim_type=claim_type,
            claim_amount=claim_amount,
            vehicle_registration=random_registration(rng),
        )

    # -- underwriting: AI_GENERATED_BASELINE, the baseline-corruption attack --
    #
    # Structurally distinct from every claims-side archetype, and the
    # distinction is the point. Every other fraud in this corpus fabricates
    # the *presence* of damage at claim time. This one fabricates the
    # *absence* of it at policy inception: the applicant's vehicle is
    # already damaged, so they submit a synthetic image of an undamaged
    # vehicle of the same make and colour. That buys two things at once - a
    # higher insured declared value than the real vehicle supports, and a
    # clean pre-existing-condition record that later legitimises a claim
    # for damage the vehicle already had.
    #
    # It is drawn from the underwriting budget rather than ARCHETYPES'
    # claims-fraud budget: an underwriting case has no claim amount and no
    # incident, so mixing it into the claims denominators would corrupt
    # every claims-side recall figure. See AI_BASELINE_TOTAL.
    ai_baseline_total = min(AI_BASELINE_TOTAL, len(ai_uw_stack)) if ai_uw_stack else 0
    for i in range(ai_baseline_total):
        spec = CaseSpec(**base_kwargs("underwriting", "AI_GENERATED_BASELINE",
                                      rng.choice(garages)["garage_id"], "underwriting_inspection", None))
        synthetic = ai_uw_stack[i % len(ai_uw_stack)]
        # One synthetic image plus one genuine whole-car shot: a submission
        # of nothing but synthetic images would be a different and much
        # easier problem, and real baseline corruption hides the fabricated
        # frame among honest ones.
        spec.image_paths = [synthetic, whole_stack.pop()]
        spec.fraud_metadata = {
            "attack": "baseline_corruption",
            "ai_image_source": str(synthetic),
            "fabricates": "absence_of_damage",
            "stage": "policy_inception",
            "intent": (
                "applicant's vehicle is already damaged; a synthetic image of an undamaged "
                "vehicle of the same make and colour is submitted to secure a higher insured "
                "declared value and to establish a clean pre-existing-condition baseline that "
                "legitimises a later claim for the pre-existing damage"
            ),
            "distinct_from": "claim_time_fabrication",
        }
        specs.append(spec)

    # Link each corrupted baseline to the claim it exists to legitimise. Done
    # here, after every spec is built, because it needs both sides. Inert
    # until the corpus is regenerated; the currently measured linkage numbers
    # come from scripts/inject_baseline_linkage.py, which applies the same
    # pairing to a database copy so the running ablation is not disturbed.
    _baseline_links: list[dict] = []

    # -- underwriting: clean, 2 whole-car images each (front/back), no incident --
    for _ in range(underwriting_total - ai_baseline_total):
        spec = CaseSpec(**base_kwargs("underwriting", "CLEAN", rng.choice(garages)["garage_id"],
                                       "underwriting_inspection", None))
        spec.image_paths = [whole_stack.pop(), whole_stack.pop()]
        specs.append(spec)

    # -- claims, clean, gaming-garage-adjacent (forces the "just legit claims that
    #    happen to cluster near the band" background the THRESHOLD_GAMING signal
    #    needs to stand out against as a *distribution*, not a single flagged case) --
    for i in range(gaming_legit_total):
        garage = gaming_garages[i % len(gaming_garages)]["garage_id"]
        spec = CaseSpec(**base_kwargs("claims", "CLEAN", garage, "collision", sample_gaming_amount(rng)))
        spec.image_paths = [damaged_stack.pop(), whole_stack.pop()]
        specs.append(spec)
        used_registry.append((spec.case_id, spec.image_paths[0], spec.declared_time))

    # -- claims, clean, everyone else --
    for _ in range(plain_clean_claims_total):
        garage = rng.choice(garages)["garage_id"]
        spec = CaseSpec(**base_kwargs("claims", "CLEAN", garage, "collision", sample_claim_amount(rng)))
        spec.image_paths = [damaged_stack.pop(), whole_stack.pop()]
        specs.append(spec)
        used_registry.append((spec.case_id, spec.image_paths[0], spec.declared_time))

    # -- fraud archetypes, everything except REUSE (REUSE needs the registry
    #    above populated first, so it runs last) --
    threshold_gaming_seq = itertools.count()
    ai_generated_seq = itertools.count()
    digital_edit_seq = itertools.count()
    context_seq = itertools.count()

    # -- scene-selected pools for CONTEXT_MISMATCH ------------------------
    # Rank a slice of the damaged pool by what each photo visibly shows, so
    # the declaration can be built to contradict it. Only a slice is
    # scored: reading and analysing every remaining image costs real time
    # and CONTEXT_MISMATCH needs a few dozen, not hundreds.
    context_needed = archetype_counts.get("CONTEXT_MISMATCH", 0)
    scan_limit = min(len(damaged_stack), max(200, context_needed * 12))
    scan = damaged_stack[-scan_limit:] if scan_limit else []
    dry_scores: dict[Path, float] = {}
    shadow_scores: dict[Path, float] = {}
    for candidate in scan:
        features = scene_features(candidate)
        if features is None:
            continue
        dry_scores[candidate] = dry_clear_score(features)
        shadow_scores[candidate] = shadow_score(features)

    half = max(1, context_needed // 2 + 1)
    dry_pool = [c for c, _ in sorted(dry_scores.items(), key=lambda kv: -kv[1])[:half]]
    # Disjoint: a photo used for the weather contradiction must not also be
    # used for the shadow one, or the two variants would share images and
    # the near-duplicate assertions would trip.
    shadow_pool = [
        c for c, _ in sorted(shadow_scores.items(), key=lambda kv: -kv[1]) if c not in set(dry_pool)
    ][:half]
    for used in set(dry_pool) | set(shadow_pool):
        if used in damaged_stack:
            damaged_stack.remove(used)
    print(f"[step3] context pools: {len(dry_pool)} dry/clear, {len(shadow_pool)} shadowed "
          f"(scored {len(dry_scores)} candidates)")

    _rain_cache: dict[tuple[float, float], list[date]] = {}

    def rain_dates_for(latitude: float, longitude: float) -> list[date]:
        key = (round(latitude, 2), round(longitude, 2))
        if key not in _rain_cache:
            _rain_cache[key] = heavy_rain_dates(latitude, longitude, reference_now)
        return _rain_cache[key]
    for archetype in ARCHETYPES:
        if archetype == "REUSE":
            continue
        for _ in range(archetype_counts[archetype]):
            garage = (
                gaming_garages[next(threshold_gaming_seq) % len(gaming_garages)]["garage_id"]
                if archetype == "THRESHOLD_GAMING" else rng.choice(garages)["garage_id"]
            )
            amount = sample_gaming_amount(rng) if archetype == "THRESHOLD_GAMING" else sample_claim_amount(rng)
            spec = CaseSpec(**base_kwargs("claims", archetype, garage, "collision", amount))

            if archetype == "EXTERNAL_SOURCING":
                spec.image_paths = [external_stack.pop(), external_stack.pop()]
                spec.fraud_metadata = {"source": "external_corpus", "images": [str(p) for p in spec.image_paths]}

            elif archetype == "DIGITAL_EDIT":
                damage_src, whole_base = damaged_stack.pop(), whole_stack.pop()
                dest = DIGITAL_EDIT_DIR / f"{spec.case_id}.jpg"
                DIGITAL_EDIT_DIR.mkdir(parents=True, exist_ok=True)
                # Alternate deterministically rather than sampling, so the
                # two variants land in a known 50/50 split regardless of
                # how the rng stream is consumed elsewhere - the
                # per-variant detection rates in the evaluation are only
                # comparable if the groups are the same size.
                recompress_patch = next(digital_edit_seq) % 2 == 0
                edit_meta = make_digital_edit_composite(
                    damage_src, whole_base, dest, rng, recompress_patch=recompress_patch
                )
                spec.image_paths = [dest]
                spec.fraud_metadata = {
                    "damage_source": str(damage_src), "whole_base": str(whole_base),
                    **edit_meta,
                }

            elif archetype == "AI_GENERATED":
                if ai_stack:
                    img = ai_stack[next(ai_generated_seq) % len(ai_stack)]
                    spec.image_paths = [img]
                    spec.fraud_metadata = {"ai_image_source": str(img)}
                else:
                    spec.image_paths = []
                    spec.fraud_metadata = {"pending_ai_image": True}
                    pending_ai_cases.append(spec.case_id)

            elif archetype == "METADATA_FORGERY":
                source = damaged_stack.pop()
                dest = METADATA_FORGERY_DIR / f"{spec.case_id}.jpg"
                METADATA_FORGERY_DIR.mkdir(parents=True, exist_ok=True)
                spec.fraud_metadata = forge_exif(source, dest, spec.latitude, spec.longitude, spec.declared_time, rng)
                spec.image_paths = [dest]

            elif archetype == "CONTEXT_MISMATCH":
                # Construction INVERTED: pick the photo first, then build a
                # declaration the photo actually contradicts.
                #
                # The previous version did the opposite - it altered the
                # declared date or hour and attached whatever damaged-car
                # photo came next off the stack. That made the archetype
                # unfalsifiable. Measured on the 9 cases perception
                # reached, all 9 photographs showed clear skies and dry
                # ground, including the 5 labelled "declared monsoon rain
                # but dry-season date": there was nothing in the evidence
                # to contradict, so no check could find it, and recall
                # measured how often a suitable photo happened to come up.
                #
                # Now the photo is chosen for what it visibly shows, the
                # declaration is built against it, and the intended
                # contradiction is recorded so evaluation can confirm the
                # check caught the right thing rather than firing by
                # coincidence.
                variant = "dry_photo_vs_rainy_day" if next(context_seq) % 2 == 0 else "shadows_vs_after_dark"

                wet_hour_choice = None
                if variant == "dry_photo_vs_rainy_day" and dry_pool:
                    # The declared hour must be one in which rain was
                    # actually falling, not merely a daylight hour on a day
                    # whose total was high. See rainy_hours() for why: the
                    # check refuses a daily total as evidence, correctly,
                    # so the generator has to meet its standard. Also
                    # require the hour to be daylit, or the lighting
                    # sub-check would fire instead and the case would be
                    # caught for the wrong reason.
                    for day in rng.sample(
                        rain_dates_for(spec.latitude, spec.longitude),
                        k=min(6, len(rain_dates_for(spec.latitude, spec.longitude))),
                    ):
                        lit = set(daylight_hours(day, spec.latitude, spec.longitude))
                        wet = [h for h in rainy_hours(spec.latitude, spec.longitude, day) if h in lit]
                        if wet:
                            wet_hour_choice = (day, rng.choice(wet))
                            break

                if wet_hour_choice is not None:
                    source = dry_pool.pop()
                    day, hour = wet_hour_choice
                    spec.declared_time = datetime(
                        day.year, day.month, day.day, hour, rng.randint(0, 59), tzinfo=timezone.utc
                    )
                    spec.image_paths = [source]
                    spec.fraud_metadata = {
                        "contradiction": "photo_shows_dry_clear_but_rain_was_falling_at_declared_hour",
                        "variant": "dry_photo_vs_rainy_day",
                        "expected_subcheck": "weather",
                        "declared_date": day.isoformat(),
                        "declared_hour_local": hour,
                        "rain_confirmed_hourly": True,
                        "dry_clear_score": round(dry_scores.get(source, 0.0), 3),
                    }
                elif shadow_pool:
                    source = shadow_pool.pop()
                    day = rng.choice(_dates_in_last_12_months(reference_now))
                    # One hour past civil twilight: the photograph shows
                    # daylight and standing shadows, the claim says dark.
                    hour = min(23, sunset_hour(day, spec.latitude, spec.longitude) + 1)
                    spec.declared_time = datetime(
                        day.year, day.month, day.day, hour, rng.randint(0, 59), tzinfo=timezone.utc
                    )
                    spec.image_paths = [source]
                    spec.fraud_metadata = {
                        "contradiction": "photo_shows_daylight_shadows_but_declared_after_dark",
                        "variant": "shadows_vs_after_dark",
                        "expected_subcheck": "lighting_or_solar_geometry",
                        "declared_hour": hour,
                        "shadow_score": round(shadow_scores.get(source, 0.0), 3),
                    }
                else:
                    # Pools exhausted (or the weather archive was
                    # unreachable). Fall back to the old behaviour but say
                    # so, rather than emitting a case that silently cannot
                    # be detected and would drag recall down for reasons
                    # nobody could trace.
                    source = damaged_stack.pop()
                    spec.image_paths = [source]
                    spec.declared_time = random_declared_time(rng, reference_now, hour_choices=[18])
                    spec.fraud_metadata = {
                        "contradiction": "declared_evening_unverified_photo",
                        "variant": "fallback_unverified",
                        "expected_subcheck": None,
                        "note": "scene-selected pool exhausted; contradiction not verified against the image",
                    }

            elif archetype == "THRESHOLD_GAMING":
                spec.image_paths = [damaged_stack.pop()]
                spec.fraud_metadata = {"gaming_band_inr": list(GAMING_BAND_INR)}

            specs.append(spec)
            if spec.image_paths:
                used_registry.append((spec.case_id, spec.image_paths[0], spec.declared_time))

    # -- REUSE, last: take an already-used damage photo, different claimant --
    reuse_n = archetype_counts["REUSE"]
    reuse_sources = rng.sample(used_registry, min(reuse_n, len(used_registry)))
    for i in range(reuse_n):
        original_case_id, original_path, original_time = reuse_sources[i % len(reuse_sources)]
        declared_time = original_time + timedelta(days=rng.randint(1, 60))
        garage = rng.choice(garages)["garage_id"]
        spec = CaseSpec(**base_kwargs("claims", "REUSE", garage, "collision", sample_claim_amount(rng),
                                       declared_time=declared_time))
        spec.image_paths = [original_path]
        spec.fraud_metadata = {"reused_from_case_id": original_case_id, "reused_image": str(original_path)}
        specs.append(spec)

    return specs, pending_ai_cases


def assert_clean_images_disjoint(specs: list[CaseSpec]) -> None:
    """
    Belt-and-suspenders check on top of the pool-draw construction above:
    no two CLEAN cases may share a single image's *content*. Checked by
    sha256, not by path - this dataset contains byte-identical images
    under different filenames (see dedupe_by_content_hash()), and a
    path-only check would miss that collision entirely. If this ever
    fires, the false-positive rate - the system's primary metric - is
    meaningless, because a "clean" case would look like a duplicate of
    another "clean" case for reasons that have nothing to do with fraud.

    Also asserts near-duplicate disjointness - Hamming<=8 or cosine>=0.95,
    the same thresholds src/checks/duplicate.py's InternalDuplicateCheck
    uses for CONCERN (see NEAR_DUP_HAMMING_CONCERN/NEAR_DUP_COSINE_CONCERN)
    - across every pair of CLEAN-case images, not just exact sha256
    matches. This should never fire: dedupe_near_duplicates() already
    cleans the pool CLEAN cases draw from before a single case is
    assigned (see STEP 0 in main()), so it's a sanity check on that
    construction, exactly like the sha256 half above already was. It's
    not a hypothetical either - test_checks.py's first real run against
    this corpus, before dedupe_near_duplicates() existed, found 27
    CLEAN-vs-CLEAN near-duplicate collisions this exact assertion would
    have caught.
    """
    seen: dict[str, str] = {}
    clean_specs = [spec for spec in specs if spec.archetype == "CLEAN"]

    for spec in clean_specs:
        for path in spec.image_paths:
            content_hash = ingest.compute_sha256(path)
            assert content_hash not in seen, (
                f"clean-case image collision: {path} (sha256 {content_hash[:12]}...) "
                f"used by both {seen[content_hash]} and {spec.case_id}"
            )
            seen[content_hash] = spec.case_id

    _assert_no_near_duplicate_pairs(clean_specs)


def _assert_no_near_duplicate_pairs(
    clean_specs: list[CaseSpec],
    hamming_concern: int = NEAR_DUP_HAMMING_CONCERN,
    cosine_concern: float = NEAR_DUP_COSINE_CONCERN,
) -> None:
    """
    O(n^2) pairwise comparison across every CLEAN-case image - fine at
    this corpus's scale (a few hundred clean-case images), same "not
    worth indexing yet" reasoning as ingest.find_similar and every check
    that reads from this project's brute-force-sized corpus. Skips pairs
    from the *same* case (a case legitimately sharing its own two images,
    e.g. an underwriting front/back pair, is not a disjointness
    violation) and, unlike the pool-level dedupe_near_duplicates(), does
    compare across the damaged/whole category split - that pool-level
    pass only ever compared within one category, so a damage crop and a
    whole-car photo that somehow ended up near-duplicate to each other
    would slip past it entirely.
    """
    embedder = ingest._default_embedder
    entries: list[tuple[str, Path, str, np.ndarray]] = []
    for spec in clean_specs:
        for path in spec.image_paths:
            phash, _ = ingest.compute_hashes(path)
            embedding = np.asarray(embedder.embed(path), dtype=np.float64)
            entries.append((spec.case_id, path, phash, embedding))

    if len(entries) < 2:
        return

    matrix = np.stack([entry[3] for entry in entries])
    cosines = matrix @ matrix.T

    for i in range(len(entries)):
        case_i, path_i, phash_i, _ = entries[i]
        for j in range(i + 1, len(entries)):
            case_j, path_j, phash_j, _ = entries[j]
            if case_i == case_j:
                continue
            cosine = float(cosines[i, j])
            hamming = ingest.hamming_distance(phash_i, phash_j)
            assert hamming > hamming_concern and cosine < cosine_concern, (
                f"near-duplicate clean-case image collision: {path_i} ({case_i}) and {path_j} ({case_j}) "
                f"(perceptual distance {hamming}, semantic similarity {cosine:.3f})"
            )


# ---------------------------------------------------------------------------
# Step 4 - write to database
# ---------------------------------------------------------------------------


def ingest_all(specs: list[CaseSpec], db_path: str, commit_every: int = 25) -> dict[str, list]:
    conn = db.connect(db_path)
    db.init_db(conn)
    ingested_images: dict[str, list] = {}
    saved_claimants: set[str] = set()
    try:
        for i, spec in enumerate(tqdm(specs, desc="ingesting cases", unit="case"), start=1):
            if spec.claimant.claimant_id not in saved_claimants:
                db.save_claimant(conn, spec.claimant)
                saved_claimants.add(spec.claimant.claimant_id)
            case = Case(
                case_id=spec.case_id,
                claimant_id=spec.claimant.claimant_id,
                garage_id=spec.garage_id,
                claim_type=spec.claim_type,
                declared_time=spec.declared_time,
                declared_location=spec.declared_location,
                latitude=spec.latitude,
                longitude=spec.longitude,
                agent_type=spec.agent_type,
                claim_amount=spec.claim_amount,
                vehicle_registration=spec.vehicle_registration,
            )
            ingested_images[spec.case_id] = ingest.ingest_case(conn, case, spec.image_paths)
            if i % commit_every == 0:
                conn.commit()
        conn.commit()
    finally:
        conn.close()
    return ingested_images


# ---------------------------------------------------------------------------
# Step 5 - report + ground truth
# ---------------------------------------------------------------------------


def write_report(specs: list[CaseSpec], ingested_images: dict[str, list]) -> None:
    print("\n" + "=" * 70)
    print("REPORT")
    print("=" * 70)
    print(f"total cases: {len(specs)}")

    by_archetype = Counter(s.archetype for s in specs)
    print("\nby archetype:")
    for name, n in sorted(by_archetype.items()):
        print(f"  {name:<20} {n}")

    by_agent = Counter(s.agent_type for s in specs)
    print("\nby agent type:")
    for name, n in sorted(by_agent.items()):
        print(f"  {name:<20} {n}")

    all_images = [img for images in ingested_images.values() for img in images]
    unique_hashes = {img.content_hash for img in all_images}
    print(f"\nimages: {len(all_images)} total, {len(unique_hashes)} unique content hashes "
          f"({len(all_images) - len(unique_hashes)} intentional duplicates from REUSE)")

    amounts = [s.claim_amount for s in specs if s.claim_amount is not None]
    below_50k = sum(1 for a in amounts if a < 50000)
    print(f"\nclaim amounts: {len(amounts)} cases with an amount, {below_50k} below Rs 50,000")

    print("\nclaim-amount histogram (Rs 10k buckets):")
    buckets = Counter(int(a // 10000) * 10000 for a in amounts)
    for lo in sorted(buckets):
        bar = "#" * (buckets[lo] // max(1, len(amounts) // 200) or 1)
        print(f"  {lo:>7,}-{lo + 9999:>7,}: {buckets[lo]:>4}  {bar}")


def write_ground_truth_csv(specs: list[CaseSpec]) -> None:
    GENERATED_DIR.mkdir(parents=True, exist_ok=True)
    with open(GROUND_TRUTH_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["case_id", "archetype", "agent_type", "amount", "garage_id", "fraud_metadata"])
        for spec in specs:
            writer.writerow([
                spec.case_id,
                spec.archetype,
                spec.agent_type,
                spec.claim_amount if spec.claim_amount is not None else "",
                spec.garage_id,
                json.dumps(spec.fraud_metadata),
            ])
    print(f"\nwrote {GROUND_TRUTH_CSV} ({len(specs)} rows)")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate the synthetic FraudLens case corpus.")
    parser.add_argument("--count", type=int, default=DEFAULT_CASE_COUNT, help="total cases to generate (default 800)")
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED, help="random seed for reproducibility (default 42)")
    parser.add_argument("--db-path", default="fraudlens.db", help="sqlite database path")
    return parser.parse_args(argv)


def main(argv: Optional[list[str]] = None) -> None:
    args = parse_args(argv)
    rng = random.Random(args.seed)

    print("STEP 0 - normalise source images")
    damaged_all, whole_all = normalize_source_images()
    damaged_all = dedupe_by_content_hash(damaged_all, "damaged")
    whole_all = dedupe_by_content_hash(whole_all, "whole")
    # The external corpus is reserved before this point on any re-run
    # (reserve_external_corpus physically moved those files out in STEP 1
    # of an earlier run), so it has to be fed back in explicitly as a
    # reference set - otherwise the images that stay in the pool are
    # never compared against it. Empty on a first-ever run, where nothing
    # has been reserved yet and STEP 1 draws from an already-deduped pool.
    external_reference = sorted(EXTERNAL_CORPUS.glob("*.jpg"))
    if external_reference:
        print(f"[step0c] comparing pool against {len(external_reference)} reserved external-corpus image(s)")
    damaged_all = dedupe_near_duplicates(damaged_all, "damaged", reference_paths=external_reference)
    whole_all = dedupe_near_duplicates(whole_all, "whole", reference_paths=external_reference)

    print("\nSTEP 1 - reserve external corpus")
    damaged_pool, external_names = reserve_external_corpus(damaged_all, args.seed)

    print("\nSTEP 2 - Indian context data")
    garages = build_garages(rng)
    print(f"[step2] {len(garages)} garages ({GAMING_GARAGE_COUNT} gaming), "
          f"{len(LOCATIONS)} locations, {len(RTO_CODES)} RTO codes")

    print("\nSTEP 3 - generate case specs")
    specs, pending_ai_cases = build_case_specs(args.count, rng, damaged_pool, whole_all, external_names, garages)
    print(f"[step3] {len(specs)} case specs built")
    if pending_ai_cases:
        print(
            f"WARNING: {len(pending_ai_cases)} AI_GENERATED cases have no image "
            f"(data/ai_generated/ is empty or missing) - add images there and "
            f"re-run to backfill: {', '.join(pending_ai_cases)}",
            file=sys.stderr,
        )

    align = align_clean_declarations(specs, rng, datetime.now(timezone.utc), args.db_path)
    print(f"[step3] clean declarations aligned to their photographs: "
          f"{align['weather_aligned']} on the weather axis, {align['shadow_aligned']} on the shadow axis "
          f"({align['perception_used']} used a perception record; {align['no_dry_dates']} had no usable dates)")

    assert_clean_images_disjoint(specs)
    print("[step3] clean-case image disjointness check passed")

    print("\nSTEP 4 - write to database")
    ingested_images = ingest_all(specs, args.db_path)

    print("\nSTEP 5 - report")
    write_report(specs, ingested_images)
    write_ground_truth_csv(specs)


if __name__ == "__main__":
    main()
