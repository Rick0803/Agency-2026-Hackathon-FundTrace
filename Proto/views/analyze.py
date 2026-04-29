# views/analyze.py
# Analyze page — deterministic ghost capacity scoring, no LLM.

import json
import streamlit as st
import pandas as pd
import altair as alt
from dataclasses import asdict, is_dataclass

from agent.orchestrator import (
    run_entity_batch_analysis,
    run_portfolio_analysis,
)
from views.general import (
    SEVERITY_COLOUR,
    go_to_page,
    set_selected_entity,
)


# ─── Local chart helper (mirrors _labeled_bar_chart in fetch.py) ───────────────

def _labeled_bar_chart(df: pd.DataFrame, x_col: str, y_col: str,
                        x_title: str = "", y_title: str = "",
                        colour: str = "#4C78A8") -> alt.Chart:
    """Altair bar chart with data labels on top of each bar."""
    base = alt.Chart(df).encode(
        x=alt.X(f"{x_col}:N", title=x_title, sort=None),
        y=alt.Y(f"{y_col}:Q", title=y_title),
    )
    bars = base.mark_bar(color=colour)
    labels = base.mark_text(dy=-6, fontSize=11).encode(
        text=alt.Text(f"{y_col}:Q", format=".2f")
    )
    return (bars + labels).properties(height=280)


# ─── Public entry point ────────────────────────────────────────────────────────

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


def _render_export_prompt(kind: str) -> None:
    st.divider()
    st.subheader("Export findings")
    st.write("The analysis is complete. Continue to Report to render risk cards, narrative briefs, and downloadable outputs.")

    export_col, clear_col = st.columns([1, 1])
    with export_col:
        if st.button("Continue to Report", type="primary", use_container_width=True, key=f"{kind}_continue_report"):
            if kind == "batch":
                _set_default_report_entity(st.session_state.get("batch_analysis_results") or [])
            go_to_page("Report")
    with clear_col:
        if st.button("Clear analysis results", use_container_width=True, key=f"{kind}_clear_results"):
            if kind == "batch":
                st.session_state.pop("batch_analysis_results", None)
            else:
                st.session_state.pop("portfolio_results", None)
            st.rerun()


def render_analyze() -> None:
    st.title("Public Funding Risk Intelligence Agent")
    st.subheader("Analysis — Deterministic, no LLM")
    st.caption("Choose the analysis to run on the curated workflow, then export the completed findings to Report.")

    flagged: list = st.session_state.get("flagged_list", [])
    if not flagged:
        st.info("Your flagged list is empty. Go to Fetch and add organizations before analysis.")
        return

    st.markdown("**Current flagged queue**")
    st.caption(f"{len(flagged)} organization(s) are ready from the Flagged step.")

    st.subheader("Purpose of analysis")
    st.write(
        "This step elevates the flagged entities from a review list into structured findings. "
        "The goal is to test whether the selected organizations show stronger evidence of ghost-capacity risk, "
        "then prepare the results for reporting."
    )
    st.write(
        "Analysis is conducted with deterministic scoring logic, not free-form LLM judgment. "
        "The app combines funding records, CRA filing patterns, program spending, employee signals, "
        "government dependency, transfers, and rule-based flags into comparable risk outputs."
    )

    st.subheader("Analysis methods")
    method_cols = st.columns(2)
    method_cols[0].markdown("**Batch Entity Risk Analysis**")
    method_cols[0].write(
        "Scores each selected flagged entity, ranks the results, and highlights the strongest evidence "
        "for entity-level review."
    )
    method_cols[1].markdown("**Portfolio Pattern Analysis**")
    method_cols[1].write(
        "Looks across the broader funded universe to summarize aggregate risk patterns by geography, "
        "entity type, funding band, and department."
    )

    options = {
        "Batch Entity Risk Analysis": (
            "Runs the deterministic ghost-capacity pipeline for every organization in the Flagged List."
        ),
        "Portfolio Pattern Analysis": (
            "Scans the broader funded universe to summarize aggregate risk patterns by province, entity type, funding band, and department."
        ),
    }
    selected_analysis = st.radio(
        "Analysis type",
        list(options.keys()),
        horizontal=True,
        key="selected_analysis_type",
    )
    st.info(options[selected_analysis])

    if selected_analysis == "Batch Entity Risk Analysis":
        _render_batch_analysis()
    else:
        _render_portfolio_dashboard()


# ─── Tab 1: Batch Analysis ─────────────────────────────────────────────────────

def _render_batch_analysis() -> None:
    flagged: list = st.session_state.get("flagged_list", [])

    st.write(f"**{len(flagged)} organization(s)** will be analyzed from your Flagged List.")

    flag_rows = []
    for ent in flagged:
        flag_rows.append({
            "Organization":    ent.get("canonical_name", ""),
            "BN":              ent.get("bn_root", ""),
            "Province":        ent.get("province", ""),
            "Fed Total ($)":   f"${float(ent.get('fed_total', 0)):,.0f}",
            "Rules Triggered": int(ent.get("rules_triggered", 0)),
        })
    st.dataframe(pd.DataFrame(flag_rows), use_container_width=True, hide_index=True)

    if st.button("Run Batch Analysis", type="primary", key="run_batch"):
        with st.spinner(f"Analyzing {len(flagged)} organization(s)…"):
            results = run_entity_batch_analysis(flagged)
        st.session_state["batch_analysis_results"] = results
        st.rerun()

    results = st.session_state.get("batch_analysis_results")
    if not results:
        return

    st.divider()
    st.subheader("Batch Results")

    # Summary metrics
    critical_count = sum(1 for r in results if r.overall_risk == "CRITICAL")
    high_count     = sum(1 for r in results if r.overall_risk == "HIGH")
    avg_ghost      = sum(r.ghost_score for r in results) / max(len(results), 1)

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Analyzed",        len(results))
    m2.metric("CRITICAL",        critical_count)
    m3.metric("HIGH",            high_count)
    m4.metric("Avg Ghost Score", f"{avg_ghost:.3f}")

    st.markdown("**Ranked Findings Preview**")
    st.dataframe(_batch_results_df(results), use_container_width=True, hide_index=True)

    top_result = max(results, key=lambda x: x.ghost_score)
    st.markdown("**Highest-risk finding**")
    h1, h2, h3 = st.columns(3)
    h1.metric("Organization", top_result.canonical_name)
    h2.metric("Risk", top_result.overall_risk)
    h3.metric("Ghost Score", f"{top_result.ghost_score:.3f}")
    st.caption(top_result.explanation)

    batch_json = json.dumps(_to_plain(results), indent=2, default=str)
    batch_csv = _batch_results_df(results).to_csv(index=False)
    dl1, dl2, _ = st.columns([1, 1, 2])
    dl1.download_button(
        "Download Preview JSON",
        data=batch_json,
        file_name="batch-analysis-preview.json",
        mime="application/json",
        use_container_width=True,
    )
    dl2.download_button(
        "Download Preview CSV",
        data=batch_csv,
        file_name="batch-analysis-preview.csv",
        mime="text/csv",
        use_container_width=True,
    )

    _render_export_prompt("batch")


# ─── Tab 2: Portfolio Dashboard ────────────────────────────────────────────────

def _render_portfolio_dashboard() -> None:
    min_fed = st.number_input(
        "Min federal funding ($)",
        min_value=0,
        value=0,
        step=10_000,
        key="portfolio_min_fed",
    )

    if st.button("Run Portfolio Analysis", type="primary", key="run_portfolio"):
        with st.spinner("Loading full funded universe — this may take 30–60 seconds…"):
            portfolio_result = run_portfolio_analysis(min_fed_total=float(min_fed))
        st.session_state["portfolio_results"] = portfolio_result
        st.rerun()

    portfolio_result = st.session_state.get("portfolio_results")
    if not portfolio_result:
        return

    stats      = portfolio_result.get("portfolio", {})
    dept_df    = portfolio_result.get("departments", pd.DataFrame())
    total_ents = portfolio_result.get("total_entities", 0)

    st.divider()
    st.subheader("Portfolio Overview")

    top_ents_df = stats.get("top_entities", pd.DataFrame())
    risk_dist   = stats.get("risk_distribution", pd.DataFrame())

    total_flagged = 0
    avg_risk_rate = 0.0
    by_prov       = stats.get("by_province", pd.DataFrame())
    if not by_prov.empty and "risky_count" in by_prov.columns:
        total_flagged = int(by_prov["risky_count"].sum())
        total_in_prov = int(by_prov["total_entities"].sum())
        avg_risk_rate = total_flagged / max(total_in_prov, 1)

    pm1, pm2, pm3 = st.columns(3)
    pm1.metric("Total Entities",    f"{total_ents:,}")
    pm2.metric("Flagged (≥1 rule)", f"{total_flagged:,}")
    pm3.metric("Avg Risk Rate",     f"{avg_risk_rate*100:.1f}%")

    # Risk distribution chart
    if not risk_dist.empty and "risk_label" in risk_dist.columns:
        st.markdown("**Risk Distribution**")
        chart_df = risk_dist.rename(columns={"risk_label": "Risk Level", "count": "Count"})
        chart = _labeled_bar_chart(chart_df, "Risk Level", "Count",
                                   x_title="Risk Level", y_title="Entity Count",
                                   colour="#E45756")
        st.altair_chart(chart, use_container_width=True)

    st.divider()

    # Province and entity type
    col_prov, col_type = st.columns(2)

    with col_prov:
        st.markdown("**By Province**")
        by_province = stats.get("by_province", pd.DataFrame())
        if not by_province.empty:
            disp = by_province.copy()
            disp["risk_rate"]         = disp["risk_rate"].map(lambda x: f"{x*100:.1f}%")
            disp["avg_gov_dependency"]= disp["avg_gov_dependency"].map(lambda x: f"{x*100:.1f}%")
            disp["avg_program_ratio"] = disp["avg_program_ratio"].map(lambda x: f"{x*100:.1f}%")
            disp["total_funding"]     = disp["total_funding"].map(lambda x: f"${x:,.0f}")
            st.dataframe(disp, use_container_width=True, hide_index=True)

    with col_type:
        st.markdown("**By Entity Type**")
        by_entity_type = stats.get("by_entity_type", pd.DataFrame())
        if not by_entity_type.empty:
            disp = by_entity_type.copy()
            disp["risk_rate"]         = disp["risk_rate"].map(lambda x: f"{x*100:.1f}%")
            disp["avg_gov_dependency"]= disp["avg_gov_dependency"].map(lambda x: f"{x*100:.1f}%")
            disp["avg_program_ratio"] = disp["avg_program_ratio"].map(lambda x: f"{x*100:.1f}%")
            disp["total_funding"]     = disp["total_funding"].map(lambda x: f"${x:,.0f}")
            st.dataframe(disp, use_container_width=True, hide_index=True)

    # By funding band
    st.markdown("**By Funding Band**")
    by_funding_band = stats.get("by_funding_band", pd.DataFrame())
    if not by_funding_band.empty:
        disp = by_funding_band.copy()
        disp["risk_rate"]         = disp["risk_rate"].map(lambda x: f"{x*100:.1f}%")
        disp["avg_gov_dependency"]= disp["avg_gov_dependency"].map(lambda x: f"{x*100:.1f}%")
        disp["avg_program_ratio"] = disp["avg_program_ratio"].map(lambda x: f"{x*100:.1f}%")
        disp["total_funding"]     = disp["total_funding"].map(lambda x: f"${x:,.0f}")
        st.dataframe(disp, use_container_width=True, hide_index=True)

    # Departments section
    st.divider()
    st.subheader("Risk by Department")
    if not dept_df.empty:
        disp_dept = dept_df.copy()
        if "risk_rate" in disp_dept.columns:
            disp_dept["risk_rate"] = disp_dept["risk_rate"].map(lambda x: f"{float(x)*100:.1f}%")
        if "total_funding" in disp_dept.columns:
            disp_dept["total_funding"] = disp_dept["total_funding"].map(lambda x: f"${float(x):,.0f}")
        if "avg_gov_dependency" in disp_dept.columns:
            disp_dept["avg_gov_dependency"] = disp_dept["avg_gov_dependency"].map(
                lambda x: f"{float(x)*100:.1f}%" if x is not None else "—"
            )
        if "avg_program_ratio" in disp_dept.columns:
            disp_dept["avg_program_ratio"] = disp_dept["avg_program_ratio"].map(
                lambda x: f"{float(x)*100:.1f}%" if x is not None else "—"
            )
        st.dataframe(disp_dept, use_container_width=True, hide_index=True)
    else:
        st.info("No department data available.")

    # Top entities
    st.divider()
    st.subheader("Top Flagged Entities")
    if not top_ents_df.empty:
        disp_top = top_ents_df.copy()
        for col in ["avg_gov_dependency", "avg_program_ratio"]:
            if col in disp_top.columns:
                disp_top[col] = disp_top[col].map(lambda x: f"{float(x)*100:.1f}%")
        for col in ["fed_total", "funding_gap"]:
            if col in disp_top.columns:
                disp_top[col] = disp_top[col].map(lambda x: f"${float(x):,.0f}")
        st.dataframe(disp_top, use_container_width=True, hide_index=True)

    portfolio_json = json.dumps(_to_plain(portfolio_result), indent=2, default=str)
    dl1, _ = st.columns([1, 3])
    dl1.download_button(
        "Download Preview JSON",
        data=portfolio_json,
        file_name="portfolio-analysis-preview.json",
        mime="application/json",
        use_container_width=True,
    )

    _render_export_prompt("portfolio")
