"""
fraudlens.checks.retired
==========================

Checks that were built, measured, and withdrawn.

Nothing in this package is imported by src/checks/__init__.py, so nothing
here reaches REGISTRY and nothing here runs. That is the point: a retired
check must be inert by construction, not by remembering to skip it.

The code is kept rather than deleted because a negative result is a
result. Each module here documents what it attempted, what was measured,
and why the mechanism fails - so that the next person to have the same
idea finds the experiment already run instead of running it again.
See outputs/retired_checks.md for the write-up.
"""

from __future__ import annotations

__all__: list[str] = []
