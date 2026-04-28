# views/general.py
# Shared UI helpers, session state, Home page, and Open Search page.
# Import from here in all other view modules to avoid duplication.

import json
import streamlit as st
import pandas as pd

from agent.orchestrator import (
    run_open_search,
    run_open_search_prefilter,
)

SEVERITY_COLOUR = {
    "CRITICAL": "🔴",
    "HIGH":     "🟠",
    "MEDIUM":   "🟡",
    "LOW":      "🔵",
}

CORE_DATASETS = {"cra", "fed"}


# ─── Session state ─────────────────────────────────────────────────────────────

def init_session_state() -> None:
    if "page" not in st.session_state:
        st.session_state["page"] = "Home"
    if "selected_entity" not in st.session_state:
        st.session_state["selected_entity"] = {}
    if "flagged_list" not in st.session_state:
        st.session_state["flagged_list"] = []


# ─── Navigation ────────────────────────────────────────────────────────────────

def go_to_page(page: str) -> None:
    st.session_state["page"] = page


# ─── Entity helpers ────────────────────────────────────────────────────────────

def core_sources(sources):
    if not isinstance(sources, list):
        return []
    return [s for s in sources if s in CORE_DATASETS]


def format_sources(sources):
    filtered = core_sources(sources)
    return ", ".join(filtered) if filtered else "—"


def selected_entity_snapshot(record: dict) -> dict:
    return {
        "canonical_name":  record.get("canonical_name", ""),
        "bn_root":         record.get("bn_root", ""),
        "entity_type":     record.get("entity_type", ""),
        "status":          record.get("status", ""),
        "dataset_sources": core_sources(record.get("dataset_sources", [])),
    }


def set_selected_entity(record: dict) -> None:
    st.session_state["selected_entity"] = selected_entity_snapshot(record)


def selected_entity_name() -> str:
    return st.session_state.get("selected_entity", {}).get("canonical_name", "")


def selected_entity_bn() -> str:
    return st.session_state.get("selected_entity", {}).get("bn_root", "")


def selected_entity_query(action: str) -> str:
    name = selected_entity_name()
    bn   = selected_entity_bn()
    if not name:
        return ""
    if bn:
        return f"{action} {name} BN {bn} for ghost capacity"
    return f"{action} {name} for ghost capacity"


def render_selected_entity_banner() -> None:
    ent = st.session_state.get("selected_entity")
    if not ent:
        st.info("No organization selected yet. Use Fetch to search and select an organization.")
        return
    st.success(
        f"Selected organization: **{ent.get('canonical_name', '')}**"
        f" | BN: `{ent.get('bn_root', '—') or '—'}`"
        f" | Sources: {format_sources(ent.get('dataset_sources', []))}"
    )


# ─── Generic value helpers ─────────────────────────────────────────────────────

def profile_value(profile, keys, default="—"):
    if not isinstance(profile, dict):
        return default
    for key in keys:
        value = profile.get(key)
        if value not in (None, "", []):
            return value
    return default


def money_value(value):
    try:
        return f"${float(value):,.0f}"
    except (TypeError, ValueError):
        return "—"


def compact_value(value):
    if value is None:
        return "—"
    if isinstance(value, float) and pd.isna(value):
        return "—"
    if isinstance(value, (dict, list, tuple)):
        return json.dumps(value, default=str, ensure_ascii=False)
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return value


def location_value(record: pd.Series, key: str, default=""):
    cra_value = profile_value(record.get("cra_profile"), [key], None)
    if cra_value not in (None, "", [], "—"):
        return cra_value
    fed_value = profile_value(record.get("fed_profile"), [key], None)
    if fed_value not in (None, "", [], "—"):
        return fed_value
    for address in record.get("addresses") or []:
        if isinstance(address, dict):
            value = address.get(key)
            if value not in (None, "", []):
                return value
    return default


def address_value(record: pd.Series, default=""):
    for address in record.get("addresses") or []:
        if not isinstance(address, dict):
            continue
        parts = [
            address.get("address"),
            address.get("street"),
            address.get("city"),
            address.get("province"),
            address.get("postal_code"),
            address.get("country"),
        ]
        parts = [str(p) for p in parts if p not in (None, "", [])]
        if parts:
            return ", ".join(parts)
    return default


def filter_value(label: str) -> str:
    return "" if label == "Any" else label


def safe_sum(df: pd.DataFrame, column: str) -> float:
    if df.empty or column not in df.columns:
        return 0.0
    return float(pd.to_numeric(df[column], errors="coerce").fillna(0).sum())


# ─── Open Search helpers ───────────────────────────────────────────────────────

@st.cache_data(ttl=600)
def load_open_search_prefilter(candidate_limit: int = 50, min_fed_total: float = 0) -> pd.DataFrame:
    return run_open_search_prefilter(candidate_limit, min_fed_total)


def format_open_search_df(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    return pd.DataFrame({
        "Organization":      df["canonical_name"],
        "BN":                df["bn_root"],
        "City":              df["city"],
        "Province":          df["province"],
        "Prefilter score":   df["prefilter_score"],
        "Federal funding":   df["fed_total"].apply(lambda v: f"${float(v):,.0f}"),
        "Agreements":        df["fed_agreement_count"],
        "CRA years":         df["cra_years"],
        "Gov revenue share": df["avg_gov_dependency"].apply(lambda v: f"{float(v) * 100:.1f}%"),
        "Program spend share": df["avg_program_ratio"].apply(lambda v: f"{float(v) * 100:.1f}%"),
        "Employees":         df["total_employees"],
        "Transfers out":     df["transfers_out_total"].apply(lambda v: f"${float(v):,.0f}"),
        "Funding gap":       df["funding_to_program_gap"].apply(lambda v: f"${float(v):,.0f}"),
    })


def render_open_search_glossary() -> None:
    with st.expander("Open Search glossary", expanded=False):
        st.markdown(
            """
Use these terms in your request to get cleaner results.

**Ranking metrics**

| Ask for... | Meaning |
|---|---|
| most suspicious / ghost capacity | Blended heuristic across government dependency, low program spend, employees, transfers, and funding gap |
| transfers out | Total CRA gifts/transfers to other qualified donees |
| federal funding | Total federal grants/contributions received |
| funding gap | Federal funding minus CRA program spending |
| government dependency | Share of CRA revenue from government sources |
| program spend share | CRA program spending as a share of total expenses |
| employees | CRA-reported employee count |
| compensation | CRA-reported compensation total |
| admin ratio | CRA admin spending as a share of total expenses |
| CRA years | Number of CRA filing years available |
| agreement count | Number of federal agreements |

**Filters you can mention**

| Filter | Example phrase |
|---|---|
| province | in Ontario, in QC, province AB |
| city | in Toronto |
| entity type | charities only, non-profits |
| minimum federal funding | over $500k federal funding |
| transfers threshold | transfers out over $100k |
| government dependency threshold | government revenue above 90% |
| program spend threshold | program spend below 20% |
| funding gap threshold | funding gap over $1M |
| CRA years | at least 4 CRA years |
| zero employees | zero employees, no employees |

**Good example queries**

`Top 10 organizations by transfers out`

`Show Ontario organizations with zero employees and over $500k federal funding`

`Find the most suspicious ghost-capacity candidates with government dependency above 90%`

`Lowest program spend share among CRA and FED organizations`

`Top 20 funding gaps in Quebec`
            """
        )


# ─── Home page ─────────────────────────────────────────────────────────────────

def render_home() -> None:
    st.title("Public Funding Risk Intelligence Agent")
    st.caption("Investigate Canadian organizations receiving public funds for ghost capacity patterns.")
    st.divider()

    st.subheader("What this app does")
    st.write(
        "This prototype helps government employees, journalists, researchers, and members of the public "
        "inspect Canadian organizations that receive public funding. "
        "It combines federal grants data with CRA charity filings to surface patterns where funding "
        "continues but program delivery capacity appears weak, missing, or hard to verify. "
        "The goal is to make open data easier to access, connect, and use for public accountability."
    )

    col_fetch, col_analyze, col_report = st.columns(3)

    with col_fetch:
        st.subheader("Fetch")
        st.write("Pull raw CRA and federal records for a selected organization without using an LLM.")
        st.button(
            "Open Fetch",
            type="primary",
            use_container_width=True,
            on_click=go_to_page,
            args=("Fetch",),
        )

    with col_analyze:
        st.subheader("Analyze")
        st.write("Compute ghost-capacity signals such as government dependency and program-spend gaps.")
        st.button(
            "Open Analyze",
            use_container_width=True,
            on_click=go_to_page,
            args=("Analyze",),
        )

    with col_report:
        st.subheader("Report")
        st.write("Run the full investigation and generate a narrative risk brief with recommendations.")
        st.button(
            "Open Report",
            use_container_width=True,
            on_click=go_to_page,
            args=("Report",),
        )

    st.divider()

    st.subheader("Signals reviewed")
    signal_cols = st.columns(5)
    signal_cols[0].metric("Revenue", "Gov dependency")
    signal_cols[1].metric("Delivery", "Program spend")
    signal_cols[2].metric("Capacity", "Employees")
    signal_cols[3].metric("Flow", "Transfers out")
    signal_cols[4].metric("Pattern", "Persistence")


# ─── Open Search page ──────────────────────────────────────────────────────────

def render_open_search() -> None:
    st.title("Public Funding Risk Intelligence Agent")
    st.subheader("Open Search — Natural language CRA/FED search")
    st.caption("Ask for ranked tables such as top transfers out, zero-employee funded orgs, or likely ghost-capacity candidates.")

    search_request = st.text_area(
        "Search request",
        value="Top 10 organizations by transfers out",
        placeholder="e.g. Show charities in Ontario with zero employees and over $500k federal funding",
        height=90,
    )

    st.caption(
        "Examples: "
        "`top 10 by transfers out`, "
        "`most suspicious ghost capacity candidates`, "
        "`Ontario organizations with zero employees and high federal funding`, "
        "`lowest program spend share`"
    )

    render_open_search_glossary()

    candidate_limit = st.number_input(
        "Preview rows",
        min_value=10,
        max_value=200,
        value=50,
        step=10,
        help="This preview uses the default ghost-capacity heuristic and does not call the LLM.",
    )

    with st.spinner("Loading deterministic candidate preview..."):
        try:
            preview_df = load_open_search_prefilter(int(candidate_limit), 0)
        except Exception as e:
            preview_df = pd.DataFrame()
            st.error(f"Could not load Open Search candidates: {e}")

    if not preview_df.empty:
        st.caption(f"Default ghost-capacity preview: {len(preview_df):,} CRA+FED candidates. No LLM used.")
        st.dataframe(format_open_search_df(preview_df), use_container_width=True, hide_index=True)
    else:
        st.info("No CRA+FED candidates matched the current Open Search settings.")

    st.warning("Run Natural Language Search calls the LLM once to interpret your request and will use API tokens.")
    if st.button("Run Natural Language Search", type="primary", disabled=not search_request.strip()):
        with st.spinner("LLM is interpreting the request, then the database is running the safe query..."):
            result = run_open_search(search_request.strip())

        spec = result.get("spec", {})
        st.subheader("Interpreted Query")
        st.json(spec)

        rows = result.get("results", [])
        if rows:
            st.subheader("Results")
            results_df = pd.DataFrame(rows)
            st.dataframe(format_open_search_df(results_df), use_container_width=True, hide_index=True)
        else:
            st.info("No records matched the interpreted query.")

        if spec.get("explanation"):
            st.caption(spec["explanation"])
