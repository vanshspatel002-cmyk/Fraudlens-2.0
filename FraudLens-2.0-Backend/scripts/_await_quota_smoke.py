"""
Wait for the free-tier quota window to roll over, then run the smoke test.

Gemini's free tier resets at midnight *Pacific*, not local midnight, so a
run launched on a new local date can still be a few hours inside the old
quota day. Rather than guess the offset, this probes with the cheapest
possible call and sleeps between attempts.

Not part of the system - a scaffold so an unattended session can finish
TASK 7 the moment quota exists instead of recording another outage.
"""
from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]

from src.llm import get_provider, is_rate_limit_error, reset_key_state

PROBE_INTERVAL = 600      # 10 min; the reset is a wall-clock edge, not a trickle
MAX_WAIT = 4 * 60 * 60    # give up after four hours rather than idle forever


def quota_available() -> bool:
    reset_key_state()
    try:
        get_provider().chat([{"role": "user", "content": "Reply with the single word: ready"}])
        return True
    except Exception as e:  # noqa: BLE001
        if is_rate_limit_error(e):
            return False
        # A non-quota failure is a real problem and must not be silently
        # slept through - surface it immediately.
        print(f"[await] non-quota provider failure: {type(e).__name__}: {e}")
        raise


def main() -> int:
    started = time.monotonic()
    attempt = 0
    while time.monotonic() - started < MAX_WAIT:
        attempt += 1
        if quota_available():
            elapsed = (time.monotonic() - started) / 60
            print(f"[await] quota available after {elapsed:.0f} min ({attempt} probes); running smoke test")
            # The probe consumed one call from key 1; the smoke test rotates
            # on its own, so this costs a case at worst.
            return subprocess.call([sys.executable, "scripts/agent_smoke_test.py", "--limit", "10"])
        print(f"[await] probe {attempt}: still rate-limited; sleeping {PROBE_INTERVAL // 60} min", flush=True)
        time.sleep(PROBE_INTERVAL)

    print("[await] gave up after four hours - quota never returned")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
