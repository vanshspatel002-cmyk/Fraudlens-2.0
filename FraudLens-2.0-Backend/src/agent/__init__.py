"""
fraudlens.agent
=================

The agentic layer - the treatment arm of this project's ablation.

Three modules, deliberately separated:

    policy.py   what an agent may do and what it has been told about the
                evidence. Data, not code, so the difference between the
                claims and underwriting agents is auditable by reading a
                dataclass.
    tools.py    the follow-up questions an agent can ask when the
                findings do not settle a case. Never calls an API.
    engine.py   the loop. Always returns a Decision, can never reject,
                and records every step it took.
"""

from __future__ import annotations

from .engine import AdjudicationResult, TraceStep, adjudicate, parse_decision
from .policy import CLAIMS_POLICY, UNDERWRITING_POLICY, AgentPolicy, policy_for
from .tools import TOOL_SCHEMAS, TOOLS, call_tool, schemas_for

__all__ = [
    "AdjudicationResult", "TraceStep", "adjudicate", "parse_decision",
    "AgentPolicy", "CLAIMS_POLICY", "UNDERWRITING_POLICY", "policy_for",
    "TOOLS", "TOOL_SCHEMAS", "call_tool", "schemas_for",
]
