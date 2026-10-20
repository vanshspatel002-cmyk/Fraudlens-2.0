"""
fraudlens.checks.severity_progression
=======================================

"This vehicle has claimed before. Does the damage tell a coherent story?"

Damage to a vehicle is monotone between repairs. It accumulates until
someone fixes it, and then it resets. What it does not do is oscillate: a
car cannot be severely damaged in March, moderately damaged in April, and
severely damaged again in May unless something was repaired in between —
and a repair leaves a record.

That gives a check no single claim can support. Every claim in a repeat
sequence may be individually plausible, with genuine photographs of real
damage, while the *sequence* is impossible. This is the same shape of
problem as `entity_graph` and `baseline_linkage`: the contradiction lives
between cases, not inside one.

--------------------------------------------------------------------------
The two patterns
--------------------------------------------------------------------------
**Non-monotone severity.** Severity falls and then rises again with no
repair-completed record in the interval. Falling severity by itself is
ordinary — it means the car was repaired, or the second incident was
milder — so the check requires the *recovery*: down, then up. A single
downward step is not evidence of anything.

**Rapid repeat on the same panel.** The same damaged region claimed twice
inside `SAME_PANEL_WINDOW_DAYS`, *at the same or lesser severity*. Panels do
get damaged twice, but rarely within three months, and a genuine second
incident usually shows the first one's repair.

The severity qualifier was added after measurement. Without it the rule
flagged vehicles whose damage simply worsened on the same panel - being hit
again before the first dent was fixed, which is ordinary. A second claim at
the same or lesser severity is the suspicious shape, because that is what
claiming twice for one loss looks like.

--------------------------------------------------------------------------
Why severity comes from perception rather than from the claim
--------------------------------------------------------------------------
The claimed amount is what the claimant asserts; the perceived severity is
what the photographs show. Using the amount would make this a check on
consistency of *claims*, which a coordinated fraudster controls completely.
Using perception makes it a check on consistency of *evidence*, which is
harder to fabricate across several submissions.

The cost is coverage: severity is only known where the vision pass has run,
so the check returns INCONCLUSIVE rather than PASS when a prior claim's
images were never described. An unread prior claim is not evidence of
coherence.

--------------------------------------------------------------------------
Measured on a copy, because the corpus has no repeat claimants
--------------------------------------------------------------------------
The generator assigns every case a unique registration, so no vehicle ever
claims twice and this check cannot fire on the production corpus. Measured
instead against injected repeat sequences
(`scripts/inject_repeat_claims.py`, `outputs/severity_progression_measurement.json`),
in the same way `entity_graph` was measured against an injected ring.
"""

from __future__ import annotations

import sqlite3
from .. import db, ingest
from datetime import datetime, timezone
from typing import Any, Optional

from ..models import CheckCategory, Finding, Verdict
from .base import Check, CheckContext, register_check

SEVERITY_ORDER = {"none": 0, "minor": 1, "moderate": 2, "severe": 3}

# Two claims on the same panel inside this window are a repeat, not a
# coincidence. A judgement call rather than a measured threshold.
SAME_PANEL_WINDOW_DAYS = 90

# Audit events that would legitimately explain a severity reset.
REPAIR_EVENT_TYPES = ("repair_completed", "claim_settled", "vehicle_repaired")


class SeverityProgressionCheck(Check):
    agent_types = ('claims',)
    check_id = "severity_progression"
    category = CheckCategory.ECONOMIC
    scope = "case"
    cost_inr = 0.0
    requires_perception = True
    # No archetype in this corpus generates repeat claims, so there is
    # nothing here to be measured against. Naming a target it cannot fire on
    # would credit it with coverage it does not have.
    target_archetypes = ()
    # 1.0 by argument, measured against injected sequences rather than
    # against the production corpus. A severity sequence that falls and
    # recovers with no repair on record is a contradiction between stored
    # observations rather than an estimate from pixels - the same class of
    # evidence as a hash match. Re-derive against real repeat-claim data,
    # where repair records are messier than any generated corpus.
    weight = 1.0
    attributed_to = "vehicle"
    limitation = (
        "The original unaugmented research corpus used unique registrations. In authored scenarios, 8/8 oscillating sequences were flagged with 0/12 monotone/repaired controls flagged; this does not establish prospective accuracy."
    )

    def run(self, ctx: CheckContext) -> list[Finding]:
        case = ctx.case
        if case.agent_type != "claims":
            return []

        history = self._claim_history(ctx, case)
        evidence: dict[str, Any] = {
            "vehicle_registration": case.vehicle_registration,
            "claims_on_this_vehicle": len(history),
            "same_panel_window_days": SAME_PANEL_WINDOW_DAYS,
        }

        if len(history) < 2:
            return [self._finding(
                case.case_id, Verdict.INCONCLUSIVE, 0.0,
                "No earlier claim is on record for this vehicle, so there is no "
                "sequence of damage to be inconsistent.",
                {**evidence, 'execution_state': 'not_applicable', 'reason': 'no_prior_claim_sequence'})]

        evidence["sequence"] = [
            {"case_id": h["case_id"], "declared_time": h["declared_time"],
             "severity": h["severity"], "description": (h["description"] or "")[:80]}
            for h in history
        ]

        if any(item['when'] is None for item in history) or len({item['when'].utcoffset() is None for item in history}) > 1:
            return [self._finding(case.case_id, Verdict.INCONCLUSIVE, 0.0,
                'The damage sequence cannot be compared because claim timestamps are missing or use incompatible timezone bases.',
                {**evidence, 'execution_state': 'inconclusive', 'reason': 'chronology_unverified'})]

        known = [h for h in history if h["severity"] in SEVERITY_ORDER]
        if len(known) < 2:
            return [self._finding(
                case.case_id, Verdict.INCONCLUSIVE, 0.0,
                f"This vehicle has {len(history)} claims on record, but the damage in "
                f"fewer than two of them has been assessed, so the sequence cannot be "
                f"checked for coherence.",
                evidence)]

        oscillation = self._find_oscillation(ctx, known, case.vehicle_registration)
        if oscillation:
            low, high = oscillation["trough"], oscillation["recovery"]
            evidence["oscillation"] = oscillation
            return [self._finding(
                case.case_id, Verdict.CONCERN, 0.8,
                f"The damage recorded for this vehicle does not progress coherently: "
                f"{oscillation['peak']['severity']} in {oscillation['peak']['case_id']}, "
                f"then {low['severity']} in {low['case_id']}, then "
                f"{high['severity']} in {high['case_id']}, with no repair recorded in "
                f"between. Damage does not heal on its own, so either a repair is "
                f"missing from the record or one of these assessments is wrong.",
                evidence)]

        repeat = self._same_panel_repeat(ctx, known, case.vehicle_registration)
        if repeat:
            evidence["same_panel_repeat"] = repeat
            return [self._finding(
                case.case_id, Verdict.CONCERN, 0.65,
                f"The same area of the vehicle appears in two claims "
                f"{repeat['days_apart']} days apart ({repeat['first']} and "
                f"{repeat['second']}), described both times as "
                f"\"{repeat['shared_terms']}\". A panel damaged twice in under "
                f"{SAME_PANEL_WINDOW_DAYS} days is unusual, and the second claim "
                f"should show the first one's repair.",
                evidence)]

        return [self._finding(
            case.case_id, Verdict.PASS, 0.7,
            f"The {len(known)} assessed claims on this vehicle show damage that "
            f"accumulates or resets coherently.",
            evidence)]

    # -- helpers ---------------------------------------------------------

    def _finding(self, case_id: str, verdict: Verdict, confidence: float,
                 explanation: str, evidence: dict[str, Any]) -> Finding:
        return Finding(
            check_id=self.check_id, case_id=case_id, category=self.category,
            verdict=verdict, confidence=confidence, explanation=explanation,
            evidence=evidence,
        )

    def _claim_history(self, ctx: CheckContext, case: Any) -> list[dict[str, Any]]:
        """Every claim on this registration, oldest first, with perceived severity."""
        if not case.vehicle_registration:
            return []
        cutoff_sql, values = ingest.evaluation_cutoff_filter(ctx.conn, ctx.config.get('evaluation_cutoff'))
        rows = ctx.conn.execute(
                "SELECT case_id, declared_time FROM cases "
                "WHERE vehicle_registration = ? AND agent_type = 'claims'" + cutoff_sql,
                (case.vehicle_registration, *values),
            ).fetchall()

        out: list[dict[str, Any]] = []
        for case_id, declared in rows:
            when = self._as_datetime(declared)
            current = self._as_datetime(case.declared_time)
            if (when is not None and current is not None
                    and (when.utcoffset() is None) == (current.utcoffset() is None) and when > current):
                continue
            severity, description = self._severity_for(ctx, case_id)
            out.append({
                "case_id": case_id,
                "declared_time": str(declared) if declared else None,
                "when": when,
                "severity": severity,
                "description": description,
            })
        def chronology_key(item):
            when = item['when']
            # Different UTC offsets must sort by the actual instant. The run
            # guard still rejects missing or mixed aware/naive chronology.
            if when is not None and when.utcoffset() is not None:
                when = when.astimezone(timezone.utc).replace(tzinfo=None)
            return when is None, when or datetime.max
        return sorted(out, key=chronology_key)

    def _severity_for(self, ctx: CheckContext, case_id: str) -> tuple[Optional[str], Optional[str]]:
        """Worst perceived severity across a case's images, with its description."""
        from ..perception import perception_record_usable
        worst, worst_rank, description = None, -1, None
        if case_id == ctx.case.case_id:
            images = ctx.images  # This run explicitly records its own evidence version.
        else:
            cutoff_sql, values = ingest.evaluation_cutoff_filter(ctx.conn, ctx.config.get('evaluation_cutoff'))
            images = [db._image_from_row(row) for row in ctx.conn.execute('SELECT * FROM images WHERE case_id=?' + cutoff_sql, (case_id,*values))]
        for image in images:
            record = db.get_perception(ctx.conn, image.content_hash)
            if not perception_record_usable(record):
                continue
            s = (record.damage_severity or "").strip().lower()
            if s in SEVERITY_ORDER and SEVERITY_ORDER[s] > worst_rank:
                worst, worst_rank, description = s, SEVERITY_ORDER[s], record.damage_description
        return worst, description

    def _find_oscillation(self, ctx: CheckContext, history: list[dict[str, Any]],
                          registration: Optional[str]) -> Optional[dict[str, Any]]:
        """
        A fall then a rise, with no repair recorded in the interval.

        Requires the recovery. A single downward step means the car was
        repaired or the next incident was milder, both of which are ordinary.
        """
        for i in range(len(history) - 2):
            a, b, c = history[i], history[i + 1], history[i + 2]
            ra, rb, rc = (SEVERITY_ORDER[a["severity"]], SEVERITY_ORDER[b["severity"]],
                          SEVERITY_ORDER[c["severity"]])
            if not (ra > rb and rc > rb):
                continue
            if self._repair_between(ctx, a, c, registration):
                continue
            return {
                "peak": {"case_id": a["case_id"], "severity": a["severity"]},
                "trough": {"case_id": b["case_id"], "severity": b["severity"]},
                "recovery": {"case_id": c["case_id"], "severity": c["severity"]},
                "repair_recorded_between": False,
            }
        return None

    def _repair_between(self, ctx: CheckContext, first: dict, last: dict,
                        registration: Optional[str]) -> bool:
        """
        Did anything on record explain a reset between these two claims?

        Searches every claim on the vehicle, not just the two endpoints. The
        first version queried `case_id IN (first, last)` and so never looked
        at the middle claim - which is exactly where a repair between two
        incidents is recorded. It flagged 6 of 6 controls that carried an
        explicit repair_completed event, because it never read them.
        """
        if first["when"] is None or last["when"] is None or not registration:
            return False
        cutoff_sql, values = ingest.evaluation_cutoff_filter(ctx.conn, ctx.config.get('evaluation_cutoff'), ('a.created_at',))
        rows = ctx.conn.execute(
                "SELECT a.event_type, a.created_at FROM audit_log a "
                "JOIN cases c ON c.case_id = a.case_id "
                "WHERE c.vehicle_registration = ?" + cutoff_sql,
                (registration, *values),
            ).fetchall()
        for event_type, created in rows:
            if event_type in REPAIR_EVENT_TYPES:
                when = self._as_datetime(created)
                if when is None or (when.utcoffset() is None) != (first['when'].utcoffset() is None):
                    raise ValueError('Recorded repair timing cannot be compared with the claim chronology.')
                if when is not None and first["when"] <= when <= last["when"]:
                    return True
        return False

    def _same_panel_repeat(self, ctx: CheckContext, history: list[dict[str, Any]],
                           registration: Optional[str]) -> Optional[dict[str, Any]]:
        """
        Two claims describing the same area within the window.

        Panel identity is approximated by shared vocabulary in the damage
        description - there is no panel classifier, and inventing one would
        be a guess presented as a finding. Only distinctive panel words
        count, so "damage to the car" does not match "damage to the car".
        """
        panel_words = {
            "bumper", "bonnet", "hood", "fender", "wing", "door", "tailgate",
            "boot", "trunk", "quarter", "windscreen", "windshield", "mirror",
            "headlamp", "headlight", "taillight", "grille", "roof", "sill",
        }
        for i in range(len(history) - 1):
            for j in range(i + 1, len(history)):
                a, b = history[i], history[j]
                if a["when"] is None or b["when"] is None:
                    continue
                days = abs((b["when"] - a["when"]).days)
                if days > SAME_PANEL_WINDOW_DAYS:
                    continue
                # Worsening damage on the same panel is accumulation, not a
                # repeat claim: the car was hit again before anyone fixed the
                # first dent, which is ordinary. Only a second claim at the
                # same or lesser severity is suspicious, because that is the
                # shape of claiming twice for one loss. Without this the rule
                # flagged 3 of 6 controls whose damage simply got worse.
                ra = SEVERITY_ORDER.get(a["severity"], -1)
                rb = SEVERITY_ORDER.get(b["severity"], -1)
                if rb > ra:
                    continue
                # A recorded repair explains a second claim on the same panel
                # just as it explains a severity reset. Wiring repair
                # awareness into the oscillation branch alone left this one
                # flagging 3 of 6 controls that carried an explicit
                # repair_completed event.
                if self._repair_between(ctx, a, b, registration):
                    continue
                wa = {w for w in (a["description"] or "").lower().split() if w in panel_words}
                wb = {w for w in (b["description"] or "").lower().split() if w in panel_words}
                shared = wa & wb
                if shared:
                    return {"first": a["case_id"], "second": b["case_id"],
                            "days_apart": days, "shared_terms": ", ".join(sorted(shared))}
        return None

    @staticmethod
    def _as_datetime(value: Any) -> Optional[datetime]:
        if isinstance(value, datetime):
            return value
        if isinstance(value, str):
            try:
                return datetime.fromisoformat(value)
            except ValueError:
                return None
        return None


SEVERITY_PROGRESSION_CHECK = register_check(SeverityProgressionCheck())
