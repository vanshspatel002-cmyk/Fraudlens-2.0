"""
Test suite for the agentic layer.

Entirely offline. Every test drives a FakeProvider with canned replies -
no API key is read, no request is made, and the suite runs identically
whether or not the free tier has quota left today. That is deliberate:
the behaviours under test here are the ones that must hold when the model
misbehaves, and a suite that needs a working model to check "what happens
when the model returns garbage" would be testing the wrong thing.

What is asserted, in rough order of how much it would cost to get wrong:

  - a rejection attempt is coerced to escalation (the safety claim)
  - the loop always terminates with a Decision, including at the cap
  - malformed JSON is retried once, then falls back to DESK_REVIEW
  - tool calls execute and their results feed back into the conversation
  - the trace records every step
  - the two policies load with genuinely different check sets

Run with:
    python test_agent.py
"""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
import traceback
from pathlib import Path
from typing import Any, Optional

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

sys.path.insert(0, str(Path(__file__).resolve().parent))

from src import db
from src.agent.engine import TraceStep, adjudicate, looks_like_rejection, parse_decision
from src.agent.policy import CLAIMS_POLICY, UNDERWRITING_POLICY, policy_for
from src.llm import LLMResponse, ToolCall
from src.models import Case, CheckCategory, Finding, Recommendation, RiskBand, Verdict

_TESTS: list = []


def test(fn):
    _TESTS.append(fn)
    return fn


def run_all() -> bool:
    passed, failed = 0, 0
    failures = []
    for fn in _TESTS:
        print(f"--- {fn.__name__} ---")
        try:
            fn()
            passed += 1
            print(f"PASS  {fn.__name__}")
        except Exception as e:  # noqa: BLE001
            failed += 1
            failures.append((fn.__name__, traceback.format_exc()))
            print(f"FAIL  {fn.__name__}  ->  {type(e).__name__}: {e}")
    for name, tb in failures:
        print(f"\nFAIL  {name}\n{tb}")
    print(f"\n{passed} passed, {failed} failed")
    return failed == 0


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class FakeProvider:
    """
    Replays a scripted list of replies. Never touches the network.

    Each entry is either a string (returned as the model's text) or a
    (tool_name, args) tuple (returned as a tool call). Running past the
    end of the script repeats the last entry, which is what lets the
    max-iterations test drive the loop to its cap with a single
    tool-calling reply.
    """

    model = "fake-model"

    def __init__(self, script: list[Any]) -> None:
        self.script = list(script)
        self.calls: list[list[dict]] = []

    def chat(self, messages, tools=None, conn=None) -> LLMResponse:
        self.calls.append(list(messages))
        index = min(len(self.calls) - 1, len(self.script) - 1)
        entry = self.script[index]
        if isinstance(entry, tuple):
            name, args = entry
            return LLMResponse(text="", tool_call=ToolCall(name=name, args=args),
                               raw={}, model=self.model, cached=False, latency_ms=1)
        return LLMResponse(text=str(entry), tool_call=None, raw={},
                           model=self.model, cached=False, latency_ms=1)

    def describe_image(self, image_path, prompt, conn=None, retry_attempts=1):
        raise AssertionError("the agent must never call the vision API")


def decision_json(band="clear", recommendation="approve", narrative="Nothing of concern.",
                  cited=None, artifacts=None) -> str:
    return json.dumps({
        "recommendation": recommendation,
        "risk_band": band,
        "narrative": narrative,
        "findings_cited": cited or [],
        "requested_artifacts": artifacts or [],
    })


_conn = None
_tmpdir = None


def get_conn():
    """
    A private copy of the corpus database.

    This suite writes: `adjudicate` logs an audit event whenever it coerces a
    rejection, so pointing it at fraudlens.db made the tests contend with any
    long-running batch job for a write lock. That surfaced as
    `OperationalError: database is locked` on
    test_rejection_attempt_is_coerced_to_escalation while the check battery was
    regenerating - a failure that says nothing about the code under test and
    everything about two processes sharing a file.

    Copying costs a second and buys a suite that passes regardless of what else
    is running. The copy is made once per process and removed at exit.
    """
    global _conn, _tmpdir
    if _conn is None:
        _tmpdir = tempfile.mkdtemp(prefix="fraudlens_agent_test_")
        copy = Path(_tmpdir) / "corpus.db"
        import sqlite3
        source=sqlite3.connect(Path('fraudlens.db').resolve().as_uri()+'?mode=ro',uri=True)
        target=sqlite3.connect(copy)
        try:source.backup(target)
        finally:source.close();target.close()
        _conn = db.connect(copy)
        db.init_db(_conn)
    return _conn


def cleanup_conn() -> None:
    global _conn, _tmpdir
    if _conn is not None:
        _conn.close()
        _conn = None
    if _tmpdir:
        shutil.rmtree(_tmpdir, ignore_errors=True)
        _tmpdir = None


def a_case(agent_type: str = "claims") -> Case:
    """A real case from the corpus, so tools have something to read."""
    for case in db.get_all_cases(get_conn()):
        if case.agent_type == agent_type:
            return case
    raise AssertionError(f"no {agent_type} case in the corpus")


def a_finding(case: Case, verdict=Verdict.CONCERN) -> Finding:
    return Finding(
        check_id="internal_duplicate", case_id=case.case_id, category=CheckCategory.HISTORY,
        verdict=verdict, confidence=0.9,
        explanation="This image matches an image submitted in another case.",
    )


# ---------------------------------------------------------------------------
# The safety claim
# ---------------------------------------------------------------------------


@test
def test_rejection_attempt_is_coerced_to_escalation():
    """
    The single most important test in this file.

    The system's safety argument is that it cannot deny a claim. The type
    system enforces that (Recommendation has no REJECT), but a model can
    still *try* - by writing a narrative that denies the claim while
    picking a permitted enum value. That output would be acted on by a
    human reading the narrative, so the engine has to catch the intent,
    not just the field.
    """
    case = a_case("claims")
    findings = [a_finding(case)]
    provider = FakeProvider([decision_json(
        band="desk_review", recommendation="escalate",
        narrative="This claim is fraudulent and should be rejected outright; the policy is void.",
    )])

    result = adjudicate(get_conn(), case, findings, CLAIMS_POLICY, provider)
    assert result.coerced_rejection, "rejection language must be detected"
    assert result.decision.risk_band is RiskBand.ESCALATE_SIU, result.decision.risk_band
    assert result.decision.recommendation is Recommendation.ESCALATE
    assert "Adjudicator note" in result.decision.summary
    assert any(s.kind == "guard" for s in result.trace), "the coercion must appear in the trace"
    print(f"  coerced to {result.decision.risk_band.value}, note prepended, guard traced")


@test
def test_rejection_detector_covers_the_obvious_phrasings():
    assert looks_like_rejection("we should reject this claim")
    assert looks_like_rejection("the claim is denied")
    assert looks_like_rejection("recommend repudiation of the policy")
    assert looks_like_rejection("this is not payable")
    assert looks_like_rejection("refuse the application")
    # Must not fire on ordinary escalation language, or every genuine
    # escalation would be coerced and the band would carry no information.
    assert not looks_like_rejection("escalate to the Special Investigation Unit for review")
    assert not looks_like_rejection("request the original photographs from the claimant")
    print("  fires on reject/deny/repudiate/refuse/not payable; silent on normal escalation")


# ---------------------------------------------------------------------------
# Loop behaviour
# ---------------------------------------------------------------------------


@test
def test_loop_terminates_on_a_final_answer():
    case = a_case("claims")
    findings = [a_finding(case, Verdict.PASS)]
    provider = FakeProvider([decision_json(band="clear", recommendation="approve",
                                           cited=[findings[0].finding_id])])

    result = adjudicate(get_conn(), case, findings, CLAIMS_POLICY, provider)
    assert result.converged
    assert result.decision.risk_band is RiskBand.CLEAR
    assert result.decision.iterations_count == 1, result.decision.iterations_count
    assert result.decision.llm_calls_count == 1
    assert result.decision.tool_calls_count == 0
    assert result.decision.supporting_finding_ids == [findings[0].finding_id]
    assert result.decision.latency_ms >= 0
    print(f"  1 iteration, 1 llm call, 0 tools -> {result.decision.risk_band.value}")


@test
def test_tool_call_executes_and_feeds_back():
    case = a_case("claims")
    findings = [a_finding(case)]
    provider = FakeProvider([
        ("get_claimant_history", {}),
        decision_json(band="desk_review", recommendation="escalate",
                      narrative="Claimant has prior claims; a handler should review."),
    ])

    result = adjudicate(get_conn(), case, findings, CLAIMS_POLICY, provider)
    assert result.converged
    assert result.decision.tool_calls_count == 1, result.decision.tool_calls_count
    assert result.decision.iterations_count == 2

    tool_steps = [s for s in result.trace if s.kind == "tool_call"]
    assert len(tool_steps) == 1 and tool_steps[0].detail == "get_claimant_history"

    # The result must actually reach the model, not just be recorded.
    final_messages = provider.calls[-1]
    assert any("get_claimant_history" in m["content"] for m in final_messages), \
        "the tool result must be appended to the conversation"
    print(f"  tool executed, result fed back, {len(provider.calls)} model calls")


@test
def test_out_of_policy_tool_is_refused_without_failing_the_case():
    """
    Underwriting has no garage tool. A model that asks for one anyway
    must be told what it actually has, not crash the adjudication.
    """
    case = a_case("underwriting")
    findings = [a_finding(case)]
    provider = FakeProvider([
        ("get_garage_history", {}),
        decision_json(band="request_evidence", recommendation="request_evidence",
                      narrative="Need a clearer photograph of the rear panel.",
                      artifacts=["a close-up photograph of the rear bumper"]),
    ])

    result = adjudicate(get_conn(), case, findings, UNDERWRITING_POLICY, provider)
    assert result.converged
    assert result.decision.tool_calls_count == 0, "an out-of-policy tool must not count as a call"
    guards = [s for s in result.trace if s.kind == "guard"]
    assert guards and "out-of-policy" in guards[0].detail
    assert result.decision.requested_artifacts, "REQUEST_EVIDENCE must name an artifact"
    print(f"  refused get_garage_history, agent recovered -> {result.decision.risk_band.value}")


@test
def test_iteration_cap_falls_back_to_desk_review():
    """
    A model that only ever calls tools must still yield a decision. The
    fallback is DESK_REVIEW - never CLEAR, because failing to decide is
    not evidence of innocence, and never ESCALATE_SIU, because a loop is
    not grounds for a fraud investigation.
    """
    case = a_case("claims")
    findings = [a_finding(case)]
    # The script's last entry repeats forever, so this never answers.
    provider = FakeProvider([("get_claimant_history", {})])

    result = adjudicate(get_conn(), case, findings, CLAIMS_POLICY, provider)
    assert not result.converged
    assert result.decision.risk_band is RiskBand.DESK_REVIEW, result.decision.risk_band
    assert result.decision.iterations_count == CLAIMS_POLICY.max_iterations
    assert "did not converge" in result.decision.summary
    assert any(s.kind == "fallback" for s in result.trace)
    print(f"  hit {CLAIMS_POLICY.max_iterations}-iteration cap -> desk_review, no crash")


@test
def test_tool_call_cap_is_enforced():
    case = a_case("claims")
    findings = [a_finding(case)]
    tight = type(CLAIMS_POLICY)(
        agent_type="claims", check_ids=CLAIMS_POLICY.check_ids, tool_names=CLAIMS_POLICY.tool_names,
        system_prompt=CLAIMS_POLICY.system_prompt, policy_version="test-tight",
        max_iterations=6, max_tool_calls=2, escalation_bias="escalate",
    )
    provider = FakeProvider([("get_claimant_history", {})])

    result = adjudicate(get_conn(), case, findings, tight, provider)
    assert result.decision.tool_calls_count <= 2, result.decision.tool_calls_count
    assert any(s.kind == "guard" and "cap" in s.detail for s in result.trace)
    print(f"  stopped at {result.decision.tool_calls_count} tool calls, cap honoured")


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------


@test
def test_malformed_json_is_retried_once_then_falls_back():
    case = a_case("claims")
    findings = [a_finding(case)]
    provider = FakeProvider(["I think this claim is probably fine, honestly."])

    result = adjudicate(get_conn(), case, findings, CLAIMS_POLICY, provider)
    assert not result.converged
    assert result.decision.risk_band is RiskBand.DESK_REVIEW
    parse_failures = [s for s in result.trace if s.kind == "parse_failure"]
    assert len(parse_failures) == 2, f"expected one retry then give up, got {len(parse_failures)}"
    print(f"  2 parse failures (one retry) -> {result.decision.risk_band.value}")


@test
def test_malformed_then_valid_recovers():
    case = a_case("claims")
    findings = [a_finding(case)]
    provider = FakeProvider(["not json at all", decision_json(band="clear", recommendation="approve")])

    result = adjudicate(get_conn(), case, findings, CLAIMS_POLICY, provider)
    assert result.converged, "a corrected second reply must be accepted"
    assert result.decision.risk_band is RiskBand.CLEAR
    print("  recovered on the retry")


@test
def test_parse_decision_handles_fences_and_rejects_nonsense():
    fenced = "```json\n" + decision_json(band="clear", recommendation="approve") + "\n```"
    assert parse_decision(fenced) is not None, "fenced JSON must parse"

    wrapped = "Here is my decision:\n" + decision_json(band="clear", recommendation="approve") + "\nHope that helps."
    assert parse_decision(wrapped) is not None, "JSON with prose around it must parse"

    # A band this system does not have is a parse failure, not something
    # to coerce silently - silent coercion would hide the model drifting.
    assert parse_decision(json.dumps({
        "recommendation": "approve", "risk_band": "definitely_fine",
        "narrative": "x", "findings_cited": [], "requested_artifacts": [],
    })) is None
    assert parse_decision(json.dumps({
        "recommendation": "reject", "risk_band": "clear",
        "narrative": "x", "findings_cited": [], "requested_artifacts": [],
    })) is None, "an invalid recommendation must not parse"
    assert parse_decision("") is None
    assert parse_decision("{}") is None
    print("  fences and prose tolerated; unknown bands and empty replies rejected")


@test
def test_hallucinated_finding_ids_are_dropped():
    """
    A decision citing a finding that does not exist looks auditable and
    is not, which is worse than citing nothing.
    """
    case = a_case("claims")
    findings = [a_finding(case)]
    provider = FakeProvider([decision_json(
        band="desk_review", recommendation="escalate",
        cited=[findings[0].finding_id, "00000000-dead-beef-0000-000000000000"],
    )])

    result = adjudicate(get_conn(), case, findings, CLAIMS_POLICY, provider)
    assert result.decision.supporting_finding_ids == [findings[0].finding_id]
    print("  invented finding id dropped, real one kept")


# ---------------------------------------------------------------------------
# Trace and policies
# ---------------------------------------------------------------------------


@test
def test_trace_records_every_step():
    case = a_case("claims")
    findings = [a_finding(case)]
    provider = FakeProvider([
        ("get_claimant_history", {}),
        ("widen_similarity_search", {"threshold": 0.85}),
        decision_json(band="desk_review", recommendation="escalate"),
    ])

    result = adjudicate(get_conn(), case, findings, CLAIMS_POLICY, provider)
    kinds = [s.kind for s in result.trace]
    assert kinds.count("tool_call") == 2, kinds
    assert kinds.count("llm_call") == 1, kinds
    assert [s.step for s in result.trace] == sorted(s.step for s in result.trace), "steps must be ordered"
    for s in result.trace:
        assert isinstance(s.to_dict(), dict) and s.detail
    json.dumps(result.trace_dicts())  # must be persistable in an audit event
    print(f"  {len(result.trace)} steps, ordered and JSON-serialisable: {kinds}")


@test
def test_both_policies_load_with_different_check_sets():
    assert CLAIMS_POLICY.agent_type == "claims"
    assert UNDERWRITING_POLICY.agent_type == "underwriting"
    assert CLAIMS_POLICY.check_ids != UNDERWRITING_POLICY.check_ids

    # Economic checks are claims-only: underwriting has no claim amount.
    assert "threshold_gaming" in CLAIMS_POLICY.check_ids
    assert "threshold_gaming" not in UNDERWRITING_POLICY.check_ids
    assert "damage_plausibility" not in UNDERWRITING_POLICY.check_ids
    # baseline_corruption is underwriting-only.
    assert "baseline_corruption" in UNDERWRITING_POLICY.check_ids
    assert "baseline_corruption" not in CLAIMS_POLICY.check_ids
    # Biases differ, and that is the point of having two.
    assert CLAIMS_POLICY.escalation_bias == "escalate"
    assert UNDERWRITING_POLICY.escalation_bias == "request_evidence"
    # Dispatch works off the case's own agent_type.
    assert policy_for("underwriting") is UNDERWRITING_POLICY
    assert policy_for("claims") is CLAIMS_POLICY
    assert policy_for("something_else") is CLAIMS_POLICY
    print(f"  claims {len(CLAIMS_POLICY.check_ids)} checks / underwriting "
          f"{len(UNDERWRITING_POLICY.check_ids)}; biases differ")


@test
def test_prompts_state_the_hard_rule_and_the_measured_reliabilities():
    """
    The prompt is the only place the agent learns that one of its own
    findings is measured to be inverted. If that text is lost in an edit,
    nothing else catches it - so it is asserted.
    """
    for prompt in (CLAIMS_POLICY.system_prompt, UNDERWRITING_POLICY.system_prompt):
        lowered = prompt.lower()
        assert "never reject" in lowered or "never reject, deny" in lowered
        assert "no such option exists" in lowered
        assert "ai_generation" in lowered and "inverted" in lowered
        assert "ignore it entirely" in lowered
        assert "plate_ocr" in lowered and "0.2%" in prompt
        assert "internal_duplicate" in lowered and "100%" in prompt
        # The INCONCLUSIVE guidance protects the false-positive rate.
        assert "inconclusive" in lowered and "could not tell" in lowered
    print("  both prompts carry the hard rule, the measured reliabilities, and the "
          "INCONCLUSIVE guidance")


@test
def test_tool_schemas_are_accepted_by_the_real_sdk():
    """
    Regression guard for a bug the rest of this file structurally cannot
    catch.

    FakeProvider accepts whatever `tools` argument it is handed, so every
    other test here passed while the schemas were in a shape google-genai
    rejects outright. The real SDK wants a list of Tool objects, each
    holding `function_declarations`; bare declarations fail validation,
    which surfaced as a provider error and routed every single case to the
    DESK_REVIEW fallback. The pass still completed, every decision was a
    valid AgentDecision, and the whole run silently measured the fallback
    path instead of the agent.

    So this validates against the actual SDK type rather than a fake. It
    skips rather than fails when google-genai is not installed, since the
    rest of the suite is deliberately runnable without it.
    """
    try:
        from google.genai import types
    except ImportError:
        print("  SKIP: google-genai not installed")
        return

    from src.agent.tools import TOOL_SCHEMAS, schemas_for

    for policy in (CLAIMS_POLICY, UNDERWRITING_POLICY):
        schemas = schemas_for(policy.tool_names)
        # Must not raise - this is the assertion.
        types.GenerateContentConfig(temperature=0, tools=schemas)
        assert len(schemas) == 1 and "function_declarations" in schemas[0], schemas
        names = {d["name"] for d in schemas[0]["function_declarations"]}
        assert names == set(policy.tool_names), (names, policy.tool_names)

    # An agent with no tools must yield something the SDK also accepts.
    types.GenerateContentConfig(temperature=0, tools=schemas_for(()) or None)
    # And the flat declarations stay flat, since they are the readable form.
    assert all("name" in s and "parameters" in s for s in TOOL_SCHEMAS)
    print(f"  both policies' schemas validate against google-genai "
          f"({len(TOOL_SCHEMAS)} declarations total)")


@test
def test_agent_never_calls_the_vision_api():
    """
    requery_perception reads the cache. If any path reached the vision
    API mid-adjudication a single case could exhaust a day's quota, so
    FakeProvider.describe_image raises if it is ever touched.
    """
    case = a_case("claims")
    findings = [a_finding(case)]
    images = db.get_images_for_case(get_conn(), case.case_id)
    image_id = images[0].image_id if images else "none"
    provider = FakeProvider([
        ("requery_perception", {"image_id": image_id, "question": "what was the weather?"}),
        decision_json(band="clear", recommendation="approve"),
    ])

    result = adjudicate(get_conn(), case, findings, CLAIMS_POLICY, provider)
    assert result.converged
    assert result.decision.tool_calls_count == 1
    print("  requery_perception served from cache; describe_image never invoked")


if __name__ == "__main__":
    try:
        ok = run_all()
    finally:
        if _conn is not None:
            _conn.close()
    cleanup_conn()
    sys.exit(0 if ok else 1)
