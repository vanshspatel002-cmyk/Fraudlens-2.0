"""
fraudlens.checks.external_corpus
==================================

Check 4 - "has this photo appeared somewhere outside this insurer?"

--------------------------------------------------------------------
SIMULATION NOTICE - read before citing any number this check produces
--------------------------------------------------------------------
In production this check would call a commercial reverse-image-search
API. TinEye is the realistic option at roughly Rs 3 per query with no
free tier (hence cost_inr = 3.0 below, so a cost-per-case metric prices
this correctly even though today it costs nothing to run); there is no
public Google Lens API to use instead.

What it actually does here is query a LOCAL 400-image corpus under
data/external/corpus/ - images src/generate_dataset.py deliberately
reserved and moved out of the pool that genuine cases draw from, then
handed to EXTERNAL_SOURCING cases. The interface, the metrics, the
thresholds, and the Finding it emits are identical to what the API
version would produce; only the index being searched differs.

The limitation this creates is real and is stated here, in the code,
rather than only in a report: a local corpus of 400 known images cannot
tell you the recall a web-scale index would achieve. Recall measured
against it is an upper bound produced under ideal conditions (every
"external" image is, by construction, definitely in the index). A real
TinEye query against a photo lifted from a used-car listing might find
nothing at all. Treat recall from this check as "the plumbing works",
not as "we detect externally-sourced images this well".
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

import numpy as np

from .. import ingest
from ..models import CheckCategory, Finding, Image, Verdict
from .base import Check, CheckContext, register_check

EXTERNAL_CORPUS_DIR = Path("data/external/corpus")
CORPUS_INDEX_PATH = Path("data/external/corpus_index.json")


def _lerp_confidence(value: float, lo: float, hi: float, conf_at_lo: float, conf_at_hi: float) -> float:
    if hi == lo:
        return conf_at_hi
    t = max(0.0, min(1.0, (value - lo) / (hi - lo)))
    return conf_at_lo + t * (conf_at_hi - conf_at_lo)


# ---------------------------------------------------------------------------
# The index
# ---------------------------------------------------------------------------


class CorpusIndex:
    """
    pHash + CLIP index over the external corpus, persisted to
    CORPUS_INDEX_PATH.

    Built once and cached because embedding 400 images on CPU is minutes
    of work that must not happen on every run, let alone every case -
    loading the cached index parses JSON and stacks one numpy array, and
    that's it. Rebuilt only when the corpus file count changes, matching
    the invalidation rule src/generate_dataset.py's own caches use: this
    corpus is only ever written by reserve_external_corpus() moving whole
    files in, so a changed count is exactly what "the corpus changed"
    looks like.
    """

    def __init__(self, filenames: list[str], phashes: list[str], embeddings: np.ndarray) -> None:
        self.filenames = filenames
        self.phashes = phashes
        self.embeddings = embeddings

    def __len__(self) -> int:
        return len(self.filenames)

    @classmethod
    def build(cls, corpus_dir: Path = EXTERNAL_CORPUS_DIR) -> "CorpusIndex":
        paths = sorted(corpus_dir.glob("*.jpg"))
        filenames, phashes, vectors = [], [], []
        for path in paths:
            phash, _ = ingest.compute_hashes(path)
            filenames.append(path.name)
            phashes.append(phash)
            vectors.append(ingest._default_embedder.embed(path))
        embeddings = np.asarray(vectors, dtype=np.float64) if vectors else np.zeros((0, 512))
        return cls(filenames, phashes, embeddings)

    def save(self, index_path: Path = CORPUS_INDEX_PATH) -> None:
        index_path.parent.mkdir(parents=True, exist_ok=True)
        index_path.write_text(
            json.dumps(
                {
                    "file_count": len(self.filenames),
                    "filenames": self.filenames,
                    "phashes": self.phashes,
                    "embeddings": [[round(v, 6) for v in row] for row in self.embeddings.tolist()],
                }
            )
        )

    @classmethod
    def load_or_build(
        cls, corpus_dir: Path = EXTERNAL_CORPUS_DIR, index_path: Path = CORPUS_INDEX_PATH
    ) -> "CorpusIndex":
        current_count = len(list(corpus_dir.glob("*.jpg")))
        if index_path.exists():
            try:
                data = json.loads(index_path.read_text())
                if data.get("file_count") == current_count:
                    return cls(
                        data["filenames"],
                        data["phashes"],
                        np.asarray(data["embeddings"], dtype=np.float64),
                    )
            except (json.JSONDecodeError, KeyError, ValueError):
                pass  # corrupt or old-format index - fall through and rebuild
        index = cls.build(corpus_dir)
        index.save(index_path)
        return index


# Module-level, lazily populated: one index shared by every case in a
# run, the same reason ingest.CLIPEmbedder is a module global rather than
# per-call.
_index: Optional[CorpusIndex] = None


def get_index() -> CorpusIndex:
    global _index
    if _index is None:
        _index = CorpusIndex.load_or_build()
    return _index


# ---------------------------------------------------------------------------
# The check
# ---------------------------------------------------------------------------


class ExternalCorpusCheck(Check):
    """
    Same two-metric comparison as InternalDuplicateCheck, with a CLIP
    veto on the pHash path: CONCERN requires cosine >= COSINE_FLOOR AND
    (hamming <= HAMMING_CONCERN OR cosine >= COSINE_CONCERN).

    The floor exists because pHash alone produces occasional coincidental
    collisions between semantically unrelated photos - measured on this
    project's own corpus, 3 of 30 flags from the un-vetoed version of
    this logic in InternalDuplicateCheck were exactly that, matching at
    hamming <= 8 with cosine as low as 0.55. Requiring CLIP to also agree
    the images are related costs nothing on a genuine duplicate (which
    scores far above the floor on both metrics) and removes that entire
    error class.
    """

    check_id = "external_corpus"
    category = CheckCategory.HISTORY
    scope = "image"
    cost_inr = 3.0
    requires_perception = False
    target_archetypes = ("EXTERNAL_SOURCING",)
    # 1.0 - 35/35 EXTERNAL_SOURCING recall, and all 4 apparent false
    # positives on clean cases were verified byte-identical (sha256) to a
    # corpus image, i.e. the check was right and the dataset had a
    # residual leak. Corrected false-positive rate 0/560. Same matching
    # logic and same CLIP veto as internal_duplicate, so it earns the same
    # weight - tempered by the SIMULATION NOTICE above: recall against a
    # 400-image local index is an upper bound on web-scale behaviour, but
    # a *match* found is still a near-exact match, and weight governs how
    # much a CONCERN counts, not how often one occurs.
    weight = 1.0
    attributed_to = "image"

    HAMMING_CONCERN = 8
    COSINE_CONCERN = 0.95
    COSINE_FLOOR = 0.90
    COSINE_INCONCLUSIVE = 0.88

    def run(self, ctx: CheckContext) -> list[Finding]:
        cfg = ctx.config
        hamming_concern = cfg.get("external_hamming_concern", self.HAMMING_CONCERN)
        cosine_concern = cfg.get("external_cosine_concern", self.COSINE_CONCERN)
        cosine_floor = cfg.get("external_cosine_floor", self.COSINE_FLOOR)
        cosine_inconclusive = cfg.get("external_cosine_inconclusive", self.COSINE_INCONCLUSIVE)

        index = get_index()
        return [
            self._check_one_image(ctx, image, index, hamming_concern, cosine_concern, cosine_floor, cosine_inconclusive)
            for image in ctx.images
        ]

    def _check_one_image(
        self,
        ctx: CheckContext,
        image: Image,
        index: CorpusIndex,
        hamming_concern: int,
        cosine_concern: float,
        cosine_floor: float,
        cosine_inconclusive: float,
    ) -> Finding:
        def finding(verdict: Verdict, confidence: float, explanation: str, evidence: dict[str, Any]) -> Finding:
            return Finding(
                check_id=self.check_id,
                case_id=ctx.case.case_id,
                category=self.category,
                verdict=verdict,
                confidence=confidence,
                explanation=explanation,
                evidence={"image_id": image.image_id, "corpus_size": len(index), **evidence},
            )

        if image.embedding is None:
            return finding(
                Verdict.INCONCLUSIVE, 0.0,
                "This image has no CLIP embedding to compare against the external image index.",
                {},
            )
        if not len(index):
            return finding(
                Verdict.INCONCLUSIVE, 0.0,
                "The external image index is empty - nothing to compare against.",
                {},
            )

        query = np.asarray(image.embedding, dtype=np.float64)
        norm = np.linalg.norm(query)
        if norm == 0.0:
            return finding(Verdict.INCONCLUSIVE, 0.0, "This image's CLIP embedding is degenerate (zero vector).", {})

        # Corpus embeddings come from CLIPEmbedder and are already
        # L2-normalised, so normalising the query alone makes this dot
        # product a true cosine similarity.
        cosines = index.embeddings @ (query / norm)
        best_by_cosine = int(np.argmax(cosines))

        # The pHash path needs its own candidate: the nearest neighbour by
        # cosine is not necessarily the closest by Hamming distance, and a
        # re-encoded/cropped copy can rank second on CLIP while being a
        # near-exact pHash match.
        hammings = [ingest.hamming_distance(image.phash, p) for p in index.phashes]
        best_by_hamming = int(np.argmin(hammings))

        concern_idx = None
        if float(cosines[best_by_cosine]) >= cosine_concern and float(cosines[best_by_cosine]) >= cosine_floor:
            concern_idx = best_by_cosine
        elif hammings[best_by_hamming] <= hamming_concern and float(cosines[best_by_hamming]) >= cosine_floor:
            concern_idx = best_by_hamming

        if concern_idx is not None:
            cosine = float(cosines[concern_idx])
            hamming = hammings[concern_idx]
            confidence = max(
                _lerp_confidence(cosine, cosine_concern, 1.0, 0.6, 0.95) if cosine >= cosine_concern else 0.0,
                _lerp_confidence(hamming, hamming_concern, 0, 0.6, 0.95) if hamming <= hamming_concern else 0.0,
            )
            return finding(
                Verdict.CONCERN,
                confidence,
                f"This image matches an image found in an external image index "
                f"(semantic similarity {cosine:.2f}).",
                {
                    "matched_filename": index.filenames[concern_idx],
                    "cosine_similarity": round(cosine, 4),
                    "hamming_distance": hamming,
                },
            )

        cosine = float(cosines[best_by_cosine])
        hamming = hammings[best_by_cosine]
        if cosine >= cosine_inconclusive:
            return finding(
                Verdict.INCONCLUSIVE,
                _lerp_confidence(cosine, cosine_inconclusive, cosine_concern, 0.35, 0.6),
                f"This image resembles an image in an external image index "
                f"(semantic similarity {cosine:.2f}) but not closely enough to conclude it is the same photo.",
                {
                    "matched_filename": index.filenames[best_by_cosine],
                    "cosine_similarity": round(cosine, 4),
                    "hamming_distance": hamming,
                },
            )

        return finding(
            Verdict.PASS,
            _lerp_confidence(cosine, 0.0, cosine_inconclusive, 0.9, 0.6),
            f"No matching image found in the external image index "
            f"(closest semantic similarity {cosine:.2f}).",
            {
                "matched_filename": index.filenames[best_by_cosine],
                "cosine_similarity": round(cosine, 4),
                "hamming_distance": hamming,
            },
        )


EXTERNAL_CORPUS_CHECK = register_check(ExternalCorpusCheck())
