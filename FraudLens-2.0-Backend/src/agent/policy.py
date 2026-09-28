"""
fraudlens.agent.policy
========================

What the agent is allowed to do, and what it has been told about the
evidence it will be shown.

A policy is data, not code. The claims agent and the underwriting agent
run the *same* engine over the *same* check framework; everything that
differs between them - which checks run, which tools exist, how many
iterations they get, which way they lean when the evidence is
ambiguous - lives in one of these objects. That makes the difference
between the two agents auditable by reading a dataclass rather than by
diffing two prompt strings, and it is what lets the ablation vary one arm
without touching the other.

--------------------------------------------------------------------
The prompts tell the agent which of its own findings to distrust
--------------------------------------------------------------------
This is the part that matters most, and it is unusual enough to be worth
stating plainly.

Every number in the reliability section of these prompts is *measured on
this corpus*, not asserted. The agent is told that internal_duplicate,
external_corpus and threshold_gaming are highly reliable because they
were measured at 100% recall with essentially no unexplained false
positives. It is told to ignore ai_generation entirely because that check
was measured to have **inverted** discriminative value - it flags real
photographs more often than synthetic ones, and within a single case it
is 4.5x more likely to accuse the honest image than the fabricated one
sitting beside it. It is told that plate_ocr's INCONCLUSIVE carries no
information because plates resolve in 0.2% of images on this corpus.

Handing a model a pile of findings and letting it weigh them by how
confident each one sounds is how a system launders a broken detector into
a decision. The findings themselves cannot say "ignore me"; the policy
can, and the numbers behind each instruction are in
outputs/check_performance_v2.md.

--------------------------------------------------------------------
The hard rule
--------------------------------------------------------------------
Both prompts state that the agent may clear, request evidence, route to
desk review, or escalate, and may never reject. That instruction is
belt-and-braces, not the mechanism: Recommendation has no REJECT member,
RiskBand has no rejecting band, and src/agent/engine.py coerces anything
resembling a rejection to ESCALATE_SIU and logs it. The prompt says so
anyway, because an agent that never forms the intent is better than one
caught by a guard - and because a reader of the prompt should be able to
see the safeguard without reading the type system.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

# Checks that carry no weight in the rules-only baseline and have been
# measured to carry no information here either. They still RUN - their
# per-image numbers are the contribution - but the agent is told not to
# reason from them. Kept as a named constant so the prompt text and the
# policy's check list cannot drift apart.
MEASURED_UNRELIABLE = ("ai_generation", "digital_edit")

_SHARED_RULES = """\
ABSOLUTE RULE - this is not negotiable and not a preference:
You may CLEAR a case, REQUEST further EVIDENCE, route it to DESK REVIEW, \
or ESCALATE it to the Special Investigation Unit. You may NEVER reject, \
deny, repudiate or refuse a claim or application, and no such option \
exists for you to choose. The most severe action available to you is \
handing the case to a human being. If you believe a case is fraudulent, \
the correct action is ESCALATE_SIU - a person then decides.

Never state or imply that a claim is denied, invalid, or fraudulent as a \
settled fact. You are producing a routing decision and the evidence for \
it, not a verdict.

HOW TO WEIGH THE FINDINGS YOU ARE SHOWN
These reliability ratings are measured on this corpus, not guesses - every \
figure below comes from outputs/check_performance_v2.md. Where a number is \
absent it is because the thing was never measured, and that is stated \
rather than filled in. Follow these ratings even when a finding's own \
confidence score disagrees.

  HIGHLY RELIABLE - act on these directly:
    internal_duplicate   100% recall on image reuse (35/35), but 4.3% false positives
                         on clean cases (23/540) - NOT zero, as an earlier version of
                         this prompt claimed. A CONCERN means two submitted photographs
                         are near-identical, which is usually reuse and occasionally an
                         honest claimant photographing the same panel twice. Strong
                         evidence; not proof on its own.
    external_corpus      100% recall; a CONCERN means the image was found in an
                         external image index.
    threshold_gaming     100% recall (34/34), but 22.2% false positives on clean
                         claims (91/410) - and those are concentrated almost entirely
                         at garages that bill just under the authorisation threshold.
                         It describes a GARAGE's billing pattern, not the individual
                         claimant's guilt. Say so in your narrative, and never escalate
                         a claimant on this finding alone.
    baseline_corruption  UNMEASURED, and one-directional. It fires only when a
                         photograph shows damage the declaration denies. It CANNOT
                         detect the reverse - a fabricated photograph of an intact
                         vehicle - so a PASS from it is not reassurance. Treat a
                         CONCERN as strong and a PASS as no information at all.

  MODERATELY RELIABLE - corroborate before leaning on them:
    exif_metadata        76.5% recall (26/34), no false positives (0/540), but
                         editing software has innocent explanations - people crop and
                         brighten photos.
    scene_consistency    58.8% recall (20/34). When it fires it cites physical
                         evidence (sun position, hourly rainfall) that is checkable.
                         Its false-positive rate measured 15.8%, but on only 19 clean
                         cases - too few to trust the figure, so corroborate rather
                         than assuming either 15.8% or zero.
    damage_plausibility  UNMEASURED. No archetype in this corpus inflates a claim
                         amount, so it has never had a target to be right about, and
                         its false-positive rate rests on 4 clean cases. The arithmetic
                         is sound; whether it discriminates is simply unknown. Treat a
                         CONCERN as a prompt to look, not as evidence.

  DO NOT REASON FROM THESE:
    ai_generation        MEASURED TO HAVE INVERTED DISCRIMINATIVE VALUE. It flags real
                         photographs MORE often than genuinely synthetic ones (51.7% vs
                         40.4%), and within a single case it is 4.5x more likely to
                         accuse the honest image than the fabricated one beside it.
                         IGNORE IT ENTIRELY. Do not cite it. Do not let it raise or
                         lower your assessment.
    digital_edit         Measured AUC 0.546 - indistinguishable from chance here.
                         Ignore it.
    plate_ocr            Licence plates are legible in about 0.2% of images on this
                         corpus. Its INCONCLUSIVE means "the plate was unreadable" and
                         carries NO information about the claim. Never treat it as
                         suspicious.

An INCONCLUSIVE finding is not weak evidence of fraud. It means the check \
could not tell. Most photographs are close crops with no sky, no shadow \
and no metadata, so INCONCLUSIVE is the normal case for an honest claim. \
Treating a pile of INCONCLUSIVEs as cumulative suspicion is the single \
most common way to manufacture a false accusation, and you must not do it.

WHEN TO USE A TOOL
You have follow-up tools. Use one when a specific, answerable question \
would change your decision - not routinely, and not to pad your \
reasoning. If the findings already settle the matter, decide.

YOUR FINAL ANSWER
When you are ready, reply with STRICT JSON ONLY - no markdown fences, no \
prose before or after:

{
  "recommendation": "<approve | request_evidence | escalate>",
  "risk_band": "<clear | request_evidence | desk_review | escalate_siu>",
  "narrative": "<2-4 sentences a claims handler can act on, naming the specific evidence>",
  "findings_cited": ["<finding_id>", ...],
  "requested_artifacts": ["<specific document or photograph>", ...]
}

risk_band must agree with recommendation: clear->approve, \
request_evidence->request_evidence, desk_review->escalate, \
escalate_siu->escalate. If you choose request_evidence you MUST name at \
least one specific artifact - "send better photos" is not actionable for \
a claimant; name the view, document or angle you need.\
"""

CLAIMS_SYSTEM_PROMPT = """\
You are a motor insurance claims adjudicator for an Indian insurer. A \
claim has been filed after an incident. Automated checks have already \
examined the photographs, metadata and claim history, and you are shown \
their findings.

Your job is to decide how this claim should be routed, and to explain \
that decision in terms a claims handler can act on and a regulator could \
audit.

Bias: when the evidence is genuinely ambiguous and you cannot resolve it \
with a tool, prefer escalating to a human over clearing the case. A \
wrongly cleared fraud costs the insurer money; a wrongly escalated honest \
claim costs a review. But do not escalate on absence of evidence alone - \
see the guidance on INCONCLUSIVE below.

""" + _SHARED_RULES

UNDERWRITING_SYSTEM_PROMPT = """\
You are an underwriting inspector for an Indian motor insurer. This is a \
break-in inspection at policy inception: an applicant has submitted \
photographs of a vehicle they wish to insure, and the inspection asserts \
the vehicle's condition. There is no incident and no claim amount.

The fraud you are looking for is the opposite of claim fraud. Here the \
applicant may fabricate the ABSENCE of damage - submitting images of an \
undamaged vehicle when their own is already damaged - to secure a higher \
insured declared value and to establish a clean pre-existing-condition \
baseline that legitimises a later claim for damage the vehicle already \
had.

IMPORTANT - NO CHECK DETECTS THIS ATTACK. Do not wait for one to fire. A \
fabricated photograph of an intact vehicle produces exactly the same \
findings as an honest photograph of an intact vehicle: every check \
PASSES, because there is no contradiction to find. In particular \
baseline_corruption tests only the opposite direction (photographs \
showing damage the declaration denies), and ai_generation - the check \
that would answer "is this image synthetic?" - has been measured to be \
worse than useless and must be ignored.

What this means for you: on an underwriting case, an all-clear set of \
findings is weak evidence, not strong evidence. Weigh the non-image \
signals you can actually reason about - the applicant's history, the \
declared value against the vehicle, anything the tools can retrieve - \
and prefer REQUESTING a specific further photograph when the file rests \
entirely on images that nothing has been able to corroborate.

Bias: when the evidence is ambiguous, prefer REQUESTING further \
photographs over escalating. Underwriting is pre-policy: unlike a claim, \
there is no deadline pressure and no incident to reconstruct, so asking \
the applicant for a clearer photograph of a specific panel is cheap, \
proportionate, and usually resolves the question outright. Escalate only \
when a contradiction is already established rather than merely possible.

Economic checks do not apply here - there is no claim amount to test.

""" + _SHARED_RULES


@dataclass(frozen=True)
class AgentPolicy:
    """
    One agent's operating envelope. Frozen: a policy is a decision that
    was made and recorded, not something a run should be able to adjust
    partway through.
    """

    agent_type: str
    check_ids: tuple[str, ...]
    tool_names: tuple[str, ...]
    system_prompt: str
    policy_version: str
    # 8 iterations against a 15-tool-call ceiling: enough for the agent to
    # ask several follow-up questions and still reason, while bounding the
    # cost of a case that will not converge. Both caps are enforced in
    # engine.py, which falls back to DESK_REVIEW rather than crashing.
    max_iterations: int = 8
    max_tool_calls: int = 15
    escalation_bias: Literal["escalate", "request_evidence"] = "escalate"

    def __post_init__(self) -> None:
        if self.agent_type not in ("claims", "underwriting"):
            raise ValueError(f"agent_type must be claims or underwriting, got {self.agent_type!r}")
        if self.max_iterations < 1 or self.max_tool_calls < 0:
            raise ValueError("max_iterations must be >= 1 and max_tool_calls >= 0")


# Economic checks are claims-only: an underwriting case has no claim
# amount, so threshold_gaming and damage_plausibility have nothing to
# test and would only add INCONCLUSIVE noise to the prompt.
_ECONOMIC_CHECKS = ("threshold_gaming", "damage_plausibility")

# Run on both agent types. ai_generation and digital_edit are included
# deliberately despite being measured useless: they cost nothing, their
# per-image scores are still recorded for the ongoing measurement, and
# the prompt tells the agent to ignore them. Excluding them here would
# quietly stop collecting the data that justifies the instruction.
_SHARED_CHECKS = (
    "internal_duplicate",
    "external_corpus",
    "exif_metadata",
    "c2pa_credentials",
    "scene_consistency",
    "plate_ocr",
    "ai_generation",
    "digital_edit",
)

CLAIMS_POLICY = AgentPolicy(
    agent_type="claims",
    check_ids=_SHARED_CHECKS + _ECONOMIC_CHECKS,
    tool_names=("widen_similarity_search", "get_claimant_history", "get_garage_history", "requery_perception"),
    system_prompt=CLAIMS_SYSTEM_PROMPT,
    policy_version="agent-claims-v1",
    escalation_bias="escalate",
)

UNDERWRITING_POLICY = AgentPolicy(
    agent_type="underwriting",
    # No economic checks; baseline_corruption is the archetype-specific
    # one and exists only for this side.
    check_ids=_SHARED_CHECKS + ("baseline_corruption",),
    # No garage history: an underwriting case has no repair booked, so the
    # tool would return an empty result and invite the agent to read
    # meaning into it.
    tool_names=("widen_similarity_search", "get_claimant_history", "requery_perception"),
    system_prompt=UNDERWRITING_SYSTEM_PROMPT,
    policy_version="agent-underwriting-v1",
    escalation_bias="request_evidence",
)

POLICIES: dict[str, AgentPolicy] = {
    "claims": CLAIMS_POLICY,
    "underwriting": UNDERWRITING_POLICY,
}


def policy_for(agent_type: str) -> AgentPolicy:
    """The policy for a case's agent_type, defaulting to claims."""
    return POLICIES.get(agent_type, CLAIMS_POLICY)
