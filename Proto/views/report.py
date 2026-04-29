# views/report.py
# Report page — deterministic reporting first, optional LLM prose second.

import json
from dataclasses import asdict, is_dataclass

import pandas as pd
import streamlit as st
import altair as alt

from agent.orchestrator import (
    run_narrative_report_from_analysis,
    run_business_report,
)
from views.general import (
    SEVERITY_COLOUR,
    go_to_page,
    reset_workflow,
    selected_entity_bn,
    selected_entity_name,
)


AGGREGATE_REPORT_LABEL = "All analyzed entities (aggregate)"


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


def _float_value(value, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


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


def _results_dataframe(results: list) -> pd.DataFrame:
    return pd.DataFrame([_flatten_for_csv(_to_plain(result)) for result in results])


def _aggregate_signal_rows(results: list) -> pd.DataFrame:
    rows = []
    for result in results:
        data = _to_plain(result)
        for signal in data.get("signals") or []:
            signal = _to_plain(signal)
            rows.append({
                "Organization": data.get("canonical_name", "Unknown"),
                "BN": data.get("bn_root", "-"),
                "Signal": signal.get("label", signal.get("dimension", "")),
                "Severity": signal.get("severity", ""),
                "Flagged": "Yes" if signal.get("flagged") else "No",
                "Value": f"{_float_value(signal.get('value')):.3f}",
                "Threshold": f"{_float_value(signal.get('threshold')):.3f}",
                "Interpretation": signal.get("interpretation", ""),
            })
    return pd.DataFrame(rows)


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


def _signal_chart_rows(data: dict) -> pd.DataFrame:
    rows = []
    for signal in data.get("signals") or []:
        signal = _to_plain(signal)
        rows.append({
            "Signal": signal.get("label", signal.get("dimension", "")),
            "Value": _float_value(signal.get("value")),
            "Threshold": _float_value(signal.get("threshold")),
            "Severity": signal.get("severity", ""),
            "Flagged": "Flagged" if signal.get("flagged") else "Not flagged",
            "Interpretation": signal.get("interpretation", ""),
        })
    return pd.DataFrame(rows)


def _insight_lines(data: dict, signal_df: pd.DataFrame) -> list[str]:
    insights = []
    flagged = signal_df[signal_df["Flagged"] == "Flagged"] if not signal_df.empty else pd.DataFrame()
    if not flagged.empty:
        top_signals = ", ".join(flagged["Signal"].head(3).tolist())
        insights.append(f"Primary signals to review: {top_signals}.")

    gov_dependency = _float_value(data.get("avg_gov_dependency"))
    program_ratio = _float_value(data.get("avg_program_ratio"))
    funding_gap = _float_value(data.get("funding_gap"))
    employees = int(_float_value(data.get("total_employees")))

    if gov_dependency >= 0.90:
        insights.append("Government revenue dependency is above the 90% critical threshold.")
    if data.get("avg_program_ratio") is not None and program_ratio < 0.20:
        insights.append("Program spending is below 20% of expenses, which is the core delivery-capacity warning.")
    if funding_gap > 0:
        insights.append(f"Federal funding exceeds reported program spend by {_money(funding_gap)}.")
    if employees == 0:
        insights.append("No reported employees were found across the analyzed CRA years.")
    if data.get("analysis_notes"):
        insights.append(str(data["analysis_notes"]))

    if not insights:
        insights.append("No single signal dominates; use the plots below to compare the profile against thresholds.")
    return insights[:5]


def _bar_with_labels(df: pd.DataFrame, x_col: str, y_col: str, label_col: str,
                     color: str, height: int = 260) -> alt.Chart:
    base = alt.Chart(df).encode(
        x=alt.X(f"{x_col}:Q", title=None),
        y=alt.Y(f"{y_col}:N", sort="-x", title=None),
        tooltip=[y_col, label_col],
    )
    bars = base.mark_bar(color=color, cornerRadiusEnd=3)
    labels = base.mark_text(align="right", dx=-6, fontSize=11, color="white").encode(
        text=alt.Text(f"{label_col}:N")
    )
    return (bars + labels).properties(height=height)


def _render_entity_selector() -> object:
    results = _analysis_results()
    if not results:
        return None

    entity_options = _entity_options(results)
    options = [AGGREGATE_REPORT_LABEL] + entity_options

    selected_label = st.selectbox("Report scope", options, index=0)
    if selected_label == AGGREGATE_REPORT_LABEL:
        return results
    return results[entity_options.index(selected_label)]


def _render_run_analysis_prompt() -> None:
    st.info(
        "No computed entity analysis is available yet. Run Batch Analysis from the Analyze page first."
    )
    if st.button("Go to Analyze", type="primary"):
        go_to_page("Analyze")


def _build_narrative_brief_prompt(data: dict) -> str:
    return (
        "You are a government accountability analyst writing a short entity narrative from structured evidence only. "
        f"Entity analysis: {json.dumps(_to_plain(data), default=str)}. "
        "Write 2 short paragraphs. Explain why this entity stands out, cite the main signals, and suggest the next review action. "
        "Do not invent numbers or new facts."
    )


def _narrative_brief_placeholder(data: dict) -> dict:
    signals = [s for s in (_to_plain(data).get("signals") or []) if _to_plain(s).get("flagged")]
    top_signal_labels = [
        _to_plain(signal).get("label", _to_plain(signal).get("dimension", ""))
        for signal in signals[:3]
    ]
    top_signals = ", ".join(top_signal_labels) if top_signal_labels else "no dominant signal cluster"
    summary = (
        f"{data.get('canonical_name', 'This organization')} stands out because its profile combines "
        f"{top_signals} with a ghost score of {_float_value(data.get('ghost_score')):.3f}. "
        f"The current evidence points to a {str(data.get('overall_risk', 'UNKNOWN')).lower()}-risk case that merits document review."
    )
    actions = [
        "Verify recent operational activity against the latest public filings.",
        "Cross-check the largest funding periods against program-delivery evidence.",
    ]
    return {
        "entity": data.get("canonical_name", "Unknown"),
        "overall_risk": data.get("overall_risk", "UNKNOWN"),
        "confidence": data.get("confidence", "-"),
        "summary": summary,
        "signals": signals[:3],
        "recommended_actions": actions,
        "limitations": "Placeholder output until LLM credentials are enabled.",
    }


def _render_narrative_brief_panel(result) -> None:
    if not result:
        return

    data = _to_plain(result)
    prompt = _build_narrative_brief_prompt(data)
    cached_bn = st.session_state.get("narrative_brief_bn")
    brief = st.session_state.get("narrative_brief")
    if not brief or cached_bn != data.get("bn_root"):
        brief = _narrative_brief_placeholder(data)
        st.session_state["narrative_brief"] = brief
        st.session_state["narrative_brief_bn"] = data.get("bn_root")

    brief_data = _to_plain(brief)
    st.divider()
    st.subheader("Narrative Brief")
    st.info(brief_data.get("summary", "No narrative generated."))
    st.caption("Placeholder for a future LLM-written entity narrative.")
    if brief_data.get("recommended_actions"):
        for action in brief_data["recommended_actions"]:
            st.markdown(f"- {action}")
    st.session_state["narrative_brief_prompt"] = prompt


def _build_business_report_prompt(batch_results: list, portfolio_result: dict) -> str:
    return (
        "You are a Senior Executive Policy Analyst for the Government of Alberta writing an official Executive Briefing Note. "
        f"Entity results: {json.dumps(_to_plain(batch_results), default=str)}. "
        f"Portfolio context: {json.dumps(_to_plain(portfolio_result), default=str)}. "
        "Use only the provided data. Follow the fixed briefing-note template and do not invent facts."
    )


def _render_briefing_bullets(items) -> None:
    if isinstance(items, list) and items:
        for item in items:
            st.markdown(f"- {item}")
        return
    if items:
        st.markdown(f"- {items}")
        return
    st.markdown("- N/A based on provided data.")


def _render_aggregate_dashboard(results: list) -> None:
    df = _results_dataframe(results)
    if df.empty:
        _render_run_analysis_prompt()
        return

    for col in [
        "ghost_score", "anomaly_score", "fed_total", "funding_gap",
        "avg_gov_dependency", "avg_program_ratio", "total_employees",
        "transfers_out_total", "total_compensation", "rules_triggered",
    ]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)

    risk_order = ["CRITICAL", "HIGH", "MEDIUM", "LOW", "INSUFFICIENT DATA"]
    risk_counts = (
        df["overall_risk"]
        .fillna("INSUFFICIENT DATA")
        .value_counts()
        .reindex(risk_order, fill_value=0)
        .reset_index()
    )
    risk_counts.columns = ["Risk", "Entities"]
    risk_counts = risk_counts[risk_counts["Entities"] > 0]
    high_or_critical = int(df["overall_risk"].isin(["CRITICAL", "HIGH"]).sum())
    top_entity = df.sort_values("ghost_score", ascending=False).iloc[0]

    st.subheader("Aggregate dashboard")
    st.caption(f"{len(df):,} analyzed organization(s) summarized as one report.")

    st.divider()
    st.subheader("KPIs")
    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Entities", f"{len(df):,}")
    k2.metric("Critical / High", f"{high_or_critical:,}")
    k3.metric("Avg Ghost Score", f"{df['ghost_score'].mean():.3f}")
    k4.metric("Federal Funding", _money(df["fed_total"].sum()))

    k5, k6, k7, k8 = st.columns(4)
    k5.metric("Funding Gap", _money(df["funding_gap"].sum()))
    k6.metric("Avg Gov Revenue Share", _pct(df["avg_gov_dependency"].mean()))
    k7.metric("Avg Program Spend Share", _pct(df["avg_program_ratio"].mean()))
    k8.metric("Zero-Employee Entities", f"{int((df['total_employees'] == 0).sum()):,}")

    st.divider()
    st.subheader("Plots")
    plot_left, plot_right = st.columns(2)
    with plot_left:
        st.markdown("**Risk Distribution**")
        if risk_counts.empty:
            st.info("No risk labels were returned.")
        else:
            st.altair_chart(
                _bar_with_labels(risk_counts, "Entities", "Risk", "Entities", "#E15759"),
                use_container_width=True,
            )

    with plot_right:
        st.markdown("**Top Entities by Ghost Score**")
        top_df = df.sort_values("ghost_score", ascending=False).head(10).copy()
        top_df["Label"] = top_df["ghost_score"].map(lambda value: f"{value:.3f}")
        top_df["Organization"] = top_df["canonical_name"].fillna("Unknown").str.slice(0, 42)
        st.altair_chart(
            _bar_with_labels(top_df, "ghost_score", "Organization", "Label", "#4C78A8", height=320),
            use_container_width=True,
        )

    bottom_left, bottom_right = st.columns(2)
    with bottom_left:
        st.markdown("**Aggregate Financial Exposure**")
        money_df = pd.DataFrame([
            {"Metric": "Federal funding", "Value": df["fed_total"].sum(), "Label": _money(df["fed_total"].sum())},
            {"Metric": "Funding gap", "Value": df["funding_gap"].sum(), "Label": _money(df["funding_gap"].sum())},
            {"Metric": "Transfers out", "Value": df["transfers_out_total"].sum(), "Label": _money(df["transfers_out_total"].sum())},
            {"Metric": "Compensation", "Value": df["total_compensation"].sum(), "Label": _money(df["total_compensation"].sum())},
        ])
        money_df = money_df[money_df["Value"] > 0]
        if money_df.empty:
            st.info("No positive financial exposure values were returned.")
        else:
            st.altair_chart(
                _bar_with_labels(money_df, "Value", "Metric", "Label", "#76B7B2"),
                use_container_width=True,
            )

    with bottom_right:
        st.markdown("**Most Common Triggered Signals**")
        signal_df = _aggregate_signal_rows(results)
        flagged_df = signal_df[signal_df["Flagged"] == "Yes"] if not signal_df.empty else pd.DataFrame()
        if flagged_df.empty:
            st.info("No triggered signal rows were returned.")
        else:
            signal_counts = (
                flagged_df["Signal"]
                .value_counts()
                .head(10)
                .reset_index()
            )
            signal_counts.columns = ["Signal", "Entities"]
            st.altair_chart(
                _bar_with_labels(signal_counts, "Entities", "Signal", "Entities", "#59A14F", height=320),
                use_container_width=True,
            )

    st.divider()
    st.subheader("Key Ideas")
    st.markdown(f"- {high_or_critical:,} of {len(df):,} analyzed organizations are ranked CRITICAL or HIGH.")
    st.markdown(
        f"- Highest-risk entity is {top_entity.get('canonical_name', 'Unknown')} "
        f"with a ghost score of {top_entity.get('ghost_score', 0):.3f}."
    )
    if df["funding_gap"].sum() > 0:
        st.markdown(f"- Combined funding gap across analyzed entities is {_money(df['funding_gap'].sum())}.")
    if df["avg_gov_dependency"].mean() >= 0.80:
        st.markdown("- The aggregate set shows very high government revenue dependency.")

    st.divider()
    st.subheader("Narrative Brief")
    st.info(
        f"This aggregate dashboard summarizes {len(df):,} analyzed organizations. "
        f"{high_or_critical:,} are currently ranked CRITICAL or HIGH, with "
        f"{top_entity.get('canonical_name', 'Unknown')} as the highest-risk lead."
    )
    st.caption("Placeholder for an entity-level LLM narrative. Select a specific organization above to generate it.")

    st.divider()
    st.subheader("Signal Details")
    with st.expander("View Aggregate Signal Details", expanded=False):
        signal_df = _aggregate_signal_rows(results)
        if signal_df.empty:
            st.info("No signal rows were returned.")
        else:
            st.dataframe(signal_df, use_container_width=True, hide_index=True)

    st.divider()
    st.subheader("Exports")
    e1, e2, e3 = st.columns(3)
    e1.download_button(
        "Download Aggregate JSON",
        data=json.dumps([_to_plain(result) for result in results], indent=2, default=str),
        file_name="aggregate-risk-report.json",
        mime="application/json",
        use_container_width=True,
    )
    e2.download_button(
        "Download Aggregate CSV",
        data=df.to_csv(index=False),
        file_name="aggregate-risk-report.csv",
        mime="text/csv",
        use_container_width=True,
    )
    e3.download_button(
        "Download Aggregate Signals CSV",
        data=_aggregate_signal_rows(results).to_csv(index=False),
        file_name="aggregate-risk-signals.csv",
        mime="text/csv",
        use_container_width=True,
    )


def _render_risk_card(result) -> None:
    data = _to_plain(result)
    icon = SEVERITY_COLOUR.get(data.get("overall_risk"), "⚪")
    signals_df = _signal_rows(data)
    signal_chart_df = _signal_chart_rows(data)

    st.subheader(f"{icon} {data.get('canonical_name', 'Unknown')} — {data.get('overall_risk', 'UNKNOWN')} RISK")
    st.caption(
        f"BN: {data.get('bn_root') or '-'} | "
        f"{data.get('entity_type') or '-'} | "
        f"{data.get('province') or '-'} | "
        f"Confidence: {data.get('confidence') or '-'}"
    )

    st.divider()
    st.subheader("KPIs")
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Ghost Score", f"{_float_value(data.get('ghost_score')):.3f}")
    m2.metric("Federal Funding", _money(data.get("fed_total")))
    m3.metric("Funding Gap", _money(data.get("funding_gap")))
    m4.metric("Anomaly Score", f"{_float_value(data.get('anomaly_score')):.3f}")

    s1, s2, s3, s4 = st.columns(4)
    s1.metric("Gov Revenue Share", _pct(data.get("avg_gov_dependency")))
    s2.metric("Program Spend Share", _pct(data.get("avg_program_ratio")))
    s3.metric("Employees", f"{int(_float_value(data.get('total_employees'))):,}")
    s4.metric("Transfers Out", _money(data.get("transfers_out_total")))

    # Coverage data is intentionally hidden for the hackathon dashboard, but
    # kept here so it can be restored quickly.
    # st.markdown("**Coverage**")
    # t1, t2, t3, t4 = st.columns(4)
    # t1.metric("First Grant", _compact(data.get("first_grant_date")))
    # t2.metric("Last Grant", _compact(data.get("last_grant_date")))
    # t3.metric("Last CRA Filing", _compact(data.get("last_cra_filing")))
    # t4.metric("CRA Years", data.get("cra_years", 0))
    #
    # coverage = []
    # coverage.append("CRA data found" if data.get("has_cra_data") else "CRA data missing")
    # coverage.append("FED data found" if data.get("has_fed_data") else "FED data missing")
    # st.caption(" | ".join(coverage) + f" | Persistence: {_compact(data.get('persistence'))}")

    st.divider()
    st.subheader("Plots")

    plot_left, plot_right = st.columns(2)
    with plot_left:
        st.markdown("**Signals vs Thresholds**")
        if signal_chart_df.empty:
            st.info("No signal rows were returned for this entity.")
        else:
            bars = alt.Chart(signal_chart_df).mark_bar(cornerRadiusEnd=3).encode(
                x=alt.X("Value:Q", title="Observed normalized value", scale=alt.Scale(domain=[0, 1])),
                y=alt.Y("Signal:N", sort="-x", title=None),
                color=alt.Color(
                    "Severity:N",
                    scale=alt.Scale(
                        domain=["CRITICAL", "HIGH", "MEDIUM", "LOW"],
                        range=["#D62728", "#FF7F0E", "#E3B341", "#4C78A8"],
                    ),
                    legend=None,
                ),
                tooltip=["Signal", "Flagged", "Value", "Threshold", "Interpretation"],
            )
            labels = alt.Chart(signal_chart_df).mark_text(
                align="right", dx=-6, fontSize=11, color="white"
            ).encode(
                x=alt.X("Value:Q", scale=alt.Scale(domain=[0, 1])),
                y=alt.Y("Signal:N", sort="-x"),
                text=alt.Text("Value:Q", format=".3f"),
            )
            thresholds = alt.Chart(signal_chart_df).mark_tick(
                color="#111827", thickness=2, size=18
            ).encode(
                x="Threshold:Q",
                y=alt.Y("Signal:N", sort="-x"),
                tooltip=["Signal", "Threshold"],
            )
            st.altair_chart((bars + labels + thresholds).properties(height=260), use_container_width=True)

    with plot_right:
        st.markdown("**Financial Exposure**")
        money_df = pd.DataFrame([
            {"Metric": "Federal funding", "Value": _float_value(data.get("fed_total")), "Label": _money(data.get("fed_total"))},
            {"Metric": "Funding gap", "Value": _float_value(data.get("funding_gap")), "Label": _money(data.get("funding_gap"))},
            {"Metric": "Transfers out", "Value": _float_value(data.get("transfers_out_total")), "Label": _money(data.get("transfers_out_total"))},
            {"Metric": "Compensation", "Value": _float_value(data.get("total_compensation")), "Label": _money(data.get("total_compensation"))},
        ])
        money_df = money_df[money_df["Value"] > 0]
        if money_df.empty:
            st.info("No positive financial exposure values were returned.")
        else:
            st.altair_chart(
                _bar_with_labels(money_df, "Value", "Metric", "Label", "#4C78A8"),
                use_container_width=True,
            )

    ratio_left, timeline_right = st.columns(2)
    with ratio_left:
        st.markdown("**Risk Ratios**")
        ratio_df = pd.DataFrame([
            {"Metric": "Ghost score", "Value": _float_value(data.get("ghost_score")), "Label": f"{_float_value(data.get('ghost_score')):.3f}"},
            {"Metric": "Anomaly score", "Value": _float_value(data.get("anomaly_score")), "Label": f"{_float_value(data.get('anomaly_score')):.3f}"},
            {"Metric": "Gov revenue share", "Value": _float_value(data.get("avg_gov_dependency")), "Label": _pct(data.get("avg_gov_dependency"))},
            {"Metric": "Program spend share", "Value": _float_value(data.get("avg_program_ratio")), "Label": _pct(data.get("avg_program_ratio"))},
        ])
        st.altair_chart(
            _bar_with_labels(ratio_df, "Value", "Metric", "Label", "#59A14F"),
            use_container_width=True,
        )

    with timeline_right:
        st.markdown("**Timeline**")
        timeline_df = pd.DataFrame([
            {"Event": "First grant", "Date": data.get("first_grant_date")},
            {"Event": "Last grant", "Date": data.get("last_grant_date")},
            {"Event": "Last CRA filing", "Date": data.get("last_cra_filing")},
        ])
        timeline_df["Date"] = pd.to_datetime(timeline_df["Date"], errors="coerce")
        timeline_df = timeline_df.dropna(subset=["Date"])
        if timeline_df.empty:
            st.info("No timeline dates were returned.")
        else:
            timeline_chart = alt.Chart(timeline_df).mark_circle(size=130, color="#E15759").encode(
                x=alt.X("Date:T", title=None),
                y=alt.Y("Event:N", sort=None, title=None),
                tooltip=["Event", alt.Tooltip("Date:T", format="%Y-%m-%d")],
            ).properties(height=260)
            st.altair_chart(timeline_chart, use_container_width=True)

    st.divider()
    st.subheader("Key Ideas")
    st.write(data.get("explanation") or "No explanation generated.")
    for insight in _insight_lines(data, signal_chart_df):
        st.markdown(f"- {insight}")

    _render_narrative_brief_panel(result)

    st.divider()
    st.subheader("Signal Details")
    with st.expander("View Signal Details", expanded=False):
        if signals_df.empty:
            st.info("No signal rows were returned for this entity.")
        else:
            st.dataframe(signals_df, use_container_width=True, hide_index=True)

    st.divider()
    st.subheader("Exports")
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


def _build_report_markdown(report: dict) -> str:
    lines = [f"**{report.get('document_classification', 'FOR INFORMATION')}**", ""]
    lines += ["**MINISTER BRIEFING NOTE**", f"**AR #:** {report.get('ar_number', 'AR-2026-XXXX')}", ""]
    lines += [f"**TOPIC:** {report.get('topic', 'N/A based on provided data.')}", f"**PURPOSE:** {report.get('purpose', 'N/A based on provided data.')}", ""]
    lines += ["**ISSUE**", f"* {report.get('issue', 'N/A based on provided data.')}", ""]
    lines += ["**RECOMMENDATION / ADVICE**"]
    for item in report.get("recommendation_advice") or ["N/A based on provided data."]:
        lines.append(f"* {item}")
    lines.append("")
    lines += ["**BACKGROUND**"]
    for item in report.get("background") or ["N/A based on provided data."]:
        lines.append(f"* {item}")
    lines.append("")
    lines += ["**CURRENT STATUS / KEY CONSIDERATIONS**"]
    for item in report.get("current_status_key_considerations") or ["N/A based on provided data."]:
        lines.append(f"* {item}")
    lines.append("")
    lines += ["**COMMUNICATIONS**"]
    for item in report.get("communications") or ["N/A based on provided data."]:
        lines.append(f"* {item}")
    lines.append("")
    lines += ["**ATTACHMENTS**"]
    for item in report.get("attachments") or ["N/A based on provided data."]:
        lines.append(f"* {item}")
    lines.append("")
    lines += [
        f"**CONTACT:** {report.get('contact', 'N/A based on provided data.')}",
        f"**REVIEWED/APPROVED BY:** {report.get('reviewed_approved_by', 'N/A based on provided data.')}",
    ]
    return "\n".join(lines)


def _render_business_report_tab() -> None:
    batch_results    = list(st.session_state.get("batch_analysis_results") or [])
    portfolio_result = st.session_state.get("portfolio_results") or {}

    if not batch_results:
        _render_run_analysis_prompt()
        return

    st.caption(
        "One-click report combining deterministic findings with an AI-written summary. "
        "LLM sections are stubs until API credentials are available tomorrow."
    )

    if st.button("Generate Business Report", type="primary"):
        with st.spinner("Building report..."):
            result = run_business_report(batch_results, portfolio_result)
        st.session_state["business_report"] = result
        st.session_state["business_report_prompt"] = _build_business_report_prompt(
            batch_results,
            portfolio_result,
        )

    report = st.session_state.get("business_report")
    if not report:
        return

    if "business_report_prompt" not in st.session_state:
        st.session_state["business_report_prompt"] = _build_business_report_prompt(
            batch_results,
            portfolio_result,
        )

    st.subheader(report.get("document_classification", "FOR INFORMATION"))
    st.caption("Placeholder for a future LLM-written Executive Briefing Note.")

    st.markdown("**MINISTER BRIEFING NOTE**")
    st.markdown(f"**AR #:** {report.get('ar_number', 'AR-2026-XXXX')}")

    st.divider()
    st.markdown(f"**TOPIC:** {report.get('topic', 'N/A based on provided data.')}")
    st.markdown(f"**PURPOSE:** {report.get('purpose', 'N/A based on provided data.')}")

    st.divider()
    st.markdown("**ISSUE**")
    st.markdown(f"- {report.get('issue', 'N/A based on provided data.')}")

    st.markdown("**RECOMMENDATION / ADVICE**")
    _render_briefing_bullets(report.get("recommendation_advice"))

    st.divider()
    st.markdown("**BACKGROUND**")
    _render_briefing_bullets(report.get("background"))

    st.divider()
    st.markdown("**CURRENT STATUS / KEY CONSIDERATIONS**")
    _render_briefing_bullets(report.get("current_status_key_considerations"))

    st.divider()
    st.markdown("**COMMUNICATIONS**")
    _render_briefing_bullets(report.get("communications"))

    st.divider()
    st.markdown("**ATTACHMENTS**")
    _render_briefing_bullets(report.get("attachments"))

    st.divider()
    st.markdown(f"**CONTACT:** {report.get('contact', 'N/A based on provided data.')}")
    st.markdown(f"**REVIEWED/APPROVED BY:** {report.get('reviewed_approved_by', 'N/A based on provided data.')}")
    st.markdown(f"**DATE:** {pd.Timestamp.now().date().isoformat()}")

    # ── Download ──────────────────────────────────────────────────────────────
    md = _build_report_markdown(report)
    st.download_button(
        "Download Briefing Note (Markdown)",
        data=md,
        file_name="fundtrace-minister-briefing-note.md",
        mime="text/markdown",
        use_container_width=False,
    )


def render_report() -> None:
    st.title("FundTrace")
    st.subheader("Report Mode")
    st.caption("Render structured risk reports from deterministic analysis, with optional LLM-written narrative.")

    tab_entity_card, tab_business = st.tabs([
        "Dashboard",
        "Business Report",
    ])

    with tab_entity_card:
        result = _render_entity_selector()
        if isinstance(result, list):
            _render_aggregate_dashboard(result)
        elif result:
            _render_risk_card(result)
        else:
            _render_run_analysis_prompt()

    # with tab_report:
    #     st.subheader("Narrative Brief")
    #     _render_narrative_tab(_matching_analysis_result())
    #     st.divider()
    #     st.subheader("Portfolio Reports")
    #     _render_portfolio_tab()

    with tab_business:
        _render_business_report_tab()

    st.divider()
    st.subheader("Start Over")
    st.caption("Clear the current investigation and begin a new one.")
    restart_col, _ = st.columns([1, 2])
    with restart_col:
        st.button(
            "Start Over",
            type="primary",
            use_container_width=True,
            on_click=reset_workflow,
            key="report_start_over",
        )
