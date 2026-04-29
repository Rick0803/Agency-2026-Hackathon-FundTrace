# views/report.py
# Report page — deterministic reporting first, optional LLM prose second.

import json
from dataclasses import asdict, is_dataclass

import pandas as pd
import streamlit as st

from agent.orchestrator import (
    run_investigation,
    run_narrative_report_from_analysis,
)
from views.general import (
    SEVERITY_COLOUR,
    go_to_page,
    render_selected_entity_banner,
    selected_entity_query,
    selected_entity_bn,
    selected_entity_name,
)


def _to_plain(value):
    """Recursively convert dataclasses and pandas-ish values to JSON-safe objects."""
    if is_dataclass(value):
        return _to_plain(asdict(value))
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


def _money(value) -> str:
    try:
        return f"${float(value):,.0f}"
    except (TypeError, ValueError):
        return "-"


def _pct(value) -> str:
    try:
        return f"{float(value) * 100:.1f}%"
    except (TypeError, ValueError):
        return "-"


def _compact(value) -> str:
    return "-" if value in (None, "", []) else str(value)


def _analysis_results() -> list:
    results = list(st.session_state.get("batch_analysis_results") or [])
    single = st.session_state.get("report_entity_analysis")
    if single:
        single_bn = _to_plain(single).get("bn_root")
        existing_bns = {_to_plain(r).get("bn_root") for r in results}
        if single_bn not in existing_bns:
            results.append(single)
    return results


def _matching_analysis_result():
    results = _analysis_results()
    if not results:
        return None

    selected_bn = selected_entity_bn()
    selected_name = selected_entity_name()
    if selected_bn or selected_name:
        for result in results:
            data = _to_plain(result)
            if selected_bn and data.get("bn_root") == selected_bn:
                return result
            if selected_name and data.get("canonical_name") == selected_name:
                return result
    return results[0]


def _entity_options(results: list) -> list[str]:
    return [
        f"{_to_plain(r).get('canonical_name', 'Unknown')} ({_to_plain(r).get('bn_root', '-')})"
        for r in results
    ]


def _flatten_for_csv(data: dict) -> dict:
    return {
        "canonical_name": data.get("canonical_name"),
        "bn_root": data.get("bn_root"),
        "entity_type": data.get("entity_type"),
        "province": data.get("province"),
        "overall_risk": data.get("overall_risk"),
        "confidence": data.get("confidence"),
        "ghost_score": data.get("ghost_score"),
        "fed_total": data.get("fed_total"),
        "funding_gap": data.get("funding_gap"),
        "avg_gov_dependency": data.get("avg_gov_dependency"),
        "avg_program_ratio": data.get("avg_program_ratio"),
        "total_employees": data.get("total_employees"),
        "transfers_out_total": data.get("transfers_out_total"),
        "total_compensation": data.get("total_compensation"),
        "first_grant_date": data.get("first_grant_date"),
        "last_grant_date": data.get("last_grant_date"),
        "last_cra_filing": data.get("last_cra_filing"),
        "cra_years": data.get("cra_years"),
        "persistence": data.get("persistence"),
        "has_cra_data": data.get("has_cra_data"),
        "has_fed_data": data.get("has_fed_data"),
        "top_flags": "; ".join(data.get("top_flags") or []),
        "analysis_notes": data.get("analysis_notes"),
    }


def _signal_rows(data: dict) -> pd.DataFrame:
    rows = []
    for signal in data.get("signals") or []:
        signal = _to_plain(signal)
        value = signal.get("value")
        threshold = signal.get("threshold")
        rows.append({
            "Signal": signal.get("label", signal.get("dimension", "")),
            "Severity": signal.get("severity", ""),
            "Flagged": "Yes" if signal.get("flagged") else "No",
            "Value": f"{float(value):.3f}" if isinstance(value, (int, float)) else _compact(value),
            "Threshold": f"{float(threshold):.3f}" if isinstance(threshold, (int, float)) else _compact(threshold),
            "Interpretation": signal.get("interpretation", ""),
        })
    return pd.DataFrame(rows)


def _render_entity_selector() -> object:
    results = _analysis_results()
    if not results:
        return None

    current = _matching_analysis_result()
    options = _entity_options(results)
    current_label = None
    if current:
        current_data = _to_plain(current)
        current_label = f"{current_data.get('canonical_name', 'Unknown')} ({current_data.get('bn_root', '-')})"
    index = options.index(current_label) if current_label in options else 0

    selected_label = st.selectbox("Report entity", options, index=index)
    return results[options.index(selected_label)]


def _render_run_analysis_prompt() -> None:
    st.info(
        "No computed entity analysis is available yet. Run Batch Analysis from the Analyze page first."
    )
    if st.button("Go to Analyze", type="primary"):
        go_to_page("Analyze")


def _render_risk_card(result) -> None:
    data = _to_plain(result)
    icon = SEVERITY_COLOUR.get(data.get("overall_risk"), "⚪")

    st.subheader(f"{icon} {data.get('canonical_name', 'Unknown')} — {data.get('overall_risk', 'UNKNOWN')} RISK")
    st.caption(
        f"BN: {data.get('bn_root') or '-'} | "
        f"{data.get('entity_type') or '-'} | "
        f"{data.get('province') or '-'} | "
        f"Confidence: {data.get('confidence') or '-'}"
    )

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Ghost Score", f"{float(data.get('ghost_score') or 0):.3f}")
    m2.metric("Federal Funding", _money(data.get("fed_total")))
    m3.metric("Funding Gap", _money(data.get("funding_gap")))
    m4.metric("CRA Years", data.get("cra_years", 0))

    s1, s2, s3, s4 = st.columns(4)
    s1.metric("Gov Revenue Share", _pct(data.get("avg_gov_dependency")))
    s2.metric("Program Spend Share", _pct(data.get("avg_program_ratio")))
    s3.metric("Employees", f"{int(data.get('total_employees') or 0):,}")
    s4.metric("Transfers Out", _money(data.get("transfers_out_total")))

    st.markdown("**Summary**")
    st.write(data.get("explanation") or "No explanation generated.")

    st.markdown("**Timeline and Coverage**")
    t1, t2, t3, t4 = st.columns(4)
    t1.metric("First Grant", _compact(data.get("first_grant_date")))
    t2.metric("Last Grant", _compact(data.get("last_grant_date")))
    t3.metric("Last CRA Filing", _compact(data.get("last_cra_filing")))
    t4.metric("Persistence", _compact(data.get("persistence")))

    coverage = []
    coverage.append("CRA data found" if data.get("has_cra_data") else "CRA data missing")
    coverage.append("FED data found" if data.get("has_fed_data") else "FED data missing")
    st.caption(" | ".join(coverage))
    if data.get("analysis_notes"):
        st.warning(data["analysis_notes"])

    st.markdown("**Signal Breakdown**")
    signals_df = _signal_rows(data)
    if signals_df.empty:
        st.info("No signal rows were returned for this entity.")
    else:
        st.dataframe(signals_df, use_container_width=True, hide_index=True)

    st.markdown("**Exports**")
    json_data = json.dumps(data, indent=2, default=str)
    csv_data = pd.DataFrame([_flatten_for_csv(data)]).to_csv(index=False)
    signal_csv = signals_df.to_csv(index=False) if not signals_df.empty else ""

    e1, e2, e3 = st.columns(3)
    e1.download_button(
        "Download JSON",
        data=json_data,
        file_name=f"risk-{data.get('bn_root') or 'entity'}.json",
        mime="application/json",
        use_container_width=True,
    )
    e2.download_button(
        "Download Summary CSV",
        data=csv_data,
        file_name=f"risk-{data.get('bn_root') or 'entity'}.csv",
        mime="text/csv",
        use_container_width=True,
    )
    e3.download_button(
        "Download Signals CSV",
        data=signal_csv,
        file_name=f"risk-signals-{data.get('bn_root') or 'entity'}.csv",
        mime="text/csv",
        disabled=signals_df.empty,
        use_container_width=True,
    )


def _render_narrative_tab(result) -> None:
    if not result:
        _render_run_analysis_prompt()
        return

    data = _to_plain(result)
    st.caption("Single LLM call from the computed EntityAnalysisResult. No database fetching or tool loop.")

    if st.button("Generate Narrative Brief", type="primary"):
        with st.spinner("Writing narrative from structured analysis..."):
            brief = run_narrative_report_from_analysis(data)
        st.session_state["narrative_brief"] = brief
        st.session_state["narrative_brief_bn"] = data.get("bn_root")

    brief = st.session_state.get("narrative_brief")
    if not brief or st.session_state.get("narrative_brief_bn") != data.get("bn_root"):
        return

    brief_data = _to_plain(brief)
    icon = SEVERITY_COLOUR.get(brief_data.get("overall_risk"), "⚪")
    st.subheader(f"{icon} {brief_data.get('entity', 'Unknown')} — {brief_data.get('overall_risk', 'UNKNOWN')} RISK")
    st.caption(f"Confidence: {brief_data.get('confidence', '-')}")
    st.write(brief_data.get("summary", ""))

    col_sig, col_actions = st.columns([2, 1])
    with col_sig:
        st.markdown("**Evidence Signals**")
        for signal in brief_data.get("signals") or []:
            colour = SEVERITY_COLOUR.get(signal.get("severity"), "⚪")
            st.markdown(f"**{colour} {signal.get('label', '')}** `{signal.get('severity', '')}`")
            st.caption(signal.get("evidence", ""))
    with col_actions:
        st.markdown("**Recommended Actions**")
        for i, action in enumerate(brief_data.get("recommended_actions") or [], 1):
            st.markdown(f"{i}. {action}")
        if brief_data.get("limitations"):
            st.markdown("**Limitations**")
            st.caption(brief_data["limitations"])

    st.download_button(
        "Download Narrative JSON",
        data=json.dumps(brief_data, indent=2, default=str),
        file_name=f"risk-brief-{data.get('bn_root') or 'entity'}.json",
        mime="application/json",
    )


def _format_report_df(df: pd.DataFrame) -> pd.DataFrame:
    disp = df.copy()
    for col in ["avg_gov_dependency", "avg_program_ratio", "risk_rate"]:
        if col in disp.columns:
            disp[col] = disp[col].map(lambda x: _pct(x))
    for col in ["fed_total", "funding_gap", "total_funding"]:
        if col in disp.columns:
            disp[col] = disp[col].map(lambda x: _money(x))
    return disp


def _render_portfolio_tab() -> None:
    portfolio_result = st.session_state.get("portfolio_results")
    if not portfolio_result:
        st.info("No portfolio report data yet. Run Portfolio Analysis in the Analyze page first.")
        return

    stats = portfolio_result.get("portfolio", {})
    dept_df = portfolio_result.get("departments", pd.DataFrame())
    alerts_df = stats.get("alerts", pd.DataFrame())

    st.subheader("Department Risk Report")
    if dept_df.empty:
        st.info("No department data available.")
    else:
        st.dataframe(_format_report_df(dept_df), use_container_width=True, hide_index=True)
        st.download_button(
            "Download Department CSV",
            data=dept_df.to_csv(index=False),
            file_name="department-risk-report.csv",
            mime="text/csv",
        )

    st.divider()
    st.subheader("Early-Warning Alerts")
    st.caption("Active organizations with average government dependency above 80%.")
    if alerts_df.empty:
        st.info("No early-warning candidates were returned.")
    else:
        st.dataframe(_format_report_df(alerts_df), use_container_width=True, hide_index=True)
        st.download_button(
            "Download Alerts CSV",
            data=alerts_df.to_csv(index=False),
            file_name="early-warning-alerts.csv",
            mime="text/csv",
        )


def _render_legacy_deep_investigation() -> None:
    st.warning(
        "This is the older full agent loop. It fetches and computes through the LLM, "
        "so it is slower and more expensive than the structured report tabs."
    )
    default_query = selected_entity_query("Investigate")
    query = st.text_area(
        "Query",
        value=default_query,
        placeholder="e.g. Investigate GITES JEUNESSE INC for ghost capacity",
        height=80,
        key=f"legacy_report_query_{selected_entity_bn() or selected_entity_name()}",
    )

    if st.button("Run Deep Investigation", type="primary") and query.strip():
        with st.spinner("Agent is investigating..."):
            brief = run_investigation(query.strip())
        st.session_state["legacy_risk_brief"] = brief

    brief = st.session_state.get("legacy_risk_brief")
    if not brief:
        return

    data = _to_plain(brief)
    icon = SEVERITY_COLOUR.get(data.get("overall_risk"), "⚪")
    st.subheader(f"{icon} {data.get('entity', 'Unknown')} — {data.get('overall_risk', 'UNKNOWN')} RISK")
    st.caption(f"Confidence: {data.get('confidence', '-')}")
    st.write(data.get("summary", ""))
    st.download_button(
        "Download Deep Investigation JSON",
        data=json.dumps(data, indent=2, default=str),
        file_name=f"deep-risk-brief-{data.get('entity', 'entity')[:30].replace(' ', '-')}.json",
        mime="application/json",
    )


def render_report() -> None:
    st.title("Public Funding Risk Intelligence Agent")
    st.subheader("Report Mode")
    st.caption("Render structured risk reports from deterministic analysis, with optional LLM-written narrative.")
    render_selected_entity_banner()

    tab_micro, tab_narrative, tab_macro, tab_legacy = st.tabs([
        "Entity Risk Card",
        "Narrative Brief",
        "Portfolio Reports",
        "Deep Investigation",
    ])

    with tab_micro:
        result = _render_entity_selector()
        if result:
            _render_risk_card(result)
        else:
            _render_run_analysis_prompt()

    with tab_narrative:
        _render_narrative_tab(_matching_analysis_result())

    with tab_macro:
        _render_portfolio_tab()

    with tab_legacy:
        _render_legacy_deep_investigation()
