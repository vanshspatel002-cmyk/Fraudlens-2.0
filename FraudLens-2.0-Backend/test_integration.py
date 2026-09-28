"""
Integration test — the seams, not the units.

This wraps scripts/verify_integration.py so it runs as part of the test suite
in the same shape as the other suites here.

It exists because the `findings` table was empty for all 800 cases and no test
caught it. Every unit was correct: the checks produced findings, the API read
findings, the interface rendered them. What was missing was a *writer* on the
path actually in use, and a seam that neither side owns is invisible to tests
that only ever exercise one side of it.

So this asserts that data survives the whole pipeline - submission, checks,
adjudication, persistence, and retrieval back through the HTTP API - rather
than that any component behaves correctly in isolation.

No LLM calls: the adjudicator is stubbed. Runs against a temporary copy of the
database, so it is safe alongside a live ablation run.

Run with:
    python test_integration.py
"""

from __future__ import annotations

import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

sys.path.insert(0, str(Path(__file__).resolve().parent))

from scripts.verify_integration import main as verify


def run_all() -> bool:
    print("--- test_pipeline_carries_data_end_to_end ---")
    code = verify()
    if code == 0:
        print("PASS  test_pipeline_carries_data_end_to_end")
        print("\n1 passed, 0 failed")
        return True
    print("FAIL  test_pipeline_carries_data_end_to_end")
    print("\n0 passed, 1 failed")
    return False


if __name__ == "__main__":
    sys.exit(0 if run_all() else 1)
