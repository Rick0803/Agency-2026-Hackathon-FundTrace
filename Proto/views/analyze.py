# views/analyze.py
# Analyze page — deterministic ghost capacity scoring, no LLM.

import streamlit as st
import pandas as pd
import altair as alt
from dataclasses import asdict

from agent.orchestrator import (
    run_entity_batch_analysis,
    run_portfolio_analysis,
)
from views.general import (
    SEVERITY_COLOUR,
    go_to_page,
    set_selected_entity,
    render_selected_entity_banner,
    selected_entity_query,
    selected_entity_bn,
    selected_entity_name,
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

def render_analyze() -> None:
    st.title("Public Funding Risk Intelligence Agent")
    st.subheader("Analysis — Deterministic, no LLM")
    st.caption(
        "Two modes: analyze your flagged entities as a batch, "
        "or explore the full funded universe as a portfolio."
    )

    tab_batch, tab_portfolio = st.tabs(["Batch Analysis", "Portfolio Dashboard"])

    with tab_batch:
        _render_batch_analysis()

    with tab_portfolio:
        _render_portfolio_dashboard()


# ─── Tab 1: Batch Analysis ─────────────────────────────────────────────────────

def _render_batch_analysis() -> None:
    flagged: list = st.session_state.get("flagged_list", [])

    if not flagged:
        st.info(
            "Your flagged list is empty. "
            "Go to **Fetch** and use Way 1 or Way 2 results to flag organizations."
        )
        return

    st.write(f"**{len(flagged)} organization(s)** in your flagged list")

    # Show flagged table
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

    # Run button
    if st.button("Run Batch Analysis", type="primary", key="run_batch"):
        with st.spinner(f"Analyzing {len(flagged)} organization(s)…"):
            results = run_entity_batch_analysis(flagged)
        st.session_state["batch_analysis_results"] = results
        st.rerun()

    # Persist and display results
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

    # Ranked results table
    table_rows = []
    for r in sorted(results, key=lambda x: x.ghost_score, reverse=True):
        colour = SEVERITY_COLOUR.get(r.overall_risk, "⚪")
        table_rows.append({
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
            "Explanation":        r.explanation[:120] + ("…" if len(r.explanation) > 120 else ""),
        })

    st.dataframe(pd.DataFrame(table_rows), use_container_width=True, hide_index=True)

    # Drill-down
    st.divider()
    st.subheader("Drill-down")
    names = [r.canonical_name for r in results]
    selected_name = st.selectbox("Select organization for drill-down", names, key="batch_drilldown")
    selected_result = next((r for r in results if r.canonical_name == selected_name), None)

    if selected_result:
        dc1, dc2 = st.columns(2)
        with dc1:
            st.markdown(f"**Persistence:** {selected_result.persistence}")
            st.markdown(f"**Has CRA Data:** {'Yes' if selected_result.has_cra_data else 'No'}")
            st.markdown(f"**Has FED Data:** {'Yes' if selected_result.has_fed_data else 'No'}")
            if selected_result.analysis_notes:
                st.caption(f"Notes: {selected_result.analysis_notes}")
        with dc2:
            st.markdown(f"**First Grant:** {selected_result.first_grant_date or '—'}")
            st.markdown(f"**Last Grant:** {selected_result.last_grant_date or '—'}")
            st.markdown(f"**Last CRA Filing:** {selected_result.last_cra_filing or '—'}")

        st.markdown("**Signal Breakdown**")
        for sig in selected_result.signals:
            colour  = SEVERITY_COLOUR.get(sig.severity, "⚪")
            flagged = "✓ Flagged" if sig.flagged else "✗ Not flagged"
            st.markdown(f"{colour} **{sig.label}** — {flagged} (value: {sig.value:.3f}, threshold: {sig.threshold})")
            st.caption(sig.interpretation)

        btn_col1, btn_col2 = st.columns(2)
        with btn_col1:
            if st.button("Open in Report", type="primary", key="batch_open_report"):
                set_selected_entity({
                    "canonical_name":  selected_result.canonical_name,
                    "bn_root":         selected_result.bn_root,
                    "entity_type":     selected_result.entity_type,
                    "province":        selected_result.province,
                    "dataset_sources": ["cra" if selected_result.has_cra_data else None,
                                        "fed" if selected_result.has_fed_data else None],
                })
                go_to_page("Report")
        with btn_col2:
            if st.button("Clear Results", key="batch_clear"):
                st.session_state.pop("batch_analysis_results", None)
                st.rerun()


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

        st.markdown("**Select entity from top list to open in Report**")
        entity_names_top = list(top_ents_df["canonical_name"]) if "canonical_name" in top_ents_df.columns else []
        if entity_names_top:
            sel_top = st.selectbox("Organization", entity_names_top, key="portfolio_top_select")
            sel_row = top_ents_df[top_ents_df["canonical_name"] == sel_top]
            if st.button("Open in Report", type="primary", key="portfolio_open_report"):
                if not sel_row.empty:
                    row = sel_row.iloc[0].to_dict()
                    set_selected_entity({
                        "canonical_name":  row.get("canonical_name", ""),
                        "bn_root":         row.get("bn_root", ""),
                        "entity_type":     row.get("entity_type", ""),
                        "province":        row.get("province", ""),
                        "dataset_sources": ["fed"],
                    })
                    go_to_page("Report")
