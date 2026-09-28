"""
Test suite for src.ingest.

Runs against real images from data/raw and a real (CPU) CLIP model -
not mocked, because the properties under test (stable hashes, unit-norm
embeddings, similarity ordering) are exactly the things a mock would
have to fake correctly to be worth anything. Same minimal, stdlib-only
runner as test_models.py/test_llm.py, plus a PASS/FAIL line per test
since model loading and embedding are slow enough that silent progress
would be unnerving.

Run with:
    python test_ingest.py
"""

from __future__ import annotations

import os
import sys
import tempfile
import traceback
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))

import numpy as np
from PIL import Image as PILImage

from src import db, ingest
from src.models import Case

# ---------------------------------------------------------------------------
# Tiny test runner (same shape as test_models.py/test_llm.py)
# ---------------------------------------------------------------------------

_TESTS: list = []


def test(fn):
    _TESTS.append(fn)
    return fn


def run_all() -> bool:
    passed, failed = 0, 0
    failures = []
    for fn in _TESTS:
        print(f"--- {fn.__name__} ---")
        try:
            fn()
            passed += 1
            print(f"PASS  {fn.__name__}")
        except Exception as e:  # noqa: BLE001 - test runner, wants everything
            failed += 1
            failures.append((fn.__name__, e, traceback.format_exc()))
            print(f"FAIL  {fn.__name__}  ->  {type(e).__name__}: {e}")
    if failures:
        print("\n" + "=" * 70)
        for name, e, tb in failures:
            print(f"FAIL  {name}\n{tb}")
    print(f"\n{passed} passed, {failed} failed")
    return failed == 0


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_TEST_DB_FD, _TEST_DB_PATH_STR = tempfile.mkstemp(suffix=".db", prefix="fraudlens_test_ingest_")
os.close(_TEST_DB_FD)
TEST_DB_PATH = Path(_TEST_DB_PATH_STR)

_embedder: Optional[ingest.CLIPEmbedder] = None


def get_embedder() -> ingest.CLIPEmbedder:
    """One CLIP instance shared across every test, the same way ingest_case() shares one."""
    global _embedder
    if _embedder is None:
        _embedder = ingest.CLIPEmbedder()
    return _embedder


def find_sample_images(n: int = 2) -> list[Path]:
    """First `n` distinct images found under data/raw's class subfolders."""
    root = Path("data/raw")
    found: list[Path] = []
    for suffix in (".jpg", ".jpeg", ".JPEG", ".JPG", ".png"):
        for path in sorted(root.rglob(f"*{suffix}")):
            if path not in found:
                found.append(path)
            if len(found) >= n:
                return found
    raise FileNotFoundError(f"found only {len(found)}/{n} images under data/raw")


def make_case(case_id: str) -> Case:
    return Case(case_id=case_id, claimant_id="claimant-1", garage_id="garage-1", claim_type="collision")


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@test
def test_sha256_is_stable_across_calls():
    image_path = find_sample_images(1)[0]
    first = ingest.compute_sha256(image_path)
    second = ingest.compute_sha256(image_path)
    assert first == second
    assert len(first) == 64
    print(f"  sha256 = {first}")


@test
def test_phash_survives_resave_and_resize():
    image_path = find_sample_images(1)[0]
    phash_original, _ = ingest.compute_hashes(image_path)

    with tempfile.TemporaryDirectory() as tmp:
        resized_path = Path(tmp) / "resized.jpg"
        with PILImage.open(image_path) as img:
            img = img.convert("RGB")
            small = img.resize((max(1, img.width * 9 // 10), max(1, img.height * 9 // 10)))
            small.save(resized_path, format="JPEG", quality=85)

        phash_resized, _ = ingest.compute_hashes(resized_path)

    distance = ingest.hamming_distance(phash_original, phash_resized)
    # 64-bit hash (default imagehash hash_size=8); a 10% resize + JPEG
    # recompress should land well under half the bits - this is not a
    # different image, just a different encoding of the same one.
    assert distance <= 10, f"expected a small Hamming distance, got {distance}"
    print(f"  phash(original) = {phash_original}  phash(resized) = {phash_resized}  distance = {distance}")


@test
def test_embedding_is_512dim_and_unit_norm():
    image_path = find_sample_images(1)[0]
    embedding = get_embedder().embed(image_path)
    assert len(embedding) == 512, f"expected 512 dims, got {len(embedding)}"
    norm = float(np.linalg.norm(np.asarray(embedding)))
    assert abs(norm - 1.0) < 1e-4, f"expected unit norm, got {norm}"
    print(f"  dims = {len(embedding)}  norm = {norm:.6f}")


@test
def test_cosine_similarity_self_vs_different_image():
    image_a, image_b = find_sample_images(2)
    embedder = get_embedder()
    embedding_a = embedder.embed(image_a)
    embedding_b = embedder.embed(image_b)

    self_similarity = ingest.cosine_similarity(embedding_a, embedding_a)
    cross_similarity = ingest.cosine_similarity(embedding_a, embedding_b)

    assert abs(self_similarity - 1.0) < 1e-4, f"expected ~1.0, got {self_similarity}"
    assert cross_similarity < self_similarity
    print(f"  self = {self_similarity:.6f}  cross({image_a.name}, {image_b.name}) = {cross_similarity:.6f}")


@test
def test_find_similar_excludes_source_case():
    image_a, image_b = find_sample_images(2)
    embedder = get_embedder()

    with db.session(TEST_DB_PATH) as conn:
        # Same photo submitted under two different cases - the
        # duplicate-detection scenario this whole module exists for.
        db.insert_case(conn, make_case("case-src"))
        src_image = ingest.ingest_image(conn, "case-src", image_a, embedder=embedder)

        db.insert_case(conn, make_case("case-dup"))
        dup_image = ingest.ingest_image(conn, "case-dup", image_a, embedder=embedder)

        db.insert_case(conn, make_case("case-other"))
        other_image = ingest.ingest_image(conn, "case-other", image_b, embedder=embedder)

        results = ingest.find_similar(conn, src_image.embedding, exclude_case="case-src", top_k=10)

    result_case_ids = [img.case_id for img, _score in results]
    assert "case-src" not in result_case_ids, "find_similar must exclude the querying case's own images"
    assert "case-dup" in result_case_ids, "the duplicate image in another case should be found"

    top_image, top_score = results[0]
    assert top_image.case_id == "case-dup"
    assert top_score > 0.99, f"identical image in another case should score ~1.0, got {top_score}"
    print(f"  results = {[(img.case_id, round(score, 4)) for img, score in results]}")


@test
def test_extract_exif_does_not_crash_without_exif():
    with tempfile.TemporaryDirectory() as tmp:
        png_path = Path(tmp) / "no_exif.png"
        PILImage.new("RGB", (16, 16), color=(255, 0, 0)).save(png_path, format="PNG")

        exif = ingest.extract_exif(png_path)
        assert exif == {}, f"expected empty dict for a PNG with no EXIF, got {exif}"

    # Also exercise it against a real dataset image - whatever EXIF (or
    # lack of it) that file happens to have, this must not raise.
    image_path = find_sample_images(1)[0]
    exif = ingest.extract_exif(image_path)
    assert isinstance(exif, dict)
    print(f"  PNG (no exif) -> {{}}   real image -> {len(exif)} IFD block(s)")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    try:
        ok = run_all()
    finally:
        try:
            TEST_DB_PATH.unlink(missing_ok=True)
        except OSError as e:
            print(f"  (cleanup) could not remove {TEST_DB_PATH}: {e}", file=sys.stderr)
    sys.exit(0 if ok else 1)
