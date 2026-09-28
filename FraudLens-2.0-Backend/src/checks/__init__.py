"""
fraudlens.checks
==================

Public entry point for the check framework - `from src.checks import
run_checks, ALL_CHECKS, REGISTRY`. Importing this package is what
actually populates REGISTRY: each concrete module (duplicate.py,
metadata.py, threshold.py, and whatever check gets added next) calls
register_check() at its own module level, and importing it here is what
triggers that. ALL_CHECKS is built after those imports for exactly that
reason - see src/checks/base.py's module docstring for why it can't live
in base.py itself.
"""

from __future__ import annotations

from .base import Check, CheckContext, REGISTRY, register_check, run_checks
from .ai_detection import AIGenerationCheck
from .baseline_corruption import BaselineCorruptionCheck
from .damage_plausibility import DamagePlausibilityCheck
from .digital_edit import DigitalEditCheck
from .duplicate import InternalDuplicateCheck
from .entity_graph import EntityGraphCheck
from .view_completeness import ViewCompletenessCheck
from .baseline_linkage import BaselineLinkageCheck
from .severity_progression import SeverityProgressionCheck
from .external_corpus import ExternalCorpusCheck
from .metadata import MetadataCheck
from .plate_ocr import PlateOCRCheck
from .provenance import C2PACheck
from .scene_consistency import SceneConsistencyCheck
from .threshold import ThresholdGamingCheck

# vehicle_consistency was retired after measurement - see
# src/checks/retired/vehicle_consistency.py and outputs/retired_checks.md.
# It is not imported here, which is the only thing keeping it out of
# REGISTRY, and deliberately so.

ALL_CHECKS: list[str] = list(REGISTRY.keys())

__all__ = [
    "Check",
    "CheckContext",
    "REGISTRY",
    "register_check",
    "run_checks",
    "ALL_CHECKS",
    "AIGenerationCheck",
    "BaselineCorruptionCheck",
    "C2PACheck",
    "DamagePlausibilityCheck",
    "DigitalEditCheck",
    "ExternalCorpusCheck",
    "InternalDuplicateCheck",
    "MetadataCheck",
    "PlateOCRCheck",
    "SceneConsistencyCheck",
    "ThresholdGamingCheck",
]
