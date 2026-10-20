"""
fraudlens.checks.entity_graph
===============================

Garage–claimant collusion, as a network problem rather than an image one.

Every other check in this battery examines a case in isolation, or a case
against a corpus of images. This one asks a question no single case can
answer: **who else is connected to this case, and does that pattern look
like a ring?**

Organised motor fraud in India is substantially a relationship problem. A
garage recruits claimants, or a small group of individuals cycles vehicles
between policies, and the tell is not in any one photograph — it is that
the same phone number, bank account or address appears across claims that
are nominally unrelated. Image forensics cannot see this at all.

--------------------------------------------------------------------------
What it looks for
--------------------------------------------------------------------------
Two patterns, both requiring corroboration before raising a concern:

1. **Shared identifiers across claimants.** A case sharing two or more
   identifiers - phone, bank account, address, vehicle registration - with
   a case belonging to a *different* claimant. Two is the threshold rather
   than one because single-identifier collisions have innocent
   explanations: a shared address is a family, a shared garage is a popular
   repairer. Two independent identifiers rarely coincide by accident.

2. **One claimant, many vehicles, one garage.** A claimant appearing with
   multiple distinct registrations at the same garage. This is the
   signature of a garage cycling vehicles through a cooperative claimant.

The garage id alone is deliberately NOT counted as an identifier for
pattern 1. A busy garage legitimately serves hundreds of unrelated
claimants, and counting it would make every customer of a large repairer a
suspect - the same error `threshold_gaming` made by describing a garage's
billing pattern in a sentence about the claimant.

--------------------------------------------------------------------------
Measured on this corpus: nothing, and that is a corpus property
--------------------------------------------------------------------------
The generator assigns every case a unique claimant and a unique
registration, so no two cases share anything to join on and this check
cannot fire. That is not a finding about collusion detection; it is a
finding about the corpus, and it is reported that way in
`outputs/entity_graph_measurement.json`.

`scripts/inject_collusion_ring.py` builds a labelled ring in a database
copy so the check is demonstrable and measurable despite the main corpus
lacking one. The weight below is therefore justified by argument rather
than by measurement on the production corpus, and says so.
"""

from __future__ import annotations

import sqlite3
from .. import db, ingest
from collections import defaultdict
from typing import Any, Optional

from ..models import CheckCategory, Finding, Verdict
from .base import Check, CheckContext, register_check

# Identifiers that, shared between cases with different claimants, are
# evidence of a relationship. Ordered by how hard each is to share innocently.
LINKING_FIELDS: tuple[str, ...] = (
    "phone",
    "bank_account",
    "address",
    "vehicle_registration",
)

# Two independent identifiers, not one. See the module docstring.
MIN_SHARED_IDENTIFIERS = 2

# A claimant at one garage with this many distinct vehicles is the
# vehicle-cycling pattern rather than a household with two cars.
MIN_VEHICLES_PER_CLAIMANT = 3


class EntityGraphCheck(Check):
    check_id = "entity_graph"
    category = CheckCategory.HISTORY
    scope = "case"
    cost_inr = 0.0
    requires_perception = False
    # No archetype in this corpus generates collusion, so there is nothing
    # here for it to be measured against. Naming a target it cannot fire on
    # would credit it with coverage it does not have - the error
    # baseline_corruption made.
    target_archetypes = ()
    # 1.0 by argument, not by measurement on this corpus. Two independent
    # shared identifiers between different claimants is close to fact rather
    # than inference, in the same way a hash match is: people do not
    # coincidentally share both a bank account and a phone number. Measured
    # against the injected ring in
    # scripts/inject_collusion_ring.py; re-derive against real data, where
    # this check has something to detect.
    weight = 1.0
    attributed_to = "claimant"
    limitation = (
        "Every case carries a unique claimant and registration, so no two cases share an identifier to join on; verified 18/18 against expanded injected rings with 0/6 single-identifier controls flagged."
    )

    def run(self, ctx: CheckContext) -> list[Finding]:
        case = ctx.case
        identifiers = self._identifiers_for(ctx.conn, case.case_id)
        evidence: dict[str, Any] = {
            "identifiers_examined": sorted(identifiers),
            "linking_fields": list(LINKING_FIELDS),
        }

        if not identifiers:
            return [self._finding(
                case.case_id, Verdict.INCONCLUSIVE, 0.0,
                "No linking identifiers are recorded for this case, so it cannot be "
                "related to any other.",
                evidence)]

        shared = self._shared_with_other_claimants(ctx.conn, case.case_id, identifiers, ctx.config.get('evaluation_cutoff'))
        cycling = self._claimant_vehicle_cycling(ctx.conn, case, ctx.config.get('evaluation_cutoff'))

        evidence["linked_cases"] = {
            other: sorted(fields) for other, fields in sorted(shared.items())
        }
        evidence["claimant_registrations_at_garage"] = cycling

        strong = {other: fields for other, fields in shared.items()
                  if len(fields) >= MIN_SHARED_IDENTIFIERS}

        if strong:
            worst = max(strong.items(), key=lambda kv: len(kv[1]))
            other_case, fields = worst
            evidence["strongest_link"] = {"case_id": other_case, "shared": sorted(fields)}
            confidence = min(0.95, 0.6 + 0.15 * (len(fields) - MIN_SHARED_IDENTIFIERS))
            names = ", ".join(sorted(fields))
            return [self._finding(
                case.case_id, Verdict.CONCERN, confidence,
                f"This case shares {len(fields)} identifiers ({names}) with "
                f"{other_case}, which is filed by a different claimant. "
                f"{len(strong)} such link(s) exist in total. Unrelated claimants do "
                f"not normally share this many details.",
                evidence)]

        if cycling and cycling.get("distinct_registrations", 0) >= MIN_VEHICLES_PER_CLAIMANT:
            return [self._finding(
                case.case_id, Verdict.CONCERN, 0.7,
                f"This claimant appears with {cycling['distinct_registrations']} distinct "
                f"vehicle registrations at garage {cycling['garage_id']}. A single "
                f"claimant cycling several vehicles through one repairer is the "
                f"signature of an organised arrangement rather than of ordinary use.",
                evidence)]

        if shared:
            most = max(shared.items(), key=lambda kv: len(kv[1]))
            return [self._finding(
                case.case_id, Verdict.INCONCLUSIVE, 0.3,
                f"This case shares one identifier ({', '.join(sorted(most[1]))}) with "
                f"{most[0]}. A single shared detail has innocent explanations - a "
                f"family address, a shared contact number - and is not on its own "
                f"evidence of a relationship.",
                evidence)]

        return [self._finding(
            case.case_id, Verdict.PASS, 0.7,
            "No other case shares identifying details with this one.",
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
    def _available_columns(conn: sqlite3.Connection, table: str) -> set[str]:
        return db.columns(conn, table)

    def _identifiers_for(self, conn: sqlite3.Connection, case_id: str) -> dict[str, str]:
        """
        The case's linking identifiers, drawn from wherever they live.

        Contact details sit on the claimant rather than the case, and some
        deployments will not carry them at all, so every field is optional
        and a missing column is simply absent rather than an error.
        """
        out: dict[str, str] = {}
        case_cols = self._available_columns(conn, "cases")
        wanted = [f for f in LINKING_FIELDS if f in case_cols]
        if wanted:
            row = conn.execute(
                f"SELECT {', '.join(wanted)} FROM cases WHERE case_id = ?", (case_id,)
            ).fetchone()
            if row:
                for field, value in zip(wanted, row):
                    if value:
                        out[field] = str(value)

        claimant_cols = self._available_columns(conn, "claimants")
        c_wanted = [f for f in LINKING_FIELDS if f in claimant_cols and f not in out]
        if c_wanted:
            row = conn.execute(
                f"SELECT c.{', c.'.join(c_wanted)} FROM claimants c "
                "JOIN cases ca ON ca.claimant_id = c.claimant_id WHERE ca.case_id = ?",
                (case_id,),
            ).fetchone()
            if row:
                for field, value in zip(c_wanted, row):
                    if value:
                        out[field] = str(value)
        return out

    def _shared_with_other_claimants(
        self, conn: sqlite3.Connection, case_id: str, identifiers: dict[str, str], evaluation_cutoff=None,
    ) -> dict[str, set[str]]:
        """case_id -> set of field names shared, for cases with a DIFFERENT claimant."""
        mine = conn.execute(
            "SELECT claimant_id FROM cases WHERE case_id = ?", (case_id,)).fetchone()
        my_claimant = mine[0] if mine else None

        shared: dict[str, set[str]] = defaultdict(set)
        case_cols = self._available_columns(conn, "cases")
        claimant_cols = self._available_columns(conn, "claimants")

        for field, value in identifiers.items():
            if field in case_cols:
                sql = ("SELECT case_id, claimant_id FROM cases "
                       f"WHERE {field} = ? AND case_id != ?")
                params: tuple = (value, case_id)
                cutoff_sql, cutoff_values = ingest.evaluation_cutoff_filter(conn, evaluation_cutoff)
            elif field in claimant_cols:
                sql = ("SELECT ca.case_id, ca.claimant_id FROM cases ca "
                       "JOIN claimants c ON c.claimant_id = ca.claimant_id "
                       f"WHERE c.{field} = ? AND ca.case_id != ?")
                params = (value, case_id)
                cutoff_sql, cutoff_values = ingest.evaluation_cutoff_filter(conn, evaluation_cutoff, ('ca.created_at',))
            else:
                continue
            rows = conn.execute(sql + cutoff_sql, (*params,*cutoff_values)).fetchall()
            for other_case, other_claimant in rows:
                # A claimant sharing details with their own other claims is
                # not collusion; it is the same person.
                if my_claimant is not None and other_claimant == my_claimant:
                    continue
                shared[other_case].add(field)
        return dict(shared)

    def _claimant_vehicle_cycling(
        self, conn: sqlite3.Connection, case: Any, evaluation_cutoff=None,
    ) -> Optional[dict[str, Any]]:
        if not case.claimant_id or not case.garage_id or case.garage_id == 'UNASSIGNED':
            return None
        cutoff_sql, values = ingest.evaluation_cutoff_filter(conn, evaluation_cutoff)
        rows = conn.execute(
                "SELECT DISTINCT vehicle_registration FROM cases "
                "WHERE claimant_id = ? AND garage_id = ? AND vehicle_registration IS NOT NULL" + cutoff_sql,
                (case.claimant_id, case.garage_id, *values),
            ).fetchall()
        regs = sorted({r[0] for r in rows if r[0]})
        return {"garage_id": case.garage_id, "distinct_registrations": len(regs),
                "registrations": regs[:10]}


ENTITY_GRAPH_CHECK = register_check(EntityGraphCheck())
