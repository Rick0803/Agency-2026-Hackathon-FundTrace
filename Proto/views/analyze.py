# views/analyze.py
# Analyze page — deterministic ghost capacity scoring, no LLM.

import json
import streamlit as st
import pandas as pd
import altair as alt
from dataclasses import asdict, is_dataclass

from agent.orchestrator import (
    run_entity_batch_analysis,
    run_portfolio_analysis as _run_portfolio_analysis,
)
from views.general import (
    SEVERITY_COLOUR,
    go_to_page,
    set_selected_entity,
)


@st.cache_data(ttl=3600, show_spinner=False)
def _cached_run_portfolio_analysis(min_fed_total: float) -> dict:
    return _run_portfolio_analysis(min_fed_total=min_fed_total)


# ─── LLM summary (placeholder) ────────────────────────────────────────────────
# TODO: replace _build_summary_prompt + the stub body of _llm_analysis_summary
# with a real Anthropic API call once credentials are available.
# The function signature, inputs, and display block below should stay unchanged.

def _build_summary_prompt(batch_results: list, portfolio_result: dict) -> str:
    """Constructs the prompt that will be sent to the LLM."""
    total      = len(batch_results)
    critical   = sum(1 for r in batch_results if r.overall_risk == "CRITICAL")
    high       = sum(1 for r in batch_results if r.overall_risk == "HIGH")
    avg_score  = sum(r.ghost_score for r in batch_results) / max(total, 1)
    top        = max(batch_results, key=lambda r: r.ghost_score) if batch_results else None
    stats      = portfolio_result.get("portfolio", {})
    by_prov    = stats.get("by_province", pd.DataFrame())
    univ_total = portfolio_result.get("total_entities", 0)
    univ_risky = int(by_prov["risky_count"].sum()) if not by_prov.empty and "risky_count" in by_prov.columns else 0

    top_line = (
        f"Highest-risk: {top.canonical_name} (score {top.ghost_score:.3f}, {top.overall_risk})"
        if top else "No entities analyzed."
    )
    return (
        f"You are a federal funding analyst reviewing {total} flagged non-profit organizations "
        f"for ghost capacity — operations that consume public funding without delivering services. "
        f"Findings: {critical} CRITICAL, {high} HIGH, average ghost score {avg_score:.3f}. "
        f"{top_line}. "
        f"Universe context: {univ_total:,} funded organizations total, {univ_risky:,} flagged in universe. "
        f"Write exactly one sentence (under 40 words) summarizing the key risk signal for a non-technical audience."
    )


def _llm_analysis_summary(batch_results: list, portfolio_result: dict) -> str:
    """
    Returns a one-sentence plain-English summary of the analysis findings.

    STUB — generates a deterministic message from the data.
    Replace the body below with:

        import anthropic
        client = anthropic.Anthropic()
        prompt = _build_summary_prompt(batch_results, portfolio_result)
        msg = client.messages.create(
            model="claude-opus-4-7",
            max_tokens=80,
            messages=[{"role": "user", "content": prompt}],
        )
        return msg.content[0].text.strip()
    """
    total     = len(batch_results)
    critical  = sum(1 for r in batch_results if r.overall_risk == "CRITICAL")
    high      = sum(1 for r in batch_results if r.overall_risk == "HIGH")
    avg_score = sum(r.ghost_score for r in batch_results) / max(total, 1)
    top       = max(batch_results, key=lambda r: r.ghost_score) if batch_results else None

    if critical >= 1:
        lead = f"{critical} of your {total} flagged organization{'s' if total > 1 else ''} show CRITICAL ghost capacity signals"
    elif high >= 1:
        lead = f"{high} of your {total} flagged organization{'s' if total > 1 else ''} show HIGH-risk ghost capacity signals"
    else:
        lead = f"All {total} flagged organization{'s' if total > 1 else ''} score below the high-risk threshold"

    if top:
        tail = f", with {top.canonical_name} carrying the strongest risk at a ghost score of {top.ghost_score:.2f}."
    else:
        tail = "."

    return lead + tail


def _render_analysis_summary_block(batch_results: list, portfolio_result: dict) -> None:
    summary = _llm_analysis_summary(batch_results, portfolio_result)
    prompt = _build_summary_prompt(batch_results, portfolio_result)
    st.info(f"**Analysis Summary** — {summary}")
    st.caption("Placeholder for a future LLM-generated portfolio summary.")
    st.session_state["analysis_summary_prompt"] = prompt


# ─── Chart helper ─────────────────────────────────────────────────────────────

def _labeled_bar_chart(df: pd.DataFrame, x_col: str, y_col: str,
                        x_title: str = "", y_title: str = "",
                        colour: str = "#4C78A8") -> alt.Chart:
    base = alt.Chart(df).encode(
        x=alt.X(f"{x_col}:N", title=x_title, sort=None),
        y=alt.Y(f"{y_col}:Q", title=y_title),
    )
    bars   = base.mark_bar(color=colour)
    labels = base.mark_text(dy=-6, fontSize=11).encode(
        text=alt.Text(f"{y_col}:Q", format=".2f")
    )
    return (bars + labels).properties(height=280)


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _to_plain(value):
    if is_dataclass(value):
        return _to_plain(asdict(value))
    if isinstance(value, pd.DataFrame):
        return value.to_dict(orient="records")
    if isinstance(value, pd.Series):
        return value.to_dict()
    if isinstance(value, dict):
        return {k: _to_plain(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_to_plain(v) for v in value]
    if hasattr(value, "item"):
        try:
            return value.item()
        except Exception:
            return value
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return value


def _batch_results_df(results: list) -> pd.DataFrame:
    rows = []
    for r in sorted(results, key=lambda x: x.ghost_score, reverse=True):
        colour = SEVERITY_COLOUR.get(r.overall_risk, "⚪")
        rows.append({
            "Organization":       r.canonical_name,
            "BN":                 r.bn_root,
            "Province":           r.province,
            "Overall Risk":       f"{colour} {r.overall_risk}",
            "Ghost Score":        f"{r.ghost_score:.3f}",
            "Avg Gov Dep (%)":    f"{r.avg_gov_dependency*100:.1f}%",
            "Avg Program Sp (%)": f"{r.avg_program_ratio*100:.1f}%",
            "Fed Total ($)":      f"${r.fed_total:,.0f}",
            "Funding Gap ($)":    f"${r.funding_gap:,.0f}",
            "Employees":          r.total_employees,
            "CRA Years":          r.cra_years,
            "Confidence":         r.confidence,
            "Top Flags":          ", ".join(r.top_flags or []),
            "Explanation":        r.explanation[:140] + ("..." if len(r.explanation) > 140 else ""),
        })
    return pd.DataFrame(rows)


def _set_default_report_entity(results: list) -> None:
    if not results:
        return
    top = max(results, key=lambda x: x.ghost_score)
    set_selected_entity({
        "canonical_name":  top.canonical_name,
        "bn_root":         top.bn_root,
        "entity_type":     top.entity_type,
        "province":        top.province,
        "dataset_sources": [
            s for s in [
                "cra" if top.has_cra_data else None,
                "fed" if top.has_fed_data else None,
            ] if s
        ],
    })


def _fmt_pct(df: pd.DataFrame, cols: list) -> pd.DataFrame:
    for c in cols:
        if c in df.columns:
            df[c] = df[c].map(lambda x: f"{float(x)*100:.1f}%" if x is not None else "N/A")
    return df


def _fmt_dollar(df: pd.DataFrame, cols: list) -> pd.DataFrame:
    for c in cols:
        if c in df.columns:
            df[c] = df[c].map(lambda x: f"${float(x):,.0f}" if x is not None else "N/A")
    return df


# ─── Public entry point ────────────────────────────────────────────────────────

def render_analyze() -> None:
    st.title("FundTrace")
    st.subheader("Analysis")

    flagged: list = st.session_state.get("flagged_list", [])
    if not flagged:
        st.info("Your flagged list is empty. Go to Fetch and add organizations before analysis.")
        return

    batch_results    = st.session_state.get("batch_analysis_results")
    portfolio_result = st.session_state.get("portfolio_results")

    if batch_results is None or portfolio_result is None:
        with st.spinner(f"Scoring {len(flagged)} flagged entities and loading portfolio baseline…"):
            if batch_results is None:
                batch_results = run_entity_batch_analysis(flagged)
                st.session_state["batch_analysis_results"] = batch_results
            if portfolio_result is None:
                portfolio_result = _cached_run_portfolio_analysis(0.0)
                st.session_state["portfolio_results"] = portfolio_result

    _render_combined_analysis(batch_results, portfolio_result)


# ─── Combined analysis view ────────────────────────────────────────────────────

def _render_combined_analysis(batch_results: list, portfolio_result: dict) -> None:
    stats      = portfolio_result.get("portfolio", {})
    dept_df    = portfolio_result.get("departments", pd.DataFrame())
    total_ents = portfolio_result.get("total_entities", 0)

    # ── AI summary (stub — replace with LLM call when credentials are ready) ──
    _render_analysis_summary_block(batch_results, portfolio_result)

    # ── Section 1: Your flagged entities ──────────────────────────────────────
    st.subheader("Your Flagged Entities")

    critical_count = sum(1 for r in batch_results if r.overall_risk == "CRITICAL")
    high_count     = sum(1 for r in batch_results if r.overall_risk == "HIGH")
    avg_ghost      = sum(r.ghost_score for r in batch_results) / max(len(batch_results), 1)

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Analyzed", len(batch_results),
              help="Total flagged entities scored in this run.")
    m2.metric("CRITICAL", critical_count,
              help="Ghost score ≥ 0.8 — strongest evidence of ghost capacity.")
    m3.metric("HIGH", high_count,
              help="Ghost score 0.6–0.8 — probable ghost pattern, warrants review.")
    m4.metric("Avg Ghost Score", f"{avg_ghost:.3f}",
              help="Weighted composite 0–1 across five dimensions: "
                   "government revenue dependency (25%), program delivery deficit (30%), "
                   "compensation burden (20%), pass-through transfers (15%), no employees (10%). "
                   "0–0.3 low · 0.3–0.6 medium · 0.6–0.8 high · 0.8–1.0 critical.")

    st.caption("Ranked by ghost score — higher means stronger ghost capacity signals.")
    st.dataframe(_batch_results_df(batch_results), use_container_width=True, hide_index=True)

    if batch_results:
        top = max(batch_results, key=lambda x: x.ghost_score)
        st.markdown("**Highest-risk finding**")
        h1, h2, h3 = st.columns(3)
        h1.metric("Organization", top.canonical_name)
        h2.metric("Risk Label", top.overall_risk,
                  help="CRITICAL / HIGH / MEDIUM / LOW derived from ghost score thresholds.")
        h3.metric("Ghost Score", f"{top.ghost_score:.3f}",
                  help="0–1 composite. See Avg Ghost Score tooltip for dimension weights.")
        st.caption(top.explanation)

    batch_json = json.dumps(_to_plain(batch_results), indent=2, default=str)
    batch_csv  = _batch_results_df(batch_results).to_csv(index=False)
    dl1, dl2, _ = st.columns([1, 1, 2])
    dl1.download_button("Download JSON", data=batch_json,
                        file_name="batch-analysis.json", mime="application/json",
                        use_container_width=True)
    dl2.download_button("Download CSV", data=batch_csv,
                        file_name="batch-analysis.csv", mime="text/csv",
                        use_container_width=True)

    st.divider()

    # ── Section 2: Universe context ───────────────────────────────────────────
    st.subheader("Universe Context")
    st.caption(
        f"How your flagged entities compare against {total_ents:,} funded organizations in the full universe."
    )

    by_prov        = stats.get("by_province", pd.DataFrame())
    total_risky    = int(by_prov["risky_count"].sum()) if not by_prov.empty and "risky_count" in by_prov.columns else 0
    total_universe = int(by_prov["total_entities"].sum()) if not by_prov.empty else 0
    avg_risk_rate  = total_risky / max(total_universe, 1)

    pm1, pm2, pm3 = st.columns(3)
    pm1.metric("Universe Entities", f"{total_ents:,}",
               help="All active non-government FED recipients in the database.")
    pm2.metric("Risky in Universe", f"{total_risky:,}",
               help="Entities triggering at least one of the 10 zombie rules across the full universe.")
    pm3.metric("Universe Risk Rate", f"{avg_risk_rate*100:.1f}%",
               help="Share of the funded universe triggering at least one rule. "
                    "Compare to the risk rate in your flagged set to judge concentration.")

    risk_dist = stats.get("risk_distribution", pd.DataFrame())
    col_chart, col_prov = st.columns(2)

    with col_chart:
        st.markdown("**Risk Distribution — Full Universe**")
        if not risk_dist.empty and "risk_label" in risk_dist.columns:
            chart_df = risk_dist.rename(columns={"risk_label": "Risk Level", "count": "Count"})
            st.altair_chart(
                _labeled_bar_chart(chart_df, "Risk Level", "Count",
                                   x_title="Risk Level", y_title="Entity Count",
                                   colour="#E45756"),
                use_container_width=True,
            )

    with col_prov:
        st.markdown("**By Province**")
        if not by_prov.empty:
            disp = _fmt_dollar(_fmt_pct(by_prov.copy(),
                               ["risk_rate", "avg_gov_dependency", "avg_program_ratio"]),
                               ["total_funding"])
            st.dataframe(disp, use_container_width=True, hide_index=True)

    col_type, col_band = st.columns(2)

    with col_type:
        st.markdown("**By Entity Type**")
        by_entity_type = stats.get("by_entity_type", pd.DataFrame())
        if not by_entity_type.empty:
            disp = _fmt_dollar(_fmt_pct(by_entity_type.copy(),
                               ["risk_rate", "avg_gov_dependency", "avg_program_ratio"]),
                               ["total_funding"])
            st.dataframe(disp, use_container_width=True, hide_index=True)

    with col_band:
        st.markdown("**By Funding Band**")
        by_funding_band = stats.get("by_funding_band", pd.DataFrame())
        if not by_funding_band.empty:
            disp = _fmt_dollar(_fmt_pct(by_funding_band.copy(),
                               ["risk_rate", "avg_gov_dependency", "avg_program_ratio"]),
                               ["total_funding"])
            st.dataframe(disp, use_container_width=True, hide_index=True)

    st.divider()
    st.subheader("Risk by Department")
    if not dept_df.empty:
        disp_dept = _fmt_dollar(_fmt_pct(dept_df.copy(),
                               ["risk_rate", "avg_gov_dependency", "avg_program_ratio"]),
                               ["total_funding"])
        st.dataframe(disp_dept, use_container_width=True, hide_index=True)
    else:
        st.info("No department data available.")

    top_ents_df = stats.get("top_entities", pd.DataFrame())
    if not top_ents_df.empty:
        st.divider()
        st.subheader("Top Flagged Entities in Universe")
        disp_top = _fmt_dollar(_fmt_pct(top_ents_df.copy(),
                               ["avg_gov_dependency", "avg_program_ratio"]),
                               ["fed_total", "funding_gap"])
        st.dataframe(disp_top, use_container_width=True, hide_index=True)

    # ── Next steps ────────────────────────────────────────────────────────────
    st.divider()
    st.subheader("Next Steps")
    export_col, rerun_col, _ = st.columns([1, 1, 2])
    with export_col:
        if st.button("Continue to Report", type="primary", use_container_width=True,
                     key="combined_continue_report"):
            _set_default_report_entity(batch_results)
            go_to_page("Report")
    with rerun_col:
        if st.button("Re-run Analysis", use_container_width=True, key="combined_rerun"):
            st.session_state.pop("batch_analysis_results", None)
            st.session_state.pop("portfolio_results", None)
            st.rerun()
