"""
fraudlens.checks.baseline_linkage
===================================

"This vehicle was inspected as undamaged. How long ago?"

The counterpart to `baseline_corruption`, running on the other side of the
policy and looking in the other direction.

`baseline_corruption` sits on an underwriting inspection and asks whether
the photographs contradict the declaration. It cannot detect the
AI_GENERATED_BASELINE attack, because that attack fabricates the *absence*
of damage: the synthetic photograph and the declaration agree perfectly, and
there is nothing in the inspection itself to find.

This check sits on the *claim* and looks backwards. The attack's signature
is not visual at all — it is temporal. An applicant whose vehicle is already
damaged submits a synthetic photograph of an intact one at inception, waits,
and then claims for the damage the car already had. What gives it away is
the interval: a vehicle certified undamaged that files a moderate-or-worse
damage claim three weeks later either had extraordinarily bad luck or was
never undamaged.

--------------------------------------------------------------------------
Why this is the right shape for the attack
--------------------------------------------------------------------------
No forensic examination of either image set can see this. The inspection
photographs are of an intact vehicle and the claim photographs are of a
damaged one, and both are internally consistent. The contradiction exists
only in the relationship between two cases, which is why it needs a check
that joins them.

It is also the strongest signal available in production, and the one this
corpus was least able to express: matching requires the same vehicle to
appear in both an inspection and a claim, which the generator did not
originally produce.

--------------------------------------------------------------------------
Deliberately conservative
--------------------------------------------------------------------------
Short intervals happen honestly. Vehicles are damaged days after being
insured, which is the entire reason people buy insurance, so a bare
"claim soon after inspection" rule would flag ordinary misfortune.

Three conditions must hold together before this raises a concern:

  1. the inspection and the claim share a vehicle registration or policy,
  2. the claim was filed within `WINDOW_DAYS` of the inspection, and
  3. the claimed damage is moderate or worse.

The third matters most. A scuffed bumper two weeks after inception is
unremarkable; structural damage in the same window, on a vehicle certified
intact, is not. Where severity is unknown the check returns INCONCLUSIVE
rather than assuming the worse case.
"""

from __future__ import annotations

import sqlite3
from .. import db
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from ..models import CheckCategory, Finding, Verdict
from .base import Check, CheckContext, register_check

# Beyond this, an intervening incident is the more likely explanation than a
# corrupted baseline. A judgement call rather than a measured threshold, noted
# as such: the generator's own linked claims fall 5-25 days out, so this is
# not tuned to the corpus.
WINDOW_DAYS = 30

# Severities that make a short interval suspicious. A minor scuff shortly
# after inception is ordinary.
SERIOUS_SEVERITIES = ("moderate", "severe")

FIELDS = ("vehicle_registration", "policy_number")


class BaselineLinkageCheck(Check):
    check_id = "baseline_linkage"
    category = CheckCategory.HISTORY
    scope = "case"
    cost_inr = 0.0
    requires_perception = False
    target_archetypes = ("AI_GENERATED_BASELINE",)
    # 1.0. A vehicle certified undamaged that claims for moderate-or-worse
    # damage inside a month is close to fact rather than inference: the two
    # records cannot both be true. This is the same class of evidence as a
    # hash match - a contradiction between two stored records rather than an
    # estimate from pixels. Re-derive against real data, where honest
    # short-interval claims are far more common than in any generated corpus.
    weight = 1.0
    attributed_to = "vehicle"
    limitation = (
        "No underwriting inspection shares a registration with a claim on this corpus; verified 20/20 against injected links."
    )

    def run(self, ctx: CheckContext) -> list[Finding]:
        case = ctx.case
        # Underwriting inspections are the thing being looked back AT, not the
        # thing looking back. Returning [] keeps them out of the denominator.
        if case.agent_type != "claims":
            return []

        inspections = self._prior_inspections(ctx.conn, case)
        evidence: dict[str, Any] = {
            "matched_on": list(FIELDS),
            "window_days": WINDOW_DAYS,
            "prior_inspections_found": len(inspections),
        }

        if not inspections:
            return [self._finding(
                case.case_id, Verdict.PASS, 0.6,
                "No prior break-in inspection is on record for this vehicle, so there "
                "is no declared baseline for this claim to contradict.",
                evidence)]

        recent = [i for i in inspections if i["days_before_claim"] is not None
                  and 0 <= i["days_before_claim"] <= WINDOW_DAYS]
        evidence["inspections"] = inspections[:5]

        if not recent:
            nearest = min((i["days_before_claim"] for i in inspections
                           if i["days_before_claim"] is not None), default=None)
            return [self._finding(
                case.case_id, Verdict.PASS, 0.6,
                f"The most recent break-in inspection for this vehicle was "
                f"{nearest} day(s) before the loss, outside the {WINDOW_DAYS}-day "
                f"window in which a corrupted baseline would show."
                if nearest is not None else
                "No inspection date could be compared against the declared loss.",
                evidence)]

        severity = self._claim_severity(ctx)
        evidence["claimed_severity"] = severity or "unknown"
        closest = min(recent, key=lambda i: i["days_before_claim"])
        evidence["closest_inspection"] = closest

        if severity is None:
            return [self._finding(
                case.case_id, Verdict.INCONCLUSIVE, 0.0,
                f"This vehicle was inspected as undamaged {closest['days_before_claim']} "
                f"day(s) before the declared loss ({closest['case_id']}), but the "
                f"severity of the claimed damage could not be read, so the two records "
                f"cannot be compared.",
                evidence)]

        if severity in SERIOUS_SEVERITIES:
            days = closest["days_before_claim"]
            # Sooner is worse: a claim the week after inception is harder to
            # explain than one at the window's edge.
            confidence = min(0.9, 0.6 + 0.3 * (1.0 - days / max(1, WINDOW_DAYS)))
            return [self._finding(
                case.case_id, Verdict.CONCERN, confidence,
                f"This vehicle passed a break-in inspection as undamaged just "
                f"{days} day(s) before the declared loss ({closest['case_id']}), and "
                f"this claim reports {severity} damage. Either the damage was "
                f"sustained in that window, or the inspection did not record the "
                f"vehicle's true condition. The inspection photographs should be "
                f"compared against these before the claim is settled.",
                evidence)]

        return [self._finding(
            case.case_id, Verdict.PASS, 0.7,
            f"A break-in inspection {closest['days_before_claim']} day(s) before the "
            f"loss recorded no damage, and this claim reports {severity} damage. Minor "
            f"damage shortly after inception is unremarkable.",
            evidence)]

    # -- helpers ---------------------------------------------------------

    def _finding(self, case_id: str, verdict: Verdict, confidence: float,
                 explanation: str, evidence: dict[str, Any]) -> Finding:
        return Finding(
            check_id=self.check_id, case_id=case_id, category=self.category,
            verdict=verdict, confidence=confidence, explanation=explanation,
            evidence=evidence,
        )

    @staticmethod
    def _columns(conn: sqlite3.Connection) -> set[str]:
        try:
            return db.columns(conn, 'cases')
        except db.DatabaseError:
            return set()

    def _prior_inspections(self, conn: sqlite3.Connection, case: Any) -> list[dict[str, Any]]:
        """Underwriting cases on the same vehicle or policy, before this loss."""
        columns = self._columns(conn)
        clauses, params = [], []
        for field in FIELDS:
            if field not in columns:
                continue
            value = getattr(case, field, None)
            if value:
                clauses.append(f"{field} = ?")
                params.append(value)
        if not clauses:
            return []

        try:
            rows = conn.execute(
                f"SELECT case_id, declared_time, {', '.join(f for f in FIELDS if f in columns)} "
                f"FROM cases WHERE agent_type = 'underwriting' AND case_id != ? "
                f"AND ({' OR '.join(clauses)})",
                (case.case_id, *params),
            ).fetchall()
        except db.DatabaseError:
            return []

        out: list[dict[str, Any]] = []
        loss_time = self._as_datetime(case.declared_time)
        for row in rows:
            inspected = self._as_datetime(row[1])
            days = None
            if loss_time is not None and inspected is not None:
                days = (loss_time - inspected).days
            out.append({
                "case_id": row[0],
                "inspected_at": str(row[1]),
                "days_before_claim": days,
            })
        return sorted(out, key=lambda r: (r["days_before_claim"] is None,
                                          r["days_before_claim"]))

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

    @staticmethod
    def _claim_severity(ctx: CheckContext) -> Optional[str]:
        """Worst severity perception recorded across this claim's images."""
        order = {"none": 0, "minor": 1, "moderate": 2, "severe": 3}
        worst, worst_rank = None, -1
        for image in ctx.images:
            record = ctx.perception.get(image.content_hash)
            if record is None:
                continue
            severity = (getattr(record, "damage_severity", None) or "").strip().lower()
            if severity in order and order[severity] > worst_rank:
                worst, worst_rank = severity, order[severity]
        return worst


BASELINE_LINKAGE_CHECK = register_check(BaselineLinkageCheck())
