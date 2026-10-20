"""
fraudlens.agent.tools
=======================

The follow-up questions an agent can ask when the findings do not settle
a case.

These are deliberately *not* checks. A check runs on every case, costs
the same every time, and produces a Finding. A tool runs only when the
agent decides it needs an answer, and produces a fact. That difference is
the entire agentic claim under test in this project: if the agent never
calls a tool, it is an expensive way to read a list the baseline already
reads for free, and the ablation should say so.

So each tool answers a question a *finding* cannot:

    widen_similarity_search  the duplicate check found nothing at its
                             operating threshold - is there something just
                             below it?
    get_claimant_history     is this claimant's pattern of claims unusual,
                             or is this their first?
    get_garage_history       threshold_gaming describes a garage's billing
                             pattern; what is that pattern, concretely?
    requery_perception       the finding summarised one aspect of a photo;
                             what else did the vision pass record about it?

Two rules every tool here obeys:

1. **No API calls, ever.** requery_perception reads the cached
   PerceptionRecord written by src/perception.py. Vision quota is 20
   requests per key per day and is the scarcest resource in the project;
   an agent that could spend it mid-adjudication would make cost
   unpredictable and would let a single case exhaust a day's budget.
2. **Return facts, not judgements.** Every return value is a
   JSON-serialisable dict of observations. None of them says "this is
   suspicious" - forming that view is the agent's job, and a tool that
   editorialised would be smuggling a second, unmeasured detector into
   the pipeline.
"""

from __future__ import annotations

import sqlite3
from typing import Any, Callable, Optional

from .. import db, ingest
from ..models import Case

# Ceiling on rows returned by a history tool. A claimant with 400 claims
# is interesting, but pasting 400 rows into the prompt would crowd out the
# findings; the count is reported in full and the rows are truncated.
MAX_HISTORY_ROWS = 25

# Widened-search bounds. The duplicate check's own CONCERN floor is 0.90
# cosine; this tool exists to look *below* that, so it accepts anything
# from 0.70 upward and refuses to go under - beneath 0.70 CLIP similarity
# between two damaged-car photographs is essentially unrelated content and
# every case would return dozens of matches.
MIN_WIDEN_THRESHOLD = 0.70
MAX_WIDEN_MATCHES = 10


def widen_similarity_search(conn: sqlite3.Connection, case: Case, threshold: float = 0.80, evaluation_cutoff=None) -> dict[str, Any]:
    """
    Re-run the image similarity search at a lower threshold than the
    duplicate check uses.

    The check reports CONCERN only at cosine >= 0.90 with a perceptual-hash
    corroboration, which is deliberately strict - it is why that check has
    no unexplained false positives. This tool answers the different
    question "is there anything *nearly* similar", which is evidence a
    human might want and which the check correctly declines to raise on
    its own.
    """
    threshold = max(MIN_WIDEN_THRESHOLD, min(1.0, float(threshold)))
    images = db.get_images_for_case(conn, case.case_id)
    if not images:
        return {"tool": "widen_similarity_search", "threshold": threshold,
                "matches": [], "note": "this case has no images"}

    matches: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for image in images:
        if image.embedding is None:
            continue
        try:
            # find_similar takes the embedding itself and already excludes
            # the querying case; it returns (Image, cosine) pairs.
            similar = ingest.find_similar(
                conn, image.embedding, exclude_case=case.case_id, top_k=MAX_WIDEN_MATCHES,
                evaluation_cutoff=evaluation_cutoff
            )
        except Exception as e:  # noqa: BLE001 - a tool must never break the run
            from ..analysis_diagnostics import failure_detail
            return {"tool": "widen_similarity_search", "threshold": threshold,
                    "matches": [], "error": 'Similarity search could not complete.',
                    'diagnostic': failure_detail(e, 'agent_tool:widen_similarity_search')}
        for other, cosine in similar:
            if cosine < threshold:
                continue
            key = (image.image_id, other.case_id)
            if key in seen:
                continue
            seen.add(key)
            matches.append({
                "this_image_id": image.image_id,
                "matched_case_id": other.case_id,
                "matched_image_id": other.image_id,
                "cosine_similarity": round(float(cosine), 4),
            })

    matches.sort(key=lambda m: -m["cosine_similarity"])
    return {
        "tool": "widen_similarity_search",
        "threshold": threshold,
        "match_count": len(matches),
        "matches": matches[:MAX_WIDEN_MATCHES],
        "note": (
            "The internal_duplicate check reports a CONCERN only at cosine >= 0.90 with "
            "perceptual-hash corroboration. Matches listed here are BELOW that bar and are "
            "context, not evidence of reuse on their own."
        ),
    }


def get_claimant_history(conn: sqlite3.Connection, case: Case, evaluation_cutoff=None) -> dict[str, Any]:
    """Every other case filed by this claimant, with amounts and dates."""
    cutoff_sql, values = ingest.evaluation_cutoff_filter(conn, evaluation_cutoff)
    rows = conn.execute(
        "SELECT case_id, agent_type, claim_type, claim_amount, status, created_at "
        "FROM cases WHERE claimant_id = ?" + cutoff_sql + " ORDER BY created_at",
        (case.claimant_id, *values),
    ).fetchall()

    others = [dict(r) for r in rows if r["case_id"] != case.case_id]
    amounts = [r["claim_amount"] for r in others if r["claim_amount"] is not None]
    return {
        "tool": "get_claimant_history",
        "claimant_id": case.claimant_id,
        "other_case_count": len(others),
        "total_claimed_inr": round(sum(amounts), 2) if amounts else 0.0,
        "cases": [
            {k: (round(v, 2) if k == "claim_amount" and v is not None else v) for k, v in row.items()}
            for row in others[:MAX_HISTORY_ROWS]
        ],
        "truncated": len(others) > MAX_HISTORY_ROWS,
        "note": (
            "A single prior claim is unremarkable - most policyholders claim eventually. "
            "Read the pattern, not the count."
        ),
    }


def get_garage_history(conn: sqlite3.Connection, case: Case, evaluation_cutoff=None) -> dict[str, Any]:
    """
    This garage's claim distribution, including how much of it sits just
    under the 50,000 rupee independent-survey threshold.

    This is the concrete version of what threshold_gaming asserts. The
    check says "this garage's billing is skewed"; this says by how much,
    against what population baseline, so the agent can state the pattern
    in its narrative instead of repeating the check's sentence.
    """
    if not case.garage_id or case.garage_id == 'UNASSIGNED':
        return {"tool": "get_garage_history", "garage_id": None,
                "note": "this case has no garage attached"}

    cutoff_sql, values = ingest.evaluation_cutoff_filter(conn, evaluation_cutoff)
    rows = conn.execute(
        "SELECT claim_amount FROM cases WHERE garage_id = ? AND claim_amount IS NOT NULL" + cutoff_sql,
        (case.garage_id, *values),
    ).fetchall()
    amounts = [r["claim_amount"] for r in rows]

    population = conn.execute(
        "SELECT claim_amount FROM cases WHERE claim_amount IS NOT NULL" + cutoff_sql, values
    ).fetchall()
    population_amounts = [r["claim_amount"] for r in population]

    def band_share(values: list[float]) -> float:
        if not values:
            return 0.0
        return sum(1 for v in values if 45000.0 <= v < 50000.0) / len(values)

    return {
        "tool": "get_garage_history",
        "garage_id": case.garage_id,
        "claim_count": len(amounts),
        "mean_claim_inr": round(sum(amounts) / len(amounts), 2) if amounts else None,
        "share_in_45k_50k_band": round(band_share(amounts), 4),
        "population_share_in_band": round(band_share(population_amounts), 4),
        "note": (
            "The band is below a preserved INR 50,000 research benchmark, whose current legal "
            "applicability is unverified. A concentration describes the garage's recorded billing "
            "distribution; it establishes neither intent nor this claimant's conduct."
        ),
    }


def requery_perception(
    conn: sqlite3.Connection, case: Case, image_id: str, question: str = ""
) -> dict[str, Any]:
    """
    Return everything the cached vision pass recorded about one image.

    Makes NO API call - see the module docstring. `question` is accepted
    because the agent naturally phrases a follow-up as a question, and is
    echoed back so the trace records what it wanted to know; the full
    record is returned regardless, since filtering it here would just be
    guessing which field the agent meant.
    """
    image = None
    for candidate in db.get_images_for_case(conn, case.case_id):
        if candidate.image_id == image_id:
            image = candidate
            break
    if image is None:
        return {"tool": "requery_perception", "image_id": image_id,
                "error": "no such image on this case",
                "available_image_ids": [i.image_id for i in db.get_images_for_case(conn, case.case_id)]}

    record = db.get_perception_record(conn, image.content_hash)
    from ..perception import perception_record_usable
    if not perception_record_usable(record):
        return {
            "tool": "requery_perception", "image_id": image_id, "question": question,
            "perception_available": False,
            "note": (
                "No usable recorded vision observations are available for this image. "
                "Missing or failed perception is not evidence about the claim."
            ),
        }

    return {
        "tool": "requery_perception",
        "image_id": image_id,
        "question": question,
        "perception_available": True,
        'source_model': record.source,
        'schema_version': record.raw_response.get('schema_version', 'legacy_record'),
        "damage_description": record.damage_description,
        "damage_severity": record.damage_severity,
        "weather_observed": record.weather_observed,
        "road_condition": record.road_condition,
        "shadow_direction": record.shadow_direction,
        "shadow_length": record.shadow_length,
        "lighting": record.lighting,
        "plate_text": record.plate_text,
        "scene_context": record.scene_context,
        "anomaly_notes": record.anomaly_notes,
    }


# ---------------------------------------------------------------------------
# Gemini function-calling schemas
# ---------------------------------------------------------------------------
#
# Declared by hand rather than introspected from the signatures: the
# descriptions are the only thing the model sees when deciding whether a
# tool is worth calling, and they carry guidance ("use this when...") that
# no signature could express.

TOOL_SCHEMAS: list[dict[str, Any]] = [
    {
        "name": "widen_similarity_search",
        "description": (
            "Re-run image similarity at a lower threshold than the duplicate check uses. "
            "Call this when no duplicate was reported but you want to know whether a "
            "near-match exists just below the reporting bar."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "threshold": {
                    "type": "number",
                    "description": "Cosine similarity floor, 0.70 to 1.00. Default 0.80.",
                }
            },
            "required": [],
        },
    },
    {
        "name": "get_claimant_history",
        "description": (
            "List this claimant's other cases with amounts and dates. Call this when you "
            "need to know whether the claimant has a pattern of claims rather than a "
            "single event."
        ),
        "parameters": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "get_garage_history",
        "description": (
            "This garage's claim distribution and how much of it falls just under the "
            "50,000 rupee survey threshold, against the population baseline. Call this to "
            "state a threshold-gaming pattern concretely, or to check whether a garage is "
            "ordinary."
        ),
        "parameters": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "requery_perception",
        "description": (
            "Return everything the vision pass recorded about one image - damage, weather, "
            "shadows, lighting, plate text, anomalies. Reads a cache and makes no API call. "
            "Call this when a finding mentions one aspect of a photograph and you need the rest."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "image_id": {"type": "string", "description": "The image to look up."},
                "question": {"type": "string", "description": "What you want to know; recorded in the trace."},
            },
            "required": ["image_id"],
        },
    },
]

TOOLS: dict[str, Callable[..., dict[str, Any]]] = {
    "widen_similarity_search": widen_similarity_search,
    "get_claimant_history": get_claimant_history,
    "get_garage_history": get_garage_history,
    "requery_perception": requery_perception,
}


def schemas_for(tool_names: tuple[str, ...]) -> list[dict[str, Any]]:
    """
    The subset of TOOL_SCHEMAS a policy allows, wrapped as google-genai
    expects it.

    The wrapping is not decoration. GenerateContentConfig takes a list of
    *Tool* objects, each holding a `function_declarations` list - passing
    the bare declarations rejects with "tools.name: Extra inputs are not
    permitted", which surfaces as a provider error and sends every case
    to the DESK_REVIEW fallback. That failure is silent in the worst way:
    the pass completes, every decision is a valid AgentDecision, and the
    whole run quietly measures the fallback path instead of the agent.
    Caught on the first real adjudication; the offline suite could not
    have caught it, because FakeProvider never validates its arguments.

    TOOL_SCHEMAS stays flat - it is the readable declaration and what the
    tests assert against - and the transport shape is applied here, at
    the one point that talks to the SDK.
    """
    allowed = set(tool_names)
    declarations = [s for s in TOOL_SCHEMAS if s["name"] in allowed]
    return [{"function_declarations": declarations}] if declarations else []


def call_tool(
    name: str, conn: sqlite3.Connection, case: Case, args: Optional[dict[str, Any]] = None, *, evaluation_cutoff=None
) -> dict[str, Any]:
    """
    Dispatch one tool call, returning an error dict rather than raising.

    A tool that raises would abort an adjudication over a question the
    agent asked out of curiosity, so every failure comes back as data the
    agent can read and route around.
    """
    args = dict(args or {})
    if name in {'widen_similarity_search', 'get_claimant_history', 'get_garage_history'}:
        args['evaluation_cutoff'] = evaluation_cutoff  # Trusted run context overrides any model-supplied bound.
    fn = TOOLS.get(name)
    if fn is None:
        return {"tool": name, "error": "unknown tool", "available": sorted(TOOLS)}
    try:
        result = fn(conn, case, **args)
        if evaluation_cutoff is not None:
            result['evaluation_cutoff'] = str(evaluation_cutoff)
        return result
    except TypeError as e:
        return {"tool": name, "error": "Invalid tool arguments.", 'error_type': type(e).__name__}
    except Exception as e:  # noqa: BLE001
        from ..analysis_diagnostics import failure_detail
        return {"tool": name, "error": 'Tool execution failed.', 'diagnostic': failure_detail(e, 'agent_tool:' + name)}


def trace_observation(result):
    """Bounded observable facts, never hidden model thoughts/signatures."""
    keys = ('tool', 'threshold', 'match_count', 'other_case_count', 'total_claimed_inr',
            'claim_count', 'mean_claim_inr', 'share_in_45k_50k_band', 'population_share_in_band',
            'image_id', 'perception_available', 'damage_severity', 'weather_observed',
            'lighting', 'source_model', 'schema_version', 'error', 'diagnostic')
    observed = {key: result[key] for key in keys if key in result}
    for name in ('matches', 'cases'):
        if isinstance(result.get(name), list):
            observed[name] = result[name][:3]
            observed[name + '_truncated'] = len(result[name]) > 3
    return observed
