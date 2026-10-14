"""
fraudlens.vehicle_gate
======================

Local CLIP gate for intake uploads. This is intentionally not perception:
it never calls the vision LLM, never writes a case row, and never consumes a
perception cache entry. It answers only the admission question: did the upload
include at least one likely vehicle image?
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Sequence, Union

import numpy as np

from .ingest import CLIPEmbedder, _default_embedder

VEHICLE_PROMPTS = (
    "a photo of a car, motorcycle, truck, scooter, bus, or other motor vehicle",
    "an insurance claim photo showing a motor vehicle",
    "a close-up photo of vehicle damage or vehicle body panels",
)

NON_VEHICLE_PROMPTS = (
    "a photo of a person with no vehicle",
    "a photo of a document, form, letter, invoice, or identity card",
    "a landscape, room, street, or unrelated scene with no vehicle",
)

# Calibrated on 16 existing corpus vehicle images from data/curated plus
# synthetic document/person/unrelated-scene negatives. The absolute vehicle
# score separated the sets (vehicle min 0.1766, negative max 0.1712), while one
# real corpus vehicle had a small negative margin against the broad "unrelated
# scene" prompt. Keep both checks: a vehicle-score threshold for separation and
# a low margin floor to reject clear non-vehicles without rejecting busy scenes.
VEHICLE_SCORE_THRESHOLD = 0.175
VEHICLE_MARGIN_FLOOR = -0.020

_TEXT_EMBEDDINGS: Optional[np.ndarray] = None


@dataclass
class VehicleGateScore:
    filename: str
    vehicle_score: float
    non_vehicle_score: float
    margin: float
    accepted: bool
    predicted_category: str
    embedding: Optional[list[float]] = None

    def to_dict(self) -> dict[str, object]:
        return {
            "filename": self.filename,
            "vehicle_score": round(self.vehicle_score, 6),
            "non_vehicle_score": round(self.non_vehicle_score, 6),
            "margin": round(self.margin, 6),
            "vehicle_score_threshold": VEHICLE_SCORE_THRESHOLD,
            "margin_floor": VEHICLE_MARGIN_FLOOR,
            "accepted": self.accepted,
            "predicted_category": self.predicted_category,
        }


def _text_embeddings(embedder: CLIPEmbedder) -> np.ndarray:
    global _TEXT_EMBEDDINGS
    if _TEXT_EMBEDDINGS is None:
        prompts = [*VEHICLE_PROMPTS, *NON_VEHICLE_PROMPTS]
        _TEXT_EMBEDDINGS = np.asarray(embedder.embed_texts(prompts), dtype=np.float64)
    return _TEXT_EMBEDDINGS


def classify_image(
    path: Union[str, Path],
    filename: Optional[str] = None,
    embedder: Optional[CLIPEmbedder] = None,
) -> VehicleGateScore:
    embedder = embedder or _default_embedder
    image_embedding = np.asarray(embedder.embed(path), dtype=np.float64)
    text_embeddings = _text_embeddings(embedder)
    sims = text_embeddings @ image_embedding
    vehicle_score = float(np.max(sims[:len(VEHICLE_PROMPTS)]))
    non_vehicle_score = float(np.max(sims[len(VEHICLE_PROMPTS):]))
    margin = vehicle_score - non_vehicle_score
    accepted = vehicle_score >= VEHICLE_SCORE_THRESHOLD and margin >= VEHICLE_MARGIN_FLOOR
    return VehicleGateScore(
        filename=filename or Path(path).name,
        vehicle_score=vehicle_score,
        non_vehicle_score=non_vehicle_score,
        margin=margin,
        accepted=accepted,
        predicted_category="vehicle" if accepted else "non_vehicle",
        embedding=image_embedding.tolist(),
    )


def classify_uploads(
    paths: Sequence[Union[str, Path]],
    filenames: Sequence[str],
    embedder: Optional[CLIPEmbedder] = None,
) -> list[VehicleGateScore]:
    return [
        classify_image(path, filename=name, embedder=embedder)
        for path, name in zip(paths, filenames)
    ]
