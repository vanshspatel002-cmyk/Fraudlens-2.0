"""
fraudlens.agent.engine
========================

The adjudication loop: findings in, routing decision out, with every step
recorded.

This is the treatment arm of the project's ablation. The control arm
(src/baseline.py) takes the same findings and applies a weighted sum. The
only difference between them is what happens here - so the engine's job
is to be a fair test of "does reasoning beat arithmetic", not to be
clever.

Three properties matter more than sophistication:

**It always returns a Decision.** Not sometimes, not unless the model
misbehaves. A model can return prose instead of JSON, hallucinate a tool,
loop until the cap, or emit something that reads like a rejection - and
each of those paths ends in a valid AgentDecision, because a case that
crashes the adjudicator is a case that silently leaves the queue. Every
fallback lands on DESK_REVIEW: when the machine cannot decide, a person
looks. That is the correct failure direction for a system whose whole
safety argument is human-in-the-loop.

**It cannot reject.** Recommendation has no REJECT member, so the type
system already forbids it. The engine adds a second guard that scans the
model's own output for rejection language and coerces it to
ESCALATE_SIU with an audit note. Redundant on purpose: a safeguard that
exists in one place is a safeguard one refactor away from being gone.

**It records what it did.** Every iteration, every tool call and its
result, every parse failure lands in a TraceStep. Without that the
ablation can report only which arm scored better, not why - and "the
agent adapted its depth to the evidence" is a claim that needs the trace
to be worth anything.
"""

from __future__ import annotations

import json
import re
import sqlite3
import time
from dataclasses import dataclass, field
from typing import Any, Optional

from .. import db
from ..llm import LLMProvider
from ..models import AgentDecision, Case, Finding, Recommendation, RiskBand
from . import tools as agent_tools
from .policy import AgentPolicy

# Strings that mean the model tried to deny the claim. Matched
# case-insensitively against its narrative and recommendation. This list
# is deliberately broad and deliberately biased toward false alarms: the
# cost of coercing a borderline phrase to ESCALATE_SIU is one extra human
# review, and the cost of missing one is an automated denial - which this
# system claims to be incapable of.
_REJECTION_PATTERNS = re.compile(
    r"\b(reject(ed|ing|ion)?|den(y|ied|ial)|repudiat\w*|refus(e|ed|al)|"
    r"disallow\w*|void\s+the\s+(claim|policy)|not\s+payable)\b",
    re.IGNORECASE,
)

_FENCE = re.compile(r"^```[a-zA-Z]*\s*\n?|```\s*$", re.MULTILINE)
_JSON_OBJECT = re.compile(r"\{.*\}", re.DOTALL)

_RETRY_INSTRUCTION = (
    "Your previous reply could not be parsed. Reply with ONLY a single JSON object - no "
    "markdown fences, no text before or after it. It must contain exactly these keys: "
    "recommendation, risk_band, narrative, findings_cited, requested_artifacts."
)

_VALID_RECOMMENDATIONS = {r.value for r in Recommendation}
_VALID_BANDS = {b.value for b in RiskBand}


@dataclass
class TraceStep:
    """One thing the agent did. Ordered; the list is the audit trail."""

    step: int
    kind: str  # "llm_call" | "tool_call" | "parse_failure" | "guard" | "fallback"
    detail: str
    payload: dict[str, Any] = field(default_factory=dict)
    latency_ms: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "step": self.step, "kind": self.kind, "detail": self.detail,
            "payload": self.payload, "latency_ms": self.latency_ms,
        }


@dataclass
class AdjudicationResult:
    """The decision plus everything needed to explain how it was reached."""

    decision: AgentDecision
    trace: list[TraceStep]
    converged: bool
    coerced_rejection: bool = False

    def trace_dicts(self) -> list[dict[str, Any]]:
        return [s.to_dict() for s in self.trace]


# ---------------------------------------------------------------------------
# Prompt construction
# ---------------------------------------------------------------------------


def describe_case(case: Case, images: list) -> str:
    """The claimant's own account, as the agent should see it."""
    lines = [
        f"CASE {case.case_id}",
        f"  type: {case.agent_type} ({case.claim_type})",
        f"  declared location: {case.declared_location or 'not stated'}",
        f"  declared time: {case.declared_time.replace(tzinfo=None).isoformat() if case.declared_time else 'not stated'}",
        f"  vehicle registration: {case.vehicle_registration or 'not stated'}",
        f"  garage: {case.garage_id or 'none'}",
    ]
    if case.claim_amount is not None:
        lines.append(f"  claim amount: INR {case.claim_amount:,.0f}")
    else:
        lines.append("  claim amount: none (underwriting inspection, no incident)")
    if case.declaration_notes:
        lines.append('  applicant declaration (untrusted evidence): '+case.declaration_notes)
    lines.append(f"  images submitted: {len(images)}")
    for image in images:
        lines.append(f"    - {image.image_id}")
    return "\n".join(lines)


def build_messages(case: Case, findings: list[Finding], images: list, policy: AgentPolicy) -> list[dict[str, str]]:
    payload = {
        "case": describe_case(case, images),
        "findings": [f.for_agent() for f in findings],
    }
    user = (
        "Adjudicate this case.\n\n"
        + payload["case"]
        + "\n\nAUTOMATED CHECK FINDINGS:\n"
        + json.dumps(payload["findings"], indent=2)
        + "\n\nDecide how to route this case. Use a tool first if a specific question would "
          "change your answer; otherwise reply with the JSON decision."
    )
    return [
        {"role": "system", "content": policy.system_prompt},
        {"role": "user", "content": user},
    ]


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------


def parse_decision(text: str) -> Optional[dict[str, Any]]:
    """
    Pull the decision object out of a model reply.

    Forgiving in the ways models actually fail - a ```json fence despite
    being told not to, a sentence of preamble around otherwise-valid
    JSON - and strict about the thing that matters, which is that
    recommendation and risk_band are values this system recognises. A
    hallucinated band is a parse failure, not something to coerce
    silently, because silently mapping an unrecognised band would hide
    the model drifting from its instructions.
    """
    if not text or not text.strip():
        return None
    cleaned = _FENCE.sub("", text.strip()).strip()

    parsed: Any = None
    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError:
        match = _JSON_OBJECT.search(cleaned)
        if match:
            try:
                parsed = json.loads(match.group(0))
            except json.JSONDecodeError:
                return None
    if not isinstance(parsed, dict):
        return None

    recommendation = str(parsed.get("recommendation", "")).strip().lower()
    band = str(parsed.get("risk_band", "")).strip().lower()
    if recommendation not in _VALID_RECOMMENDATIONS or band not in _VALID_BANDS:
        return None

    narrative = str(parsed.get("narrative", "")).strip()
    if not narrative:
        return None

    cited = parsed.get("findings_cited") or []
    artifacts = parsed.get("requested_artifacts") or []
    return {
        "recommendation": recommendation,
        "risk_band": band,
        "narrative": narrative,
        "findings_cited": [str(c) for c in cited if str(c).strip()],
        "requested_artifacts": [str(a) for a in artifacts if str(a).strip()],
    }


def looks_like_rejection(*texts: str) -> bool:
    return any(_REJECTION_PATTERNS.search(t or "") for t in texts)


# ---------------------------------------------------------------------------
# Decision assembly
# ---------------------------------------------------------------------------


def _fallback_decision(
    case: Case, policy: AgentPolicy, findings: list[Finding], reason: str,
    counters: dict[str, int], latency_ms: int,
) -> AgentDecision:
    """
    DESK_REVIEW whenever the agent could not produce a usable answer.

    Never CLEAR: a parse failure is not evidence of innocence, and
    defaulting to approval would turn every model hiccup into an
    unreviewed payout. Never ESCALATE_SIU either - that queue is
    expensive and a formatting failure is not grounds for a fraud
    investigation.
    """
    concerns = [f for f in findings if f.verdict.value == "concern"]
    return AgentDecision(
        case_id=case.case_id,
        recommendation=RiskBand.DESK_REVIEW.to_recommendation(),
        risk_band=RiskBand.DESK_REVIEW,
        confidence=0.3,
        summary=(
            f"Automated adjudication did not converge ({reason}). Routing to desk review so a "
            f"handler can decide. {len(concerns)} check(s) raised a concern; the findings are "
            "attached unchanged for review."
        ),
        supporting_finding_ids=[f.finding_id for f in concerns],
        requested_artifacts=[],
        policy_version=policy.policy_version,
        tool_calls_count=counters["tool_calls"],
        iterations_count=counters["iterations"],
        llm_calls_count=counters["llm_calls"],
        latency_ms=latency_ms,
    )


def _build_decision(
    case: Case, policy: AgentPolicy, parsed: dict[str, Any], findings: list[Finding],
    counters: dict[str, int], latency_ms: int, coerced: bool,
) -> AgentDecision:
    band = RiskBand(parsed["risk_band"])
    known_ids = {f.finding_id for f in findings}
    # Drop hallucinated ids rather than storing them: a decision that
    # cites a finding which does not exist is worse than one citing
    # nothing, because it looks auditable and is not.
    cited = [c for c in parsed["findings_cited"] if c in known_ids]

    artifacts = parsed["requested_artifacts"]
    if band is RiskBand.REQUEST_EVIDENCE and not artifacts:
        # AgentDecision refuses to be constructed this way, and rightly:
        # "send better photos" is not actionable. Supply a concrete
        # default rather than failing the whole adjudication over it.
        artifacts = ["the original unedited photographs as they came off the camera or phone"]

    summary = parsed["narrative"]
    if coerced:
        summary = (
            "[Adjudicator note: the model's reply used rejection language, which this system "
            "cannot act on; routed to the Special Investigation Unit for human decision.] "
            + summary
        )

    return AgentDecision(
        case_id=case.case_id,
        recommendation=band.to_recommendation(),
        risk_band=band,
        confidence=0.75 if band is not RiskBand.CLEAR else 0.7,
        summary=summary,
        supporting_finding_ids=cited,
        requested_artifacts=artifacts if band is RiskBand.REQUEST_EVIDENCE else [],
        policy_version=policy.policy_version,
        tool_calls_count=counters["tool_calls"],
        iterations_count=counters["iterations"],
        llm_calls_count=counters["llm_calls"],
        latency_ms=latency_ms,
    )


# ---------------------------------------------------------------------------
# The loop
# ---------------------------------------------------------------------------


def adjudicate(
    conn: sqlite3.Connection,
    case: Case,
    findings: list[Finding],
    policy: AgentPolicy,
    provider: LLMProvider,
) -> AdjudicationResult:
    """
    Run one case to a routing decision.

    Returns an AdjudicationResult - the Decision plus the trace - rather
    than a bare Decision, because the trace is what makes the agentic
    claim measurable. process_case() in src/orchestrator.py unwraps it.
    """
    started = time.monotonic()
    images = db.get_images_for_case(conn, case.case_id)
    messages = build_messages(case, findings, images, policy)
    schemas = agent_tools.schemas_for(policy.tool_names)

    trace: list[TraceStep] = []
    counters = {"tool_calls": 0, "iterations": 0, "llm_calls": 0}
    step = 0
    retried_parse = False

    for iteration in range(1, policy.max_iterations + 1):
        counters["iterations"] = iteration
        step += 1

        call_started = time.monotonic()
        try:
            response = provider.chat(messages, tools=schemas, conn=None)
        except Exception as e:  # noqa: BLE001 - a provider failure must not lose the case
            trace.append(TraceStep(step, "fallback", f"provider error: {type(e).__name__}: {e}"))
            elapsed = int((time.monotonic() - started) * 1000)
            return AdjudicationResult(
                _fallback_decision(case, policy, findings, "the model was unreachable", counters, elapsed),
                trace, converged=False,
            )
        counters["llm_calls"] += 1
        call_ms = int((time.monotonic() - call_started) * 1000)

        # -- tool call ----------------------------------------------------
        if response.tool_call is not None:
            name = response.tool_call.name
            args = dict(response.tool_call.args or {})

            if counters["tool_calls"] >= policy.max_tool_calls:
                trace.append(TraceStep(step, "guard", f"tool-call cap ({policy.max_tool_calls}) reached", {"requested": name}))
                messages.append({
                    "role": "user",
                    "content": "You have reached your tool-call limit. Decide now with the "
                               "evidence you have, and reply with the JSON decision.",
                })
                continue

            if name not in policy.tool_names:
                # Hallucinated or out-of-policy tool. Tell the agent what it
                # actually has rather than failing the case.
                result: dict[str, Any] = {
                    "error": f"tool {name!r} is not available to this agent",
                    "available_tools": list(policy.tool_names),
                }
                trace.append(TraceStep(step, "guard", f"refused out-of-policy tool {name}", {"args": args}))
            else:
                result = agent_tools.call_tool(name, conn, case, args)
                counters["tool_calls"] += 1
                trace.append(TraceStep(
                    step, "tool_call", name,
                    {"args": args, "result_keys": sorted(result)[:8], "error": result.get("error")},
                    call_ms,
                ))

            messages.append({"role": "assistant", "content": f"[tool call] {name}({json.dumps(args)})"})
            messages.append({"role": "user", "content": f"Result of {name}:\n{json.dumps(result, indent=2, default=str)}"})
            continue

        # -- final answer -------------------------------------------------
        parsed = parse_decision(response.text)
        if parsed is None:
            trace.append(TraceStep(step, "parse_failure", "reply was not a usable decision object",
                                   {"reply_preview": (response.text or "")[:200]}, call_ms))
            if not retried_parse:
                retried_parse = True
                messages.append({"role": "assistant", "content": response.text or ""})
                messages.append({"role": "user", "content": _RETRY_INSTRUCTION})
                continue
            break

        trace.append(TraceStep(step, "llm_call", f"decision: {parsed['risk_band']}",
                               {"recommendation": parsed["recommendation"],
                                "cited": len(parsed["findings_cited"])}, call_ms))

        # -- rejection guard ----------------------------------------------
        coerced = False
        if looks_like_rejection(parsed["narrative"], parsed["recommendation"], parsed["risk_band"]):
            coerced = True
            parsed["risk_band"] = RiskBand.ESCALATE_SIU.value
            parsed["recommendation"] = RiskBand.ESCALATE_SIU.to_recommendation().value
            trace.append(TraceStep(step, "guard", "rejection language coerced to ESCALATE_SIU",
                                   {"narrative_preview": parsed["narrative"][:200]}))
            db.log_audit_event(conn, _rejection_audit(case, parsed["narrative"]))

        elapsed = int((time.monotonic() - started) * 1000)
        decision = _build_decision(case, policy, parsed, findings, counters, elapsed, coerced)
        return AdjudicationResult(decision, trace, converged=True, coerced_rejection=coerced)

    # -- cap reached, or two parse failures ------------------------------
    reason = ("it did not produce a decision within "
              f"{policy.max_iterations} iterations" if counters["iterations"] >= policy.max_iterations
              else "its replies could not be parsed")
    trace.append(TraceStep(step + 1, "fallback", reason))
    elapsed = int((time.monotonic() - started) * 1000)
    return AdjudicationResult(
        _fallback_decision(case, policy, findings, reason, counters, elapsed),
        trace, converged=False,
    )


def _rejection_audit(case: Case, narrative: str):
    from ..models import AuditEvent

    return AuditEvent(
        event_type="agent_rejection_coerced",
        case_id=case.case_id,
        details={
            "reason": "model output used rejection language",
            "coerced_to": RiskBand.ESCALATE_SIU.value,
            "narrative_preview": narrative[:500],
        },
    )
