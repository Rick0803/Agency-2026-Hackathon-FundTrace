# views/fetch.py
# Fetch page (Way 1–4 zombie scan tabs) and Flagged entities page.

import time
import streamlit as st
import pandas as pd

from agent.orchestrator import (
    run_fetch,
    run_zombie_heuristics,
    run_way2_scan,
    run_fed_entity_count,
    run_entity_picker_options,
    run_entity_filter_options,
    count_entity_picker_options,
)
from views.general import (
    clear_downstream_results,
    go_to_page,
    set_selected_entity,
    render_selected_entity_banner,
    render_open_search,
    format_sources,
    location_value,
    filter_value,
    safe_sum,
)


# ─── Chart helpers ─────────────────────────────────────────────────────────────

def _labeled_bar_chart(df: pd.DataFrame, x_col: str, y_col: str, height: int = 300):
    """Bar chart with data labels on top of each bar using Altair."""
    import altair as alt
    bars = alt.Chart(df).mark_bar().encode(
        x=alt.X(f"{x_col}:O", sort=None, axis=alt.Axis(labelAngle=0)),
        y=alt.Y(f"{y_col}:Q"),
        tooltip=[x_col, y_col],
    )
    labels = bars.mark_text(dy=-6, fontSize=12, color="white").encode(
        text=alt.Text(f"{y_col}:Q"),
    )
    return (bars + labels).properties(height=height)


# ─── Cached loaders ────────────────────────────────────────────────────────────

@st.cache_data(ttl=600)
def load_entity_picker_options(search: str = "", limit: int = 100, filters: dict = None) -> pd.DataFrame:
    return run_entity_picker_options(search, limit, filters)


@st.cache_data(ttl=600)
def load_entity_filter_options() -> dict:
    return run_entity_filter_options()


@st.cache_data(ttl=600)
def load_entity_picker_count(search: str = "", filters: dict = None) -> int:
    return count_entity_picker_options(search, filters)


# ─── Formatting helpers ────────────────────────────────────────────────────────

def format_picker_df(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    return pd.DataFrame({
        "Organization": df["canonical_name"],
        "BN":           df["bn_root"],
        "Entity type":  df["entity_type"],
        "Status":       df["status"],
        "Sources":      df["dataset_sources"].apply(format_sources),
        "City":         df.apply(lambda row: location_value(row, "city"), axis=1),
        "Province":     df.apply(lambda row: location_value(row, "province"), axis=1),
        "Postal code":  df.apply(lambda row: location_value(row, "postal_code"), axis=1),
    })


# ─── Fetch summary (Way 4 raw data) ───────────────────────────────────────────

def compute_fetch_summary(data: dict) -> dict:
    fed       = data["fed_grants"]
    revenue   = data["revenue_sources"]
    expenses  = data["expense_profile"]
    employees = data["employee_count"]
    transfers = data["transfers_out"]

    fed_total     = safe_sum(fed,       "agreement_value")
    program_total = safe_sum(expenses,  "program_spend")
    expense_total = safe_sum(expenses,  "total_expenses")
    transfer_total = safe_sum(transfers, "amount")
    employee_total = safe_sum(employees, "total_employees")
    gov_total     = safe_sum(revenue,   "gov_total")
    total_revenue = safe_sum(revenue,   "total_revenue")

    gov_dependency = gov_total / total_revenue if total_revenue > 0 else None
    program_ratio  = program_total / expense_total if expense_total > 0 else None

    return {
        "fed_total":      fed_total,
        "fed_count":      len(fed),
        "revenue_years":  len(revenue),
        "expense_years":  len(expenses),
        "employee_years": len(employees),
        "employee_total": employee_total,
        "transfer_count": len(transfers),
        "transfer_total": transfer_total,
        "program_total":  program_total,
        "gov_dependency": gov_dependency,
        "program_ratio":  program_ratio,
    }


def render_fetch_summary(data: dict) -> None:
    summary = compute_fetch_summary(data)

    st.divider()
    st.subheader("Fetch Summary")

    col_fed, col_rev, col_emp, col_trans = st.columns(4)
    col_fed.metric("Federal funding",    f"${summary['fed_total']:,.0f}", f"{summary['fed_count']} agreements")
    col_rev.metric("CRA revenue years",  summary["revenue_years"])
    col_emp.metric("Employee records",   summary["employee_years"], f"{summary['employee_total']:,.0f} employees")
    col_trans.metric("Transfers out",    f"${summary['transfer_total']:,.0f}", f"{summary['transfer_count']} rows")

    col_gov, col_prog, col_exp = st.columns(3)
    gov_label  = "—" if summary["gov_dependency"] is None else f"{summary['gov_dependency'] * 100:.1f}%"
    prog_label = "—" if summary["program_ratio"]  is None else f"{summary['program_ratio']  * 100:.1f}%"
    col_gov.metric("Gov revenue share",   gov_label)
    col_prog.metric("Program spend share", prog_label)
    col_exp.metric("CRA expense years",   summary["expense_years"])

    notes = []
    if summary["fed_total"] > 0 and summary["revenue_years"] == 0:
        notes.append(("warning", "Federal funding found, but no CRA revenue records were returned."))
    if summary["fed_total"] == 0:
        notes.append(("info", "No federal grants were returned for this organization."))
    if summary["revenue_years"] == 0:
        notes.append(("warning", "No CRA revenue records were returned."))
    if summary["expense_years"] == 0:
        notes.append(("warning", "No CRA expense records were returned."))
    if summary["employee_years"] == 0:
        notes.append(("warning", "No CRA employee records were returned."))
    elif summary["employee_total"] == 0:
        notes.append(("warning", "Employee records exist, but total reported employees are zero."))
    if summary["gov_dependency"] is not None and summary["gov_dependency"] >= 0.9:
        notes.append(("warning", "Government revenue share is above 90% in the fetched CRA revenue rows."))
    if summary["program_ratio"] is not None and summary["program_ratio"] < 0.2:
        notes.append(("warning", "Program spend is below 20% of fetched CRA expenses."))
    if summary["transfer_total"] > 0:
        notes.append(("info", "Transfers out were found. Review the Transfers Out tab for pass-through patterns."))

    if notes:
        for kind, text in notes:
            getattr(st, kind)(text)
    else:
        st.success("Core CRA/FED tables returned without obvious coverage gaps in Fetch mode.")

    st.button(
        "Analyze this organization",
        type="primary",
        on_click=go_to_page,
        args=("Analyze",),
    )


# ─── Fetch page ────────────────────────────────────────────────────────────────

def render_fetch() -> None:
    st.title("Public Funding Risk Intelligence Agent")
    st.subheader("Fetch Mode — Zombie Recipient Detection")
    st.caption("Four approaches to fetch and mark suspicious entities in public funding data.")
    st.warning("TODO: Fix the Fetch page title, subtitle, and caption.")

    flagged_count = len(st.session_state.get("flagged_list", []))
    if flagged_count:
        next_col, _ = st.columns([1, 3])
        with next_col:
            st.button(
                f"Continue to Flagged ({flagged_count})",
                type="primary",
                use_container_width=True,
                on_click=go_to_page,
                args=("Flagged",),
            )

    with st.expander("About the data", expanded=False):
        st.markdown(
            """
**The FED grants dataset has 1.275M rows — but only ~140K unique organizations.**

Each row is a single grant agreement. One organization can appear dozens or hundreds of times
across different years, departments, and programs. The scans below work at the **organization level**
(deduplicated by 9-digit CRA Business Number), not the grant-agreement level.

A small number of FED recipients are excluded when their business number cannot be matched to a
known organization in the entity registry — these are typically malformed or missing BNs.
            """
        )

    st.write(
        "Use one of the four methods below to fetch records and mark suspicious entities for further review."
    )

    way1, way2, way3, way4 = st.tabs([
        "User-Defined Rules",
        "AI-Empowered Algorithms",
        "Natural Language Database Search",
        "Filter Lookup",
    ])

    with way1:
        _render_way1()

    with way2:
        _render_way2()

    with way3:
        _render_natural_language_search()

    with way4:
        _render_way4_raw_lookup()


def _render_way1() -> None:
    st.subheader("User-Defined Rules")
    st.caption("Flags recipients using hard heuristic rules. No LLM used.")
    st.markdown(
        "This method turns domain knowledge into **10 configurable rules** for spotting suspicious "
        "funding and filing patterns. Users can adjust key thresholds before running the scan, so the "
        "rules reflect the review context rather than a fixed black-box setting."
    )

    with st.expander("How the rules work", expanded=True):
        st.markdown(
            """
**Zombie recipients** are organizations that received public funding but show signs of having
ceased operations or never meaningfully delivered on that funding.

| # | Rule | Flag |
|---|------|------|
| 1 | **Ceased operations** — last CRA T3010 filing was 2022 or earlier (2+ years before the 2024 dataset cutoff), indicating the org has gone dark | `flag_ceased` |
| 2 | **Stopped filing ≤12mo after last grant** — last CRA T3010 filing falls within one year after last federal grant | `flag_stopped_within_12mo` |
| 3 | **High government dependency** — avg government revenue share ≥ 70% across all filing years | `flag_high_gov_dependency` |
| 4 | **No CRA record at all** — entity received federal grants but has zero CRA filings; completely unverifiable | `flag_no_cra_record` |
| 5 | **Zero private revenue ever** — no donations or earned income across any filing year; 100% reliant on government | `flag_zero_private_revenue` |
| 6 | **Zero program spend ever** — charitable program expenditure is zero across all filing years | `flag_zero_program_spend` |
| 7 | **Compensation exceeds program spend** — total compensation paid out is greater than total spent on programs | `flag_comp_exceeds_programs` |
| 8 | **Funding gap** — total federal grants received exceed total CRA program spend | `flag_funding_gap` |
| 9 | **Young org, early grant** — first federal grant arrived within 2 years of first CRA filing; no track record | `flag_young_org` |
| 10 | **Revenue cliff** — revenue in final filing year dropped below 50% of the prior average; org visibly collapsing | `flag_revenue_cliff` |
            """
        )

    with st.expander("Adjust rule thresholds", expanded=False):
        st.caption("Changes take effect on the next scan.")
        tc1, tc2 = st.columns(2)
        with tc1:
            gov_threshold = st.slider(
                "3 — Gov dependency threshold",
                min_value=0, max_value=100, value=70, step=5, format="%d%%",
                help="Flag entities whose average government revenue share is at or above this level.",
            ) / 100
            cliff_threshold = st.slider(
                "10 — Revenue cliff drop",
                min_value=10, max_value=90, value=50, step=5, format="%d%%",
                help="Flag entities whose final filing revenue fell below this % of their prior average.",
            ) / 100
            filing_window = st.slider(
                "2 — Filing window after last grant (months)",
                min_value=1, max_value=36, value=12, step=1,
                help="Flag entities whose last CRA filing fell within this many months after their last federal grant.",
            ) * 30
        with tc2:
            ceased_cutoff = st.selectbox(
                "1 — Gone dark cutoff year",
                options=[2020, 2021, 2022, 2023, 2024],
                index=2,
                help="Flag entities whose last CRA filing was before January 1 of this year.",
            )
            young_org_years = st.slider(
                "9 — Young org track record window (years)",
                min_value=1, max_value=5, value=2, step=1,
                help="Flag entities whose first federal grant arrived within this many years of their first CRA filing.",
            )
            min_fed = st.number_input(
                "Min federal funding ($)",
                min_value=0, value=0, step=10_000,
                help="Only include entities that received at least this much in total federal grants.",
            )

    if st.button("Run Zombie Scan", type="primary"):
        t0 = time.time()
        with st.spinner("Scanning database..."):
            try:
                zombie_df = run_zombie_heuristics(
                    gov_dependency_threshold=gov_threshold,
                    min_fed_total=min_fed,
                    revenue_cliff_threshold=cliff_threshold,
                    ceased_cutoff_year=ceased_cutoff,
                    filing_window_days=filing_window,
                    young_org_years=young_org_years,
                )
                total_entities = run_fed_entity_count()
            except Exception as e:
                st.error(f"Query failed: {e}")
                zombie_df = pd.DataFrame()
                total_entities = 0
        elapsed = time.time() - t0
        st.session_state["zombie_df"] = zombie_df
        st.session_state["zombie_total_entities"] = total_entities
        st.session_state["zombie_elapsed"] = elapsed

    zombie_df    = st.session_state.get("zombie_df", pd.DataFrame())
    total_entities = st.session_state.get("zombie_total_entities", 0)
    elapsed      = st.session_state.get("zombie_elapsed", 0.0)

    if zombie_df.empty:
        st.info("No matching entities found with the current thresholds.")
        return

    flag_cols = [
        "flag_ceased", "flag_stopped_within_12mo", "flag_high_gov_dependency",
        "flag_no_cra_record", "flag_zero_private_revenue", "flag_zero_program_spend",
        "flag_comp_exceeds_programs", "flag_funding_gap",
        "flag_young_org", "flag_revenue_cliff",
    ]
    rule_labels = [
        "1 Gone dark (≤2022)", "2 Stopped ≤12mo", "3 High dependency",
        "4 No CRA record", "5 Zero priv revenue", "6 Zero prog spend",
        "7 Comp > prog spend", "8 Funding gap",
        "9 Young org", "10 Revenue cliff",
    ]

    if "rules_triggered" not in zombie_df.columns:
        zombie_df["rules_triggered"] = zombie_df[flag_cols].apply(
            lambda row: int(row.sum()), axis=1
        )

    n_flagged = len(zombie_df)
    pct       = n_flagged / total_entities * 100 if total_entities else 0
    n_three   = int((zombie_df["rules_triggered"] == 3).sum())
    n_five    = int((zombie_df["rules_triggered"] >= 5).sum())
    pct_three = n_three / total_entities * 100 if total_entities else 0
    pct_five  = n_five  / total_entities * 100 if total_entities else 0

    # Coverage card
    st.divider()
    st.subheader("Coverage")
    cov1, cov2, cov3, cov4 = st.columns(4)
    cov1.metric("Entities scanned", f"{total_entities:,}")
    cov2.metric("Flag rate",        f"{pct:.1f}%")
    cov3.metric("Scan time",        f"{elapsed:.1f}s")

    m1, m2, m3 = st.columns(3)
    m1.metric("Flagged (≥1 rule)", f"{n_flagged:,}", f"{pct:.1f}% of scanned")
    m2.metric("Flagged 3 times",   f"{n_three:,}",   f"{pct_three:.1f}% of scanned")
    m3.metric("Flagged 5+ times",  f"{n_five:,}",    f"{pct_five:.1f}% of scanned")

    # Histogram + rule breakdown
    st.divider()
    col_hist, col_table = st.columns(2)

    with col_hist:
        st.subheader("Rules triggered per entity")
        hist_data = (
            zombie_df["rules_triggered"]
            .value_counts()
            .reindex(range(1, len(flag_cols) + 1), fill_value=0)
            .reset_index()
        )
        hist_data.columns = ["Rules triggered", "Entities"]
        hist_data["Rules triggered"] = hist_data["Rules triggered"].astype(str)
        st.altair_chart(_labeled_bar_chart(hist_data, "Rules triggered", "Entities", height=300), use_container_width=True)
        st.caption("How many rules each flagged entity triggered. Higher = stronger zombie signal.")

    with col_table:
        st.subheader("Rule breakdown")
        breakdown = pd.DataFrame({
            "Rule":  rule_labels,
            "Count": [int(zombie_df[c].sum()) for c in flag_cols],
        })
        breakdown["% of flagged"] = (breakdown["Count"] / n_flagged * 100).map(lambda v: f"{v:.1f}%")
        st.dataframe(breakdown, use_container_width=True, hide_index=True)
        st.caption("How many flagged entities each rule contributed to.")

    # Detailed results table with checkboxes
    st.divider()
    st.subheader("Flagged entities")
    zombie_df = zombie_df.sort_values("rules_triggered", ascending=False).reset_index(drop=True)
    flag = lambda col: zombie_df[col].apply(lambda v: "✓" if v else "")
    display_df = pd.DataFrame({
        "Select":              False,
        "Organization":        zombie_df["canonical_name"],
        "BN":                  zombie_df["bn_root"],
        "Status":              zombie_df["status"],
        "Province":            zombie_df["province"],
        "Federal funding":     zombie_df["fed_total"].apply(lambda v: f"${float(v):,.0f}"),
        "Program spend":       zombie_df["total_program_spend"].apply(lambda v: f"${float(v):,.0f}"),
        "Funding gap":         zombie_df["funding_gap"].apply(lambda v: f"${float(v):,.0f}"),
        "First grant":         zombie_df["first_grant_date"],
        "Last grant":          zombie_df["last_grant_date"],
        "Last CRA filing":     zombie_df["last_cra_filing"],
        "Gov dependency":      zombie_df["avg_gov_dependency"].apply(lambda v: f"{float(v)*100:.1f}%"),
        "Rules triggered":     zombie_df["rules_triggered"],
        "1 Ceased":           flag("flag_ceased"),
        "2 Stopped ≤12mo":    flag("flag_stopped_within_12mo"),
        "3 High dependency":  flag("flag_high_gov_dependency"),
        "4 No CRA":           flag("flag_no_cra_record"),
        "5 Zero priv rev":    flag("flag_zero_private_revenue"),
        "6 Zero prog spend":  flag("flag_zero_program_spend"),
        "7 Comp>prog spend":  flag("flag_comp_exceeds_programs"),
        "8 Funding gap":      flag("flag_funding_gap"),
        "9 Young org":        flag("flag_young_org"),
        "10 Revenue cliff":   flag("flag_revenue_cliff"),
    })
    edited_df = st.data_editor(
        display_df,
        use_container_width=True,
        hide_index=True,
        column_config={"Select": st.column_config.CheckboxColumn("Select", default=False)},
        disabled=[c for c in display_df.columns if c != "Select"],
    )

    n_checked = int(edited_df["Select"].sum())
    add_col, _ = st.columns([1, 3])
    with add_col:
        if st.button(
            f"Add {n_checked} to Flagged List" if n_checked else "Add to Flagged List",
            type="primary",
            disabled=n_checked == 0,
            use_container_width=True,
        ):
            checked_indices = edited_df.index[edited_df["Select"]].tolist()
            existing_bns = {e["bn_root"] for e in st.session_state["flagged_list"]}
            added = 0
            for i in checked_indices:
                row = zombie_df.iloc[i]
                if row["bn_root"] not in existing_bns:
                    st.session_state["flagged_list"].append({
                        "canonical_name":  row["canonical_name"],
                        "bn_root":         row["bn_root"],
                        "entity_type":     row["entity_type"],
                        "status":          row["status"],
                        "dataset_sources": list(row.get("dataset_sources") or []),
                        "rules_triggered": int(row["rules_triggered"]),
                        "province":        row.get("province", ""),
                        "fed_total":       float(row["fed_total"]),
                    })
                    existing_bns.add(row["bn_root"])
                    added += 1
            if added:
                clear_downstream_results()
                st.success(f"Added {added} organization(s) to the Flagged List.")
            else:
                st.info("All selected organizations were already in the Flagged List.")


# ─── Natural language database search ─────────────────────────────────────────

def _render_natural_language_search() -> None:
    st.subheader("Natural Language Database Search")
    st.markdown(
        "Use plain-language questions as database queries to fetch matching organizations and ranked results. "
        "For the most accurate and consistent searches, refer to the glossary before running a query so field "
        "names, funding concepts, and risk terms are interpreted the way you expect."
    )
    render_open_search(show_header=False)


# ─── Future Way 3 pseudocode: Open Search inside Fetch ────────────────────────
#
# Way 3 is intended to be the existing Open Search experience currently exposed
# as its own app page. Keep this commented until the app restructure is ready.
#
# Minimal move:
#   1. Uncomment the future imports near the top of this file:
#        from views.general import render_open_search
#   2. Replace the Way 3 placeholder with:
#        render_open_search()
#
# Caveat:
#   render_open_search() includes its own st.title(), so it works as a full page.
#   Inside a Fetch tab, the more polished option is the tab-specific version below
#   because it avoids repeating the app title.
#
#
# def _render_way3_open_search() -> None:
#     """
#     Future Way 3 — LLM-powered Open Search embedded under Fetch.
#
#     This is adapted from the current Open Search page in app.py / views.general.
#     The LLM only converts natural language into an allowlisted query spec.
#     The database query itself stays deterministic and controlled by
#     retrieval.fetch_open_search_candidates().
#     """
#
#     st.subheader("Way 3 — Open Search")
#     st.caption(
#         "Use natural language to search ranked CRA/FED candidate tables. "
#         "The LLM interprets intent; SQL remains allowlisted."
#     )
#
#     search_request = st.text_area(
#         "Search request",
#         value="Top 10 organizations by transfers out",
#         placeholder="e.g. Show charities in Ontario with zero employees and over $500k federal funding",
#         height=90,
#         key="fetch_way3_open_search_request",
#     )
#
#     st.caption(
#         "Examples: "
#         "`top 10 by transfers out`, "
#         "`most suspicious ghost capacity candidates`, "
#         "`Ontario organizations with zero employees and high federal funding`, "
#         "`lowest program spend share`"
#     )
#
#     render_open_search_glossary()
#
#     candidate_limit = st.number_input(
#         "Preview rows",
#         min_value=10,
#         max_value=200,
#         value=50,
#         step=10,
#         help="This preview uses the default ghost-capacity heuristic and does not call the LLM.",
#         key="fetch_way3_preview_rows",
#     )
#
#     with st.spinner("Loading deterministic candidate preview..."):
#         try:
#             preview_df = load_open_search_prefilter(int(candidate_limit), 0)
#         except Exception as e:
#             preview_df = pd.DataFrame()
#             st.error(f"Could not load Open Search candidates: {e}")
#
#     if not preview_df.empty:
#         st.caption(
#             f"Default ghost-capacity preview: {len(preview_df):,} CRA+FED candidates. "
#             "No LLM used."
#         )
#         st.dataframe(format_open_search_df(preview_df), use_container_width=True, hide_index=True)
#     else:
#         st.info("No CRA+FED candidates matched the current Open Search settings.")
#
#     st.warning("Run Natural Language Search calls the LLM once to interpret your request and will use API tokens.")
#     if st.button(
#         "Run Natural Language Search",
#         type="primary",
#         disabled=not search_request.strip(),
#         key="fetch_way3_run_open_search",
#     ):
#         with st.spinner("LLM is interpreting the request, then the database is running the safe query..."):
#             result = run_open_search(search_request.strip())
#
#         spec = result.get("spec", {})
#         st.subheader("Interpreted Query")
#         st.json(spec)
#
#         rows = result.get("results", [])
#         if rows:
#             st.subheader("Results")
#             results_df = pd.DataFrame(rows)
#             st.dataframe(format_open_search_df(results_df), use_container_width=True, hide_index=True)
#         else:
#             st.info("No records matched the interpreted query.")
#
#         if spec.get("explanation"):
#             st.caption(spec["explanation"])
#

def _render_way4_raw_lookup() -> None:
    st.subheader("Filter Lookup")
    st.caption("Pulls raw data from CRA and FED directly for a selected organization.")
    render_selected_entity_banner()

    picked_entity_name = ""
    picker_df = pd.DataFrame()

    with st.expander("Choose from organization list", expanded=True):
        search_query = st.text_input(
            "Search organizations",
            placeholder="Type a name or 9-digit BN",
            help="The list refreshes as you type.",
        )

        try:
            filter_options = load_entity_filter_options()
        except Exception as e:
            filter_options = {"entity_types": [], "statuses": ["active"], "provinces": [], "cities": []}
            st.warning(f"Could not load filter options: {e}")

        col_type, col_source, col_status = st.columns(3)
        with col_type:
            entity_type_filter = st.selectbox("Entity type", ["Any"] + filter_options.get("entity_types", []))
        with col_source:
            source_filter = st.selectbox("Sources", ["Any", "CRA", "FED", "CRA + FED"])
        with col_status:
            status_options = ["Any"] + filter_options.get("statuses", [])
            default_status_index = status_options.index("active") if "active" in status_options else 0
            status_filter = st.selectbox("Status", status_options, index=default_status_index)

        col_city, col_province = st.columns(2)
        with col_city:
            city_filter = st.selectbox("City", ["Any"] + filter_options.get("cities", []))
        with col_province:
            province_filter = st.selectbox("Province", ["Any"] + filter_options.get("provinces", []))

        source_filter_map = {"Any": "", "CRA": "cra", "FED": "fed", "CRA + FED": "cra_fed"}
        picker_filters = {
            "entity_type": filter_value(entity_type_filter),
            "source":      source_filter_map[source_filter],
            "status":      filter_value(status_filter),
            "city":        filter_value(city_filter),
            "province":    filter_value(province_filter),
        }

        try:
            result_count = load_entity_picker_count(search_query, picker_filters)
            picker_df    = load_entity_picker_options(search_query, filters=picker_filters)
        except Exception as e:
            st.warning(f"Could not load organization picker: {e}")
            result_count = 0

        st.caption(f"{result_count:,} matching organizations. Showing up to {len(picker_df):,}.")
        if not picker_df.empty:
            picker_raw_df = picker_df.copy()
            picker_df     = format_picker_df(picker_raw_df)
            st.dataframe(picker_df, use_container_width=True, hide_index=True)

            selected_index = st.selectbox(
                "Organization to fetch",
                list(range(len(picker_df))),
                index=0,
                format_func=lambda i: f"{picker_df.loc[i, 'Organization']} ({picker_df.loc[i, 'BN']})",
            )
            selected_record = picker_raw_df.iloc[selected_index].to_dict()
            set_selected_entity(selected_record)
            picked_entity_name = selected_record.get("canonical_name", "") or ""
        else:
            st.info("No organizations are available in the picker yet. Use manual search below.")

    entity_name = st.text_input(
        "Organization name",
        value=picked_entity_name,
        placeholder="e.g. GITES JEUNESSE INC",
        help="Pick from the table above or type another organization name.",
        key=f"fetch_entity_name_{picked_entity_name}",
    )

    if st.button("Fetch Data", type="primary") and entity_name.strip():
        with st.spinner("Querying database..."):
            data = run_fetch(entity_name.strip())

        if "error" in data:
            st.error(data["error"])
        else:
            ent = data["entity"]
            set_selected_entity({
                "canonical_name":  ent.get("canonical_name", ""),
                "bn_root":         ent.get("bn_root", ""),
                "entity_type":     ent.get("entity_type", ""),
                "status":          ent.get("status", ""),
                "dataset_sources": ent.get("dataset_sources", []),
            })
            st.success(f"**{ent['canonical_name']}** — BN: `{ent['bn_root']}` | Sources: {ent['dataset_sources']}")

            render_fetch_summary(data)

            tab_grants, tab_rev, tab_exp, tab_emp, tab_trans = st.tabs([
                "Federal Grants", "Revenue Sources", "Expense Profile", "Employees", "Transfers Out"
            ])
            with tab_grants:
                df = data["fed_grants"]
                if df.empty:
                    st.info("No federal grants found.")
                else:
                    st.metric("Total federal funding", f"${df['agreement_value'].sum():,.0f}")
                    st.dataframe(df, use_container_width=True)
            with tab_rev:
                df = data["revenue_sources"]
                st.dataframe(df, use_container_width=True) if not df.empty else st.info("No CRA revenue data.")
            with tab_exp:
                df = data["expense_profile"]
                st.dataframe(df, use_container_width=True) if not df.empty else st.info("No CRA expense data.")
            with tab_emp:
                df = data["employee_count"]
                st.dataframe(df, use_container_width=True) if not df.empty else st.info("No employee data.")
            with tab_trans:
                df = data["transfers_out"]
                st.dataframe(df, use_container_width=True) if not df.empty else st.info("No transfers found.")


# ─── Flagged entities page ─────────────────────────────────────────────────────

def render_flagged() -> None:
    st.title("Public Funding Risk Intelligence Agent")
    st.subheader("Flagged Entities — Review List")
    st.caption("The first 10 candidates are preselected for analysis. Adjust the checklist, then continue.")

    flagged = st.session_state["flagged_list"]

    if not flagged:
        st.info("No entities flagged yet. Run a scan in Fetch → User-Defined Rules and check the boxes to add organizations here.")
        return

    st.caption(f"{len(flagged)} organization(s) in your list.")

    flagged_display = pd.DataFrame({
        "Include":         [i < 10 for i in range(len(flagged))],
        "Organization":    [e["canonical_name"] for e in flagged],
        "BN":              [e["bn_root"] for e in flagged],
        "Province":        [e.get("province", "") for e in flagged],
        "Federal funding": [f"${e['fed_total']:,.0f}" for e in flagged],
        "Rules triggered": [e["rules_triggered"] for e in flagged],
        "Status":          [e.get("status", "") for e in flagged],
    })

    edited_flagged = st.data_editor(
        flagged_display,
        use_container_width=True,
        hide_index=True,
        key="flagged_include_editor",
        column_config={"Include": st.column_config.CheckboxColumn("Include", default=True)},
        disabled=[c for c in flagged_display.columns if c != "Include"],
    )

    n_include = int(edited_flagged["Include"].sum())
    st.caption(f"{n_include} organization(s) selected for analysis.")

    apply_col, clear_col, _ = st.columns([1, 1, 3])
    with apply_col:
        if st.button(
            "Apply selection",
            disabled=n_include == len(flagged),
            use_container_width=True,
        ):
            keep = edited_flagged.index[edited_flagged["Include"]].tolist()
            st.session_state["flagged_list"] = [flagged[i] for i in keep]
            clear_downstream_results()
            st.rerun()
    with clear_col:
        if st.button("Clear all", use_container_width=True):
            st.session_state["flagged_list"] = []
            clear_downstream_results()
            st.rerun()

    st.divider()
    st.subheader("Continue to analysis")
    if st.button("Elevate These Entities by Analyzing Them", type="primary", disabled=n_include == 0, use_container_width=True):
        keep = edited_flagged.index[edited_flagged["Include"]].tolist()
        selected_flagged = [flagged[i] for i in keep]
        st.session_state["flagged_list"] = selected_flagged
        clear_downstream_results()
        set_selected_entity(selected_flagged[0])
        go_to_page("Analyze")


def _format_way2_display(df: pd.DataFrame) -> pd.DataFrame:
    """Converts raw Way 2 scored rows into Streamlit-friendly display columns."""
    return pd.DataFrame({
        "Select":           False,
        "Organization":     df["canonical_name"],
        "BN":               df["bn_root"],
        "Province":         df["province"],
        "Entity type":      df["entity_type"],
        "Anomaly score":    df["anomaly_score"].apply(lambda v: f"{float(v):.3f}"),
        "Peer group":       df["peer_group"],
        "Rules triggered":  df["rules_triggered"].apply(lambda v: int(float(v))),
        "Top rules":        df["top_rules"],
        "Explanation":      df["explanation"],
        "Federal funding":  df["fed_total"].apply(lambda v: f"${float(v):,.0f}"),
        "Gov dependency":   df["avg_gov_dependency"].apply(lambda v: f"{float(v)*100:.1f}%"),
        "Program spend":    df["avg_program_ratio"].apply(lambda v: f"{float(v)*100:.1f}%"),
        "Funding gap":      df["funding_gap"].apply(lambda v: f"${float(v):,.0f}"),
        "Employees":        df["total_employees"].apply(lambda v: int(float(v))),
        "Transfers out":    df["transfers_out_total"].apply(lambda v: f"${float(v):,.0f}"),
    })


def _render_way2() -> None:
    st.subheader("AI-Empowered Algorithms")
    st.caption(
        "Ranks organizations that look statistically unusual compared with "
        "similar publicly funded peers. Uses user-defined rule signals as model features. No LLM."
    )
    st.markdown(
        "This method uses anomaly detection to find organizations whose funding, filing, spending, "
        "and capacity patterns differ from comparable peers. Instead of checking one rule at a time, "
        "the algorithm considers multiple signals together and prioritizes entities that deserve closer review."
    )

    with st.expander("How This Method Works", expanded=False):
        st.markdown(
            """
**This method combines unsupervised anomaly detection with the 10 user-defined rules as domain knowledge features.**

The model scores each organization against its peers — organizations in a similar funding band
and entity type — rather than against the entire universe. This prevents large hospital networks
from making small charities look normal.

**Features used by the model:**

| Category | Features |
|---|---|
| Ratios (from CRA) | Gov dependency, program spend share, admin spend share |
| Scale (from FED) | Log federal funding, log agreement count |
| Gap signals | Funding gap ratio, compensation-to-program ratio, transfers-to-expenses ratio |
| Time | Years since last CRA filing, grant span years, revenue cliff ratio |
| Domain knowledge | Rules triggered (count of user-defined rule flags), gov × low-program interaction |

**Models available:**
- **ECOD** — Empirical CDF outlier detection. Parameter-free, fast, robust to outliers in the training data.
- **Isolation Forest** — Tree-based anomaly detection. Good for high-dimensional data.
- **LOF** — Local Outlier Factor. Best for detecting local density anomalies.

**Peer grouping:**
Entities are scored within groups sharing the same entity type and funding band.
Groups smaller than 15 entities fall back to global scoring.
            """
        )

    with st.expander("Configure anomaly scan", expanded=True):
        w2c1, w2c2 = st.columns(2)
        with w2c1:
            selected_model = st.selectbox(
                "Anomaly model",
                ["ECOD", "Isolation Forest", "LOF"],
                index=0,
                help="ECOD is fastest and parameter-free. IF and LOF require sklearn.",
            )
            peer_grouping = st.selectbox(
                "Peer grouping",
                ["By entity type + funding band", "By entity type", "By funding band", "None / global"],
                index=0,
                help="Score each entity against peers of similar size and type.",
            )
        with w2c2:
            min_fed_w2 = st.number_input(
                "Min federal funding ($)",
                min_value=0, value=0, step=10_000,
                help="Only include entities that received at least this much in total federal grants.",
                key="way2_min_fed",
            )
            max_results_w2 = st.number_input(
                "Max results shown",
                min_value=10, max_value=500, value=100, step=10,
                help="Number of top anomalies to display after scoring.",
                key="way2_max_results",
            )

    if st.button("Run Anomaly Scan", type="primary", key="way2_run"):
        t0 = time.time()
        with st.spinner("Building entity-level feature table — this may take 30–60s..."):
            try:
                way2_df = run_way2_scan(
                    min_fed_total=float(min_fed_w2),
                    model_name=selected_model,
                    peer_grouping=peer_grouping,
                )
            except Exception as e:
                st.error(f"Anomaly scan failed: {e}")
                way2_df = pd.DataFrame()
        elapsed_w2 = time.time() - t0
        st.session_state["way2_df"]      = way2_df
        st.session_state["way2_elapsed"] = elapsed_w2
        st.session_state["way2_model"]   = selected_model
        st.session_state["way2_peers"]   = peer_grouping

    way2_df = st.session_state.get("way2_df", pd.DataFrame())
    elapsed_w2 = st.session_state.get("way2_elapsed", 0.0)

    if way2_df.empty:
        st.info("Configure the scan above and click Run Anomaly Scan.")
        return

    top_df = way2_df.head(int(max_results_w2))

    # Metrics
    st.divider()
    st.subheader("Coverage")
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Entities scored",  f"{len(way2_df):,}")
    m2.metric("Scan time",        f"{elapsed_w2:.1f}s")
    m3.metric("Model",            st.session_state.get("way2_model", "—"))
    m4.metric("Shown",            f"{len(top_df):,}")

    # Score distribution
    col_hist, col_rules = st.columns(2)
    with col_hist:
        st.subheader("Anomaly score distribution")
        import numpy as np
        bins = np.linspace(0, 1, 11)
        counts, edges = np.histogram(way2_df["anomaly_score"].clip(0, 1), bins=bins)
        hist_df = pd.DataFrame({
            "Score range": [f"{edges[i]:.1f}–{edges[i+1]:.1f}" for i in range(len(counts))],
            "Entities": counts,
        })
        st.altair_chart(_labeled_bar_chart(hist_df, "Score range", "Entities", height=250), use_container_width=True)
        st.caption("Distribution of anomaly scores across all scored entities.")

    with col_rules:
        st.subheader("Top anomalies: rules triggered")
        rule_dist = (
            top_df["rules_triggered"]
            .apply(lambda v: int(float(v)))
            .value_counts()
            .sort_index()
            .reset_index()
        )
        rule_dist.columns = ["Rules triggered", "Entities"]
        rule_dist["Rules triggered"] = rule_dist["Rules triggered"].astype(str)
        st.altair_chart(_labeled_bar_chart(rule_dist, "Rules triggered", "Entities", height=250), use_container_width=True)
        st.caption(f"How many user-defined rules each top-{len(top_df)} anomaly triggered.")

    # Results table with checkboxes — sorted by rules triggered desc, then anomaly score desc
    top_df = top_df.sort_values(
        ["rules_triggered", "anomaly_score"], ascending=[False, False]
    ).reset_index(drop=True)

    st.divider()
    st.subheader(f"Top {len(top_df)} anomalies")
    display_df = _format_way2_display(top_df)

    edited_w2 = st.data_editor(
        display_df,
        use_container_width=True,
        hide_index=True,
        column_config={"Select": st.column_config.CheckboxColumn("Select", default=False)},
        disabled=[c for c in display_df.columns if c != "Select"],
    )

    n_checked_w2 = int(edited_w2["Select"].sum())
    add_col_w2, _ = st.columns([1, 3])
    with add_col_w2:
        if st.button(
            f"Add {n_checked_w2} to Flagged List" if n_checked_w2 else "Add to Flagged List",
            type="primary",
            disabled=n_checked_w2 == 0,
            use_container_width=True,
            key="way2_add_flagged",
        ):
            checked_indices = edited_w2.index[edited_w2["Select"]].tolist()
            existing_bns = {e["bn_root"] for e in st.session_state["flagged_list"]}
            added = 0
            for i in checked_indices:
                row = top_df.iloc[i]
                if row["bn_root"] not in existing_bns:
                    st.session_state["flagged_list"].append({
                        "canonical_name":  row["canonical_name"],
                        "bn_root":         row["bn_root"],
                        "entity_type":     row.get("entity_type", ""),
                        "status":          row.get("status", "active"),
                        "dataset_sources": list(row.get("dataset_sources") or []),
                        "rules_triggered": int(float(row.get("rules_triggered", 0))),
                        "province":        row.get("province", ""),
                        "fed_total":       float(row["fed_total"]),
                    })
                    existing_bns.add(row["bn_root"])
                    added += 1
            if added:
                clear_downstream_results()
                st.success(f"Added {added} organization(s) to the Flagged List.")
            else:
                st.info("All selected organizations were already in the Flagged List.")
