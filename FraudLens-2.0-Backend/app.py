"""
FraudLens analyst interface — Streamlit.

**This is a debugging and demonstration tool, not the product UI.** A
separate frontend consumes src/api.py; this exists so that a human can look
at a case, follow the agent's reasoning, and see the ablation numbers
without writing SQL. It is deliberately thin, and no effort has gone into
polish that the real frontend will replace anyway.

Everything is read through the HTTP API rather than the database. That is
the point: it makes this a real consumer of the contract, so a missing
field or an awkward shape shows up here rather than in the frontend build.
Two contract gaps surfaced immediately on writing it, both now fixed in
api.py - see FIELD NOTES at the bottom of this file.

Run:
    uvicorn src.api:app --port 8000        # terminal 1
    streamlit run app.py                   # terminal 2

Point elsewhere with FRAUDLENS_API=http://host:port
"""

from __future__ import annotations

import os
from typing import Any, Optional

import pandas as pd
import requests
import streamlit as st

API = os.environ.get("FRAUDLENS_API", "http://127.0.0.1:8000")
TIMEOUT = 30

BAND_COLOUR = {
    "clear": "#1a7f37",
    "request_evidence": "#9a6700",
    "desk_review": "#bc4c00",
    "escalate_siu": "#cf222e",
}
VERDICT_ICON = {"pass": "✅", "inconclusive": "⚪", "concern": "🚩"}
CATEGORY_ORDER = ("identity", "history", "provenance", "context", "economic")

st.set_page_config(page_title="FraudLens", layout="wide")


# ---------------------------------------------------------------------------
# API client
# ---------------------------------------------------------------------------

@st.cache_data(ttl=30, show_spinner=False)
def api_get(path: str, **params: Any) -> Optional[Any]:
    """GET with the failure surfaced in the page rather than as a traceback."""
    try:
        r = requests.get(f"{API}{path}", params={k: v for k, v in params.items()
                                                 if v not in (None, "", "any")},
                         timeout=TIMEOUT)
    except requests.RequestException as e:
        st.error(f"Cannot reach the API at `{API}` — is it running?\n\n`{e}`")
        st.code("uvicorn src.api:app --port 8000", language="bash")
        return None
    if r.status_code == 404:
        return None
    if not r.ok:
        st.error(f"{r.status_code} from `{path}`: {r.text[:300]}")
        return None
    return r.json()



def _escape(text: str) -> str:
    return (str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def _md_to_html(text: str) -> str:
    """Bold-only markdown, since the timeline is raw HTML."""
    out = _escape(text)
    while out.count("**") >= 2:
        out = out.replace("**", "<b>", 1).replace("**", "</b>", 1)
    return out


def band_chip(band: Optional[str]) -> str:
    if not band:
        return "—"
    colour = BAND_COLOUR.get(band, "#57606a")
    return (f"<span style='background:{colour};color:#fff;padding:2px 8px;"
            f"border-radius:10px;font-size:0.8em'>{band}</span>")


# ---------------------------------------------------------------------------
# Page: case queue
# ---------------------------------------------------------------------------

def page_queue() -> None:
    st.header("Case queue")

    stats = api_get("/v1/stats")
    if stats is None:
        return

    c1, c2, c3, c4 = st.columns(4)
    band = c1.selectbox("Risk band", ["any", *BAND_COLOUR])
    agent_type = c2.selectbox("Agent type", ["any", "claims", "underwriting"])
    status = c3.selectbox("Status", ["any", *sorted(stats["by_status"])])
    archetypes = ["any", "CLEAN", "REUSE", "EXTERNAL_SOURCING", "METADATA_FORGERY",
                  "THRESHOLD_GAMING", "CONTEXT_MISMATCH", "DIGITAL_EDIT",
                  "AI_GENERATED", "AI_GENERATED_BASELINE"]
    archetype = c4.selectbox("Archetype", archetypes,
                             help="Evaluation metadata — a real claim never carries this.")

    limit = st.slider("Rows", 10, 200, 50, step=10)
    data = api_get("/v1/cases", risk_band=band, agent_type=agent_type,
                   status=status, archetype=archetype, limit=limit)
    if data is None:
        return

    st.caption(f"{data['total']} case(s) match; showing {len(data['items'])}.")
    if not data["items"]:
        st.info("No cases match these filters.")
        return

    frame = pd.DataFrame(data["items"])
    columns = [c for c in ("case_id", "agent_type", "archetype", "risk_band",
                           "recommendation", "concern_count", "image_count",
                           "claim_amount", "status", "declared_location")
               if c in frame.columns]

    def colour_band(value: Any) -> str:
        return f"color: {BAND_COLOUR.get(value, '')}; font-weight: 600"

    st.dataframe(
        frame[columns].style.map(colour_band, subset=["risk_band"]),
        width='stretch', hide_index=True,
    )
    st.caption("Open a case from the **Case detail** page using its id.")


# ---------------------------------------------------------------------------
# Page: case detail
# ---------------------------------------------------------------------------

def case_picker(key: str) -> Optional[str]:
    listing = api_get("/v1/cases", limit=200)
    if listing is None:
        return None
    ids = [i["case_id"] for i in listing["items"]]
    typed = st.text_input("Case id", value=st.session_state.get(key, ids[0] if ids else ""),
                          key=f"{key}_input")
    return typed.strip() or None


def page_detail() -> None:
    st.header("Case detail")
    case_id = case_picker("detail_case")
    if not case_id:
        return
    case = api_get(f"/v1/cases/{case_id}")
    if case is None:
        st.warning(f"No case `{case_id}`.")
        return

    left, right = st.columns([2, 1])
    with left:
        st.subheader("Declaration")
        st.write({
            "case_id": case["case_id"],
            "agent_type": case["agent_type"],
            "claim_type": case.get("claim_type"),
            "declared_location": case.get("declared_location"),
            "declared_time": case.get("declared_time"),
            "claim_amount": case.get("claim_amount"),
            "vehicle_registration": case.get("vehicle_registration"),
            "garage_id": case.get("garage_id"),
            "status": case.get("status"),
            "archetype (ground truth)": case.get("archetype"),
        })
    with right:
        st.subheader("Decision")
        decision = case.get("decision")
        if not decision:
            st.info("Not yet adjudicated.")
        else:
            st.markdown(band_chip(decision.get("risk_band")), unsafe_allow_html=True)
            st.write(f"**{decision['recommendation']}** · confidence "
                     f"{decision['confidence']:.2f}")
            st.write(decision["summary"])
            if decision.get("requested_artifacts"):
                st.write("**Requested:**")
                for artifact in decision["requested_artifacts"]:
                    st.write(f"- {artifact}")
            st.caption(f"{decision.get('policy_version')} · "
                       f"{decision.get('tool_calls_count', 0)} tool call(s) · "
                       f"{decision.get('iterations_count', 0)} iteration(s) · "
                       f"{decision.get('latency_ms', 0) / 1000:.1f}s")
        if len(case.get("decisions", [])) > 1:
            st.caption(f"{len(case['decisions'])} decisions on this case "
                       "(both ablation arms).")

    st.subheader("Images")
    images = case.get("images", [])
    if not images:
        st.info("No images.")
    else:
        for column, image in zip(st.columns(min(4, len(images))), images):
            with column:
                # Served by the API: the browser cannot read the disk.
                column.image(f"{API}{image['url']}", width='stretch')
                column.caption(("perceived" if image.get("has_perception")
                                else "not perceived") + f" · {image['image_id'][:8]}")
                # The scene description is evidence a reviewer needs to see.
                # No check tests geography, so a contradiction like case-0091's
                # Sonoran-desert backdrop on a Vadodara claim appears nowhere
                # in the findings - only here.
                if image.get("scene_context"):
                    column.caption(f"👁 {image['scene_context']}")
                if image.get("damage_severity"):
                    detail = image.get("damage_description") or ""
                    column.caption(f"damage: **{image['damage_severity']}**"
                                   + (f" — {detail}" if detail else ""))
                if image.get("anomaly_notes"):
                    column.caption(f"⚠ {image['anomaly_notes']}")

    st.subheader("Findings")
    grouped = case.get("findings_by_category", {})
    if not any(grouped.values()):
        st.info("No findings recorded.")
        return
    for category in CATEGORY_ORDER:
        findings = grouped.get(category) or []
        if not findings:
            continue
        concerns = sum(1 for f in findings if f["verdict"] == "concern")
        label = f"{category.upper()} — {len(findings)} finding(s)"
        with st.expander(label + (f" · {concerns} concern" if concerns else ""),
                         expanded=bool(concerns)):
            for f in findings:
                st.write(f"{VERDICT_ICON.get(f['verdict'], '')} **{f['check_id']}** "
                         f"· {f['verdict']} · confidence {f['confidence']:.2f}")
                st.caption(f["explanation"])


# ---------------------------------------------------------------------------
# Page: agent trace
# ---------------------------------------------------------------------------

def _describe_step(step: dict) -> tuple[str, str, str]:
    """(icon, headline, body) for one step, in plain language."""
    kind = step.get("kind", "step")
    detail = step.get("detail") or ""
    payload = step.get("payload") or {}

    if kind == "tool_call":
        args = payload.get("args") or {}
        asked = ", ".join(f"{k} = {v}" for k, v in args.items()) or "no arguments"
        returned = payload.get("result_keys") or []
        if payload.get("error"):
            body = f"Asked for {asked}. It returned an error: {payload['error']}"
        elif returned:
            body = f"Asked for {asked}. It came back with: {', '.join(returned)}."
        else:
            body = f"Asked for {asked}. Nothing came back."
        return "🔎", f"Looked up **{detail}**", body

    if kind == "llm_call":
        rec = payload.get("recommendation")
        body = f"Recommendation: {rec}." if rec else ""
        return "🧠", f"Reached a conclusion — {detail}", body

    if kind == "parse_failure":
        preview = (payload.get("reply_preview") or "").strip()
        return ("↩️", "Its reply could not be read as a decision, so it was asked again",
                f"What it said: “{preview[:200]}”" if preview else "")

    if kind == "guard":
        return "🛑", f"Stopped by a policy limit — {detail}", str(payload) if payload else ""

    if kind == "fallback":
        return "⚠️", f"Fell back to a safe default — {detail}", ""

    return "•", detail or kind, ""


def page_trace() -> None:
    st.header("Agent trace")
    st.caption("What the agent did, in order. Each step is one decision it made about "
               "what it still needed to know.")
    case_id = case_picker("trace_case")
    if not case_id:
        return
    trace = api_get(f"/v1/cases/{case_id}/trace")
    if trace is None:
        st.warning(f"No case `{case_id}`.")
        return

    all_steps = trace.get("steps", [])
    if not all_steps:
        st.info("No trace recorded — this case was decided by the rules-only baseline, "
                "or has not been adjudicated yet.")
        return

    # A 429 is not reasoning. The API flags these rather than hiding them, so
    # the decision to leave them out belongs here, where the audience is a
    # person being shown how the system thinks.
    steps = [s for s in all_steps if not s.get("is_outage")]
    outages = len(all_steps) - len(steps)

    st.caption(f"policy `{trace.get('policy_version')}` · "
               f"{'converged' if trace.get('converged') else 'did not converge'} · "
               f"{len(steps)} step(s)")
    if outages:
        st.info(f"{outages} step(s) recording a provider outage are not shown — they "
                "describe the free-tier quota running out, not anything the agent "
                "decided.")
    if not steps:
        st.warning("Every recorded step was a provider outage; there is no reasoning to "
                   "show for this case.")
        return

    # Vertical timeline. Deliberately CSS rather than nested expanders: an
    # examiner should be able to read the whole sequence top to bottom without
    # clicking anything open.
    st.markdown(
        """
        <style>
        .fl-timeline { border-left: 2px solid #d0d7de; margin-left: 12px;
                       padding-left: 20px; }
        .fl-step { position: relative; padding-bottom: 18px; }
        .fl-step::before { content: ''; position: absolute; left: -27px; top: 4px;
                           width: 12px; height: 12px; border-radius: 50%;
                           background: #0969da; border: 2px solid #fff; }
        .fl-step.fl-final::before { background: #1a7f37; }
        .fl-head { font-size: 0.98em; }
        .fl-body { color: #57606a; font-size: 0.88em; margin-top: 2px; }
        .fl-meta { color: #8c959f; font-size: 0.78em; margin-top: 2px; }
        </style>
        """,
        unsafe_allow_html=True,
    )

    html = ["<div class='fl-timeline'>"]
    for i, step in enumerate(steps):
        icon, headline, body = _describe_step(step)
        final = " fl-final" if i == len(steps) - 1 else ""
        latency = step.get("latency_ms") or 0
        meta = f"{latency / 1000:.1f}s" if latency else ""
        html.append(f"<div class='fl-step{final}'>")
        html.append(f"<div class='fl-head'>{icon} <b>Step {i + 1}.</b> "
                    f"{_md_to_html(headline)}</div>")
        if body:
            html.append(f"<div class='fl-body'>{_escape(body)}</div>")
        if meta:
            html.append(f"<div class='fl-meta'>{meta}</div>")
        html.append("</div>")
    html.append("</div>")
    st.markdown("".join(html), unsafe_allow_html=True)

    decision = (api_get(f"/v1/cases/{case_id}") or {}).get("decision")
    if decision:
        st.divider()
        st.subheader("What it concluded")
        st.markdown(band_chip(decision.get("risk_band")), unsafe_allow_html=True)
        st.write(decision.get("summary", ""))


# ---------------------------------------------------------------------------
# Page: dashboard
# ---------------------------------------------------------------------------

def load_ablation() -> Optional[pd.DataFrame]:
    """
    The ablation rows come from disk, not the API.

    They are experiment output rather than production state - the API serves
    the current decision for a case, not the several decisions the two arms
    produced for it. Reading the JSONL here keeps that distinction instead of
    inventing an endpoint for a research artefact.
    """
    path = "outputs/ablation_results.jsonl"
    if not os.path.exists(path):
        return None
    rows = pd.read_json(path, lines=True)
    return rows if not rows.empty else None


def page_dashboard() -> None:
    st.header("Dashboard")
    stats = api_get("/v1/stats")
    if stats is None:
        return

    c1, c2, c3, c4 = st.columns(4)
    stp = stats.get("straight_through_rate")
    c1.metric("Straight-through rate", "n/a" if stp is None else f"{stp:.1%}",
              help="Share of decided cases cleared with no human touch.")
    c2.metric("Cases", stats["total_cases"])
    c3.metric("Decided", stats["decided_cases"])
    c4.metric("Concern findings", stats["concern_findings"])

    left, right = st.columns(2)
    with left:
        st.subheader("Cases by risk band")
        bands = stats.get("by_risk_band") or {}
        if bands:
            st.bar_chart(pd.Series(bands, name="cases"))
        else:
            st.info("No decisions yet.")
    with right:
        st.subheader("Concern findings by check")
        by_check = stats.get("by_check") or {}
        if by_check:
            st.bar_chart(pd.Series(by_check, name="concerns").sort_values(ascending=False))
        else:
            st.info("No concern findings yet.")

    st.subheader("Ablation — the two arms side by side")
    frame = load_ablation()
    if frame is None:
        st.info("No ablation results yet (`outputs/ablation_results.jsonl`).")
        return

    rows = []
    for arm in ("baseline", "agent"):
        arm_rows = frame[frame["arm"] == arm]
        if arm_rows.empty:
            continue
        fraud = arm_rows[arm_rows["is_fraud"]]
        clean = arm_rows[~arm_rows["is_fraud"]]
        caught = int((fraud["risk_band"] != "clear").sum())
        flagged_clean = int((clean["risk_band"] != "clear").sum())
        rows.append({
            "arm": arm,
            "cases": len(arm_rows),
            "fraud caught": f"{caught}/{len(fraud)}" if len(fraud) else "n/a",
            "clean flagged": f"{flagged_clean}/{len(clean)}" if len(clean) else "n/a",
            "mean tool calls": round(arm_rows["tool_calls"].mean(), 2),
            "mean LLM calls": round(arm_rows["llm_calls"].mean(), 2),
            "mean latency (s)": round(arm_rows["latency_ms"].mean() / 1000, 1),
        })
    st.dataframe(pd.DataFrame(rows), width='stretch', hide_index=True)

    # The arms cover different numbers of cases while the agent arm is still
    # running, and comparing them on different populations is a sampling
    # artefact rather than a result. Say so on the page, not just in the report.
    counts = frame.groupby("arm")["case_id"].nunique().to_dict()
    if len(counts) > 1 and len(set(counts.values())) > 1:
        st.warning(
            f"The arms have adjudicated different case counts ({counts}). The agent arm "
            "is quota-bound and still running. Compare them only on their shared subset "
            "— see `outputs/ablation_results.md`, which does exactly that."
        )


# ---------------------------------------------------------------------------

PAGES = {
    "Case queue": page_queue,
    "Case detail": page_detail,
    "Agent trace": page_trace,
    "Dashboard": page_dashboard,
}


def main() -> None:
    st.sidebar.title("FraudLens")
    st.sidebar.caption("Analyst interface — debugging and demonstration only. "
                       "The production frontend consumes the same API.")
    choice = st.sidebar.radio("Page", list(PAGES))
    st.sidebar.divider()
    st.sidebar.caption(f"API: `{API}`")
    health = api_get("/v1/health")
    st.sidebar.caption("API reachable ✅" if health else "API unreachable ❌")
    PAGES[choice]()


if __name__ == "__main__":
    main()


# ---------------------------------------------------------------------------
# FIELD NOTES — contract gaps this consumer surfaced
# ---------------------------------------------------------------------------
# Writing this page against the API found two things that reading the code
# would not have:
#
# 1. The case list has no way to ask for "cases with a decision". Rendering a
#    review queue means filtering client-side on risk_band being non-null,
#    which does not paginate correctly - page 2 of a filtered set is not the
#    second page of the filter. Worth a `decided: bool` query parameter.
#
# 2. /v1/cases/{id} returns every decision for a case, which is right, but
#    offers no way to ask for one arm's decision specifically. This page shows
#    the newest and counts the rest. A `?policy_version=` filter would let the
#    frontend show the arms side by side without fetching everything.
#
# Neither blocks this tool, so neither has been changed unilaterally - they
# are recorded here for the frontend contract discussion.
