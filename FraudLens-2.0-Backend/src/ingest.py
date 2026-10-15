"""
fraudlens.ingest
================

The image intake pipeline. Turns a file on disk into a saved Image row
- content hash, two perceptual hashes, a CLIP embedding, and EXIF -
before any check ever looks at it.

That ordering is the whole point of this module. Duplicate-image and
CLIP-similarity checks (src/checks, not written yet) work retroactively
only because every photo that has ever come through ingest_case()
already has a row sitting in the images table with an embedding in it.
Case #700 can be flagged as reusing a photo from case #12 because #12
was indexed the day it arrived, months before #700 existed - not
because #700's check went looking backwards through old cases.
"""

from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path
from typing import Any, Iterable, Optional, Sequence, Union
from uuid import uuid4

import numpy as np
from PIL import Image as PILImage

from . import db
from .models import AuditEvent, Case, Image

# ---------------------------------------------------------------------------
# Hashing
# ---------------------------------------------------------------------------


def compute_sha256(path: Union[str, Path]) -> str:
    """
    Hash of the raw file bytes, not a re-encode. This is the same
    content hash PerceptionRecord and src/llm.py's describe_image()
    cache key off of, so it has to be byte-for-byte identical for the
    same file or the whole "same photo costs one API call ever" story
    breaks.
    """
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def compute_hashes(path: Union[str, Path]) -> tuple[str, str]:
    """
    pHash and dHash via imagehash, as hex strings. Unlike compute_sha256
    these are stable across a resave, a resize, or light recompression
    - a claimant re-uploading a screenshot of the same photo won't
    share its sha256 with the original, but will almost always land
    within a small Hamming distance on these.
    """
    import imagehash

    with PILImage.open(path) as img:
        img = img.convert("RGB")
        phash = imagehash.phash(img)
        dhash = imagehash.dhash(img)
    return str(phash), str(dhash)


def hamming_distance(hash_a: str, hash_b: str) -> int:
    """Bit differences between two same-length imagehash hex strings."""
    return bin(int(hash_a, 16) ^ int(hash_b, 16)).count("1")


# ---------------------------------------------------------------------------
# CLIP embeddings
# ---------------------------------------------------------------------------


class CLIPEmbedder:
    """
    CLIP ViT-B/32 (laion2b_s34b_b79k) image encoder, CPU-only, loaded
    lazily. Constructing this class costs nothing; the weights load on
    the first call to embed() and stay resident for the lifetime of
    the instance. That matters because loading takes several real
    seconds - ingest_case() shares one instance across every image in
    a batch (see _default_embedder below) so that cost is paid once
    per process, not once per photo.
    """

    _MODEL_NAME = "ViT-B-32"
    _PRETRAINED = "laion2b_s34b_b79k"

    def __init__(self) -> None:
        import threading
        self._load_lock = threading.Lock()
        self._model = None
        self._preprocess = None
        self._tokenizer = None

    def _ensure_loaded(self) -> None:
        with self._load_lock:
            self._load_model()

    def _load_model(self) -> None:
        if self._model is not None:
            return
        from .timing import span
        with span('clip.import_dependencies'):
            import open_clip
            import os, torch
        torch.set_num_threads(max(1,int(os.environ.get('FRAUDLENS_TORCH_THREADS','2'))))

        with span('clip.initialize'):
            model, _, preprocess = open_clip.create_model_and_transforms(
                self._MODEL_NAME, pretrained=self._PRETRAINED, device="cpu"
            )
        model.eval()
        self._model = model
        self._preprocess = preprocess
        self._tokenizer = open_clip.get_tokenizer(self._MODEL_NAME)

    def embed(self, path: Union[str, Path]) -> list[float]:
        """512-dim, L2-normalised, so cosine_similarity() reduces to a plain dot product."""
        self._ensure_loaded()
        import torch

        with PILImage.open(path) as img:
            tensor = self._preprocess(img.convert("RGB")).unsqueeze(0)
        with torch.no_grad():
            features = self._model.encode_image(tensor)
            features = features / features.norm(dim=-1, keepdim=True)
        return features.squeeze(0).tolist()

    def embed_texts(self, prompts: Sequence[str]) -> list[list[float]]:
        """L2-normalised CLIP text embeddings for prompt comparison."""
        self._ensure_loaded()
        import torch

        tokens = self._tokenizer(list(prompts))
        with torch.no_grad():
            features = self._model.encode_text(tokens)
            features = features / features.norm(dim=-1, keepdim=True)
        return features.tolist()


# One embedder for the whole process. Not a class-level singleton
# pattern (no need for the ceremony) - just a module global that
# ingest_image() falls back to when the caller doesn't supply their
# own, so a script that ingests 500 images across many ingest_case()
# calls still only loads the model once.
_default_embedder = CLIPEmbedder()


def cosine_similarity(a: Sequence[float], b: Sequence[float]) -> float:
    va = np.asarray(a, dtype=np.float64)
    vb = np.asarray(b, dtype=np.float64)
    denom = float(np.linalg.norm(va) * np.linalg.norm(vb))
    if denom == 0.0:
        return 0.0
    return float(np.dot(va, vb) / denom)


# ---------------------------------------------------------------------------
# EXIF
# ---------------------------------------------------------------------------

_DROPPED = object()


def _json_safe(value: Any) -> Any:
    """Recursively strip anything json.dumps can't handle out of a raw piexif value."""
    if isinstance(value, bytes):
        try:
            return value.decode("utf-8").rstrip("\x00")
        except UnicodeDecodeError:
            return _DROPPED
    if isinstance(value, tuple):
        items = [_json_safe(v) for v in value]
        return [v for v in items if v is not _DROPPED]
    return value


def extract_exif(path: Union[str, Path]) -> dict[str, Any]:
    """
    EXIF via piexif, flattened into a plain JSON-serialisable dict
    keyed by human-readable tag name. Most images in this project's
    dataset have none at all - phones strip it, WhatsApp strips it,
    a screenshot never had it - so "no EXIF" has to be the silent,
    common case rather than an exception every caller has to guard
    against. Any tag whose value can't be decoded to text is dropped,
    not surfaced as null - a byte string that isn't valid UTF-8 isn't
    useful evidence either way.
    """
    try:
        import piexif

        raw = piexif.load(str(path))
    except Exception:
        return {}

    result: dict[str, Any] = {}
    for ifd_name, tags in raw.items():
        if ifd_name == "thumbnail" or not isinstance(tags, dict):
            continue
        tag_info = piexif.TAGS.get(ifd_name, {})
        ifd_result = {}
        for tag_id, value in tags.items():
            safe_value = _json_safe(value)
            if safe_value is _DROPPED:
                continue
            name = tag_info.get(tag_id, {}).get("name", str(tag_id))
            ifd_result[name] = safe_value
        if ifd_result:
            result[ifd_name] = ifd_result
    return result


# ---------------------------------------------------------------------------
# Ingest
# ---------------------------------------------------------------------------


from .timing import measured


@measured('admission.index_image')
def ingest_image(
    conn: sqlite3.Connection,
    case_id: str,
    path: Union[str, Path],
    embedder: Optional[CLIPEmbedder] = None,
    embedding: Optional[list[float]] = None,
) -> Image:
    """
    Turn one file on disk into a saved Image row. By the time this
    returns, the photo's hashes and embedding are already in the
    database - available to a similarity search from a case that
    doesn't exist yet.
    """
    path = Path(path)
    phash, dhash = compute_hashes(path)
    image = Image(
        image_id=str(uuid4()),
        case_id=case_id,
        path=str(path),
        content_hash=compute_sha256(path),
        phash=phash,
        dhash=dhash,
        embedding=embedding if embedding is not None else (embedder or _default_embedder).embed(path),
        exif=extract_exif(path),
    )
    db.save_image(conn, image)
    return image


def ingest_case(
    conn: sqlite3.Connection,
    case: Case,
    image_paths: Iterable[Union[str, Path]],
) -> list[Image]:
    """Save the case, ingest every image, then log one audit event for the batch."""
    db.insert_case(conn, case)
    images = [ingest_image(conn, case.case_id, path) for path in image_paths]
    db.log_audit_event(
        conn,
        AuditEvent(
            event_type="case_ingested",
            case_id=case.case_id,
            details={"image_count": len(images), "paths": [img.path for img in images]},
        ),
    )
    return images


# ---------------------------------------------------------------------------
# Similarity search
# ---------------------------------------------------------------------------


def find_similar(
    conn: sqlite3.Connection,
    embedding: Sequence[float],
    exclude_case: str,
    top_k: int = 10,
) -> list[tuple[Image, float]]:
    """
    Brute-force cosine-similarity search over every embedding ever
    ingested, excluding the querying case's own images. Done in numpy
    because sqlite has no vector type: at 800 cases and a handful of
    photos each, this is a few thousand 512-dim dot products end to
    end, sub-millisecond, not worth indexing yet. The pgvector
    migration note in db.py's module docstring is exactly for the day
    that stops being true - swap this function's body for an
    `ORDER BY embedding <=> query LIMIT top_k` ivfflat/hnsw query and
    every caller of find_similar() is unaffected.
    """
    candidates = [
        img for img in db.get_all_images(conn) if img.case_id != exclude_case and img.embedding is not None
    ]
    if not candidates:
        return []

    matrix = np.asarray([c.embedding for c in candidates], dtype=np.float64)
    query = np.asarray(embedding, dtype=np.float64)
    query_norm = np.linalg.norm(query)
    if query_norm == 0.0:
        return []

    matrix_norms = np.linalg.norm(matrix, axis=1)
    denom = matrix_norms * query_norm
    sims = np.divide(matrix @ query, denom, out=np.zeros_like(denom), where=denom != 0)

    order = np.argsort(-sims)[:top_k]
    return [(candidates[i], float(sims[i])) for i in order]
