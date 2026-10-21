"""
Shared Gemini quota budget.

Both the ablation driver and the perception pass spend from the same
Google free-tier pool. This module gives them one small coordination
point: every uncached Gemini API attempt reserves a slot in a daily JSON
budget before it reaches the network.

The split is deliberately simple and conservative. The first named
consumer to run on a Pacific quota day gets 60% of the configured daily
allowance; the other named consumer keeps a 40% floor. That prevents the
overnight perception pass from silently starving the ablation driver, and
also lets whichever job starts a fresh quota day make real progress.
"""

from __future__ import annotations

import json
import math
import os
import sys
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator, Optional
from zoneinfo import ZoneInfo

DEFAULT_STATE_PATH = Path("outputs/quota_budget.json")
DEFAULT_DAILY_PER_KEY = 20
KNOWN_CONSUMERS = ("ablation", "perception")
LOCK_TIMEOUT_SECONDS = 10.0
WRITE_RETRY_ATTEMPTS = 5
WRITE_RETRY_DELAY_SECONDS = 0.2


class QuotaBudgetExhausted(RuntimeError):
    """Raised before an API call when this consumer's shared budget is spent."""


class QuotaControlBusy(QuotaBudgetExhausted):
    error_category = 'provider_control_busy'


class QuotaControlInvalid(QuotaBudgetExhausted):
    error_category = 'provider_control_invalid'


def pacific_quota_day(now: Optional[datetime] = None) -> str:
    """Gemini free-tier quotas reset on Google's Pacific quota day."""
    now = now or datetime.now(timezone.utc)
    try:
        pacific = ZoneInfo("America/Los_Angeles")
    except Exception:  # noqa: BLE001 - zone data is present on normal Python installs
        return now.date().isoformat()
    return now.astimezone(pacific).date().isoformat()


def state_path() -> Path:
    return Path(os.getenv("GEMINI_QUOTA_BUDGET", str(DEFAULT_STATE_PATH)))


def daily_per_key() -> int:
    raw = (os.getenv("GEMINI_DAILY_QUOTA_PER_KEY") or "").strip()
    if not raw:
        return DEFAULT_DAILY_PER_KEY
    try:
        return max(1, int(raw))
    except ValueError:
        return DEFAULT_DAILY_PER_KEY


def infer_consumer(default: str = "shared") -> str:
    """
    Prefer an explicit environment variable, with argv-based inference as
    a fallback so existing entrypoints remain light-touch.
    """
    explicit = (os.getenv("GEMINI_QUOTA_CONSUMER") or "").strip().lower()
    if explicit:
        return explicit
    argv = " ".join(sys.argv).replace("\\", "/").lower()
    if "run_ablation.py" in argv or "drive_ablation.py" in argv:
        return "ablation"
    if "src.perception" in argv or "perception.py" in argv:
        return "perception"
    return default


def _base_state(total_daily_quota: int, day: str) -> dict[str, Any]:
    return {
        "quota_day": day,
        "daily_per_key": daily_per_key(),
        "total_daily_quota": total_daily_quota,
        "primary_consumer": None,
        "consumers": {},
        "keys": {},
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }


def _budgets(total_daily_quota: int, primary: str) -> dict[str, int]:
    floor = int(math.floor(total_daily_quota * 0.40))
    primary_budget = total_daily_quota - floor
    other_budget = floor
    budgets = {primary: primary_budget}
    for consumer in KNOWN_CONSUMERS:
        if consumer != primary:
            budgets[consumer] = other_budget
    return budgets


def _ensure_consumer(state: dict[str, Any], consumer: str, total_daily_quota: int) -> None:
    consumers = state.setdefault("consumers", {})
    if consumer not in consumers:
        consumers[consumer] = {"budget": 0, "reserved": 0, "calls": 0}

    if consumer not in KNOWN_CONSUMERS:
        # One-off probes and tests should not eat either named job's floor.
        consumers[consumer]["budget"] = total_daily_quota
        return

    primary = state.get("primary_consumer")
    if primary not in KNOWN_CONSUMERS:
        primary = consumer
        state["primary_consumer"] = primary
    for name, budget in _budgets(total_daily_quota, primary).items():
        consumers.setdefault(name, {"budget": 0, "reserved": 0, "calls": 0})
        consumers[name]["budget"] = budget


def _validate_state(state):
    integer = lambda value: type(value) is int and value >= 0
    valid = (isinstance(state, dict) and isinstance(state.get('quota_day'), str)
        and integer(state.get('daily_per_key')) and state['daily_per_key'] > 0
        and integer(state.get('total_daily_quota')) and state['total_daily_quota'] > 0
        and 'primary_consumer' in state
        and (state['primary_consumer'] is None or isinstance(state['primary_consumer'], str))
        and isinstance(state.get('consumers'), dict) and isinstance(state.get('keys'), dict)
        and isinstance(state.get('updated_at'), str)
        and isinstance(state.get('events', []), list) and isinstance(state.get('history', []), list))
    if valid:
        try:
            datetime.strptime(state['quota_day'], '%Y-%m-%d')
        except ValueError:
            valid = False
        valid = valid and all(isinstance(slot, dict) and all(integer(slot.get(key)) for key in ('budget','reserved','calls'))
                              for slot in state['consumers'].values())
        valid = valid and all(isinstance(slot, dict) and all(integer(slot.get(key)) for key in ('reserved','calls'))
                              for slot in state['keys'].values())
        valid = valid and all(isinstance(event, dict) for event in state.get('events', []))
    if not valid:
        raise QuotaControlInvalid('The existing quota ledger is invalid; restore its audit history before any provider request.')
    for prior in state.get('history', []):
        _validate_state(prior)


def _load_state(path: Path, total_daily_quota: int, day: str) -> dict[str, Any]:
    if path.exists():
        try:
            state = json.loads(path.read_text(encoding="utf-8"))
            _validate_state(state)
            if state.get("quota_day") == day:
                state["total_daily_quota"] = total_daily_quota
                state["daily_per_key"] = daily_per_key()
                return state
            # A legitimate provider quota-day rollover must retain the earlier
            # reservations and outcomes; recovery never erases budget history.
            new_state=_base_state(total_daily_quota,day)
            new_state['history']=[*state.get('history',[]),{k:v for k,v in state.items() if k!='history'}]
            return new_state
        except (OSError, json.JSONDecodeError) as exc:
            raise QuotaControlInvalid('The existing quota ledger is unreadable; restore its audit history before any provider request.') from exc
    return _base_state(total_daily_quota, day)


def _write_state(path: Path, state: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    state["updated_at"] = datetime.now(timezone.utc).isoformat()
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    last_error: Optional[OSError] = None
    for attempt in range(WRITE_RETRY_ATTEMPTS):
        try:
            tmp.replace(path)
            return
        except PermissionError as exc:
            last_error = exc
            if attempt == WRITE_RETRY_ATTEMPTS - 1:
                break
            time.sleep(WRITE_RETRY_DELAY_SECONDS * (attempt + 1))
    if last_error is not None:
        raise last_error


@contextmanager
def _lock(path: Path) -> Iterator[None]:
    lock_path = path.with_suffix(path.suffix + ".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + LOCK_TIMEOUT_SECONDS
    fd: Optional[int] = None
    while fd is None:
        try:
            fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_RDWR)
            os.write(fd, str(os.getpid()).encode("ascii", errors="ignore"))
        except FileExistsError:
            if time.monotonic() >= deadline:
                # A slow living writer is not a stale lock. Deleting its lock
                # admits two writers and can lose counted attempts. Fail closed;
                # interrupted-owner recovery requires an explicit operator audit.
                raise QuotaControlBusy('Shared quota control is locked; no provider request attempted.')
            time.sleep(0.1)
    try:
        yield
    finally:
        try:
            if fd is not None:
                os.close(fd)
        finally:
            try:
                lock_path.unlink()
            except OSError:
                pass


def reserve_call(
    consumer: str,
    key_label: str,
    *,
    keys_configured: int,
    model: str,
    kind: str,
) -> dict[str, Any]:
    """
    Reserve one uncached API attempt.

    Raises QuotaBudgetExhausted before the network call if this consumer
    has used its daily share. The record counts attempts, not just
    successful replies, because retries and 429 probes still compete for
    the same request budget.
    """
    path = state_path()
    total = max(1, keys_configured) * daily_per_key()
    day = pacific_quota_day()
    consumer = (consumer or "shared").strip().lower()
    with _lock(path):
        state = _load_state(path, total, day)
        _ensure_consumer(state, consumer, total)
        slot = state["consumers"][consumer]
        total_reserved = sum(item['reserved'] for item in state['consumers'].values())
        key_reserved = state['keys'].get(key_label, {}).get('reserved', 0)
        if total_reserved >= total or key_reserved >= daily_per_key():
            raise QuotaBudgetExhausted('Shared daily or selected-key attempt budget exhausted; no provider request attempted.')
        if slot["reserved"] >= slot["budget"]:
            _write_state(path, state)
            raise QuotaBudgetExhausted(
                f"{consumer} has used {slot['reserved']}/{slot['budget']} Gemini calls "
                f"for quota day {day}; shared pool total is {total}"
            )
        slot["reserved"] += 1
        slot["calls"] = slot.get("calls", 0) + 1
        key = state.setdefault("keys", {}).setdefault(key_label, {"reserved": 0, "calls": 0})
        key["reserved"] += 1
        key["calls"] = key.get("calls", 0) + 1
        state.setdefault("events", []).append(
            {
                "at": datetime.now(timezone.utc).isoformat(),
                "consumer": consumer,
                "key": key_label,
                "model": model,
                "kind": kind,
            }
        )
        # Keep the file inspectable without letting it grow forever.
        state["events"] = state["events"][-200:]
        _write_state(path, state)
        return state


def snapshot(keys_configured: int) -> dict[str, Any]:
    """Return the current budget state, initialising today's empty file if needed."""
    path = state_path()
    total = max(1, keys_configured) * daily_per_key()
    day = pacific_quota_day()
    with _lock(path):
        state = _load_state(path, total, day)
        state["total_daily_quota"] = total
        state["daily_per_key"] = daily_per_key()
        state.setdefault("consumers", {})
        state.setdefault("keys", {})
        _write_state(path, state)
        return state


def remaining_summary(keys_configured: int) -> dict[str, Any]:
    state = snapshot(keys_configured)
    consumers = state.get("consumers", {})
    used = sum(int(v.get("reserved", 0)) for v in consumers.values())
    total = int(state.get("total_daily_quota", 0))
    return {
        "quota_day": state.get("quota_day"),
        "total_daily_quota": total,
        "used": used,
        "remaining": max(0, total - used),
        "primary_consumer": state.get("primary_consumer"),
        "consumers": {
            name: {
                "budget": int(slot.get("budget", 0)),
                "used": int(slot.get("reserved", 0)),
                "remaining": max(0, int(slot.get("budget", 0)) - int(slot.get("reserved", 0))),
            }
            for name, slot in sorted(consumers.items())
        },
    }
