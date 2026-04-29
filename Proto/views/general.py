# views/general.py
# Shared UI helpers, session state, Home page, and Open Search page.
# Import from here in all other view modules to avoid duplication.

import json
from pathlib import Path
import streamlit as st
import streamlit.components.v1 as components
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
WORKFLOW_STEPS = ["Fetch", "Flagged", "Analyze", "Report"]
HOME_IMAGE_PATH = Path(__file__).resolve().parents[2] / "FED" / "image" / "CLAUDE" / "HomePageIcon.png"


# ─── Session state ─────────────────────────────────────────────────────────────

def init_session_state() -> None:
    if "page" not in st.session_state:
        st.session_state["page"] = "Home"
    if "selected_entity" not in st.session_state:
        st.session_state["selected_entity"] = {}
    if "flagged_list" not in st.session_state:
        st.session_state["flagged_list"] = []
    if "analysis_unlocked" not in st.session_state:
        st.session_state["analysis_unlocked"] = False
    if "workflow_notice" not in st.session_state:
        st.session_state["workflow_notice"] = ""
    if "scroll_to_top" not in st.session_state:
        st.session_state["scroll_to_top"] = False


# ─── Navigation ────────────────────────────────────────────────────────────────

def has_flagged_entities() -> bool:
    return bool(st.session_state.get("flagged_list"))


def analysis_unlocked() -> bool:
    return bool(st.session_state.get("analysis_unlocked"))


def has_analysis_results() -> bool:
    return bool(
        st.session_state.get("batch_analysis_results")
        or st.session_state.get("report_entity_analysis")
        or st.session_state.get("portfolio_results")
    )


def clear_downstream_results() -> None:
    for key in (
        "batch_analysis_results",
        "portfolio_results",
        "report_entity_analysis",
        "narrative_brief",
        "narrative_brief_bn",
        "legacy_risk_brief",
    ):
        st.session_state.pop(key, None)


def reset_workflow() -> None:
    clear_downstream_results()
    for key in (
        "selected_entity",
        "flagged_list",
        "business_report",
        "fetch_active_method",
    ):
        st.session_state.pop(key, None)

    st.session_state["selected_entity"] = {}
    st.session_state["flagged_list"] = []
    st.session_state["analysis_unlocked"] = False
    st.session_state["workflow_notice"] = ""
    st.session_state["page"] = "Home"
    st.session_state["scroll_to_top"] = True


def lock_analysis_step() -> None:
    st.session_state["analysis_unlocked"] = False


def unlock_analysis_step() -> None:
    st.session_state["analysis_unlocked"] = True


def page_available(page: str) -> bool:
    if page in ("Home", "Fetch"):
        return True
    if page == "Flagged":
        return has_flagged_entities()
    if page == "Analyze":
        return has_flagged_entities() and analysis_unlocked()
    if page == "Report":
        return has_analysis_results()
    return True


def page_prerequisite(page: str) -> str:
    if page == "Flagged":
        return "Add at least one organization to the Flagged List in Fetch first."
    if page == "Analyze":
        if not has_flagged_entities():
            return "Add at least one organization to the Flagged List in Fetch first."
        return "Use page 2 to elevate your shortlisted entities before running analysis."
    if page == "Report":
        return ""
    return ""


def fallback_page_for(page: str) -> str:
    if page == "Report":
        if analysis_unlocked():
            return "Analyze"
        return "Flagged" if has_flagged_entities() else "Fetch"
    if page == "Analyze":
        return "Flagged" if has_flagged_entities() else "Fetch"
    if page == "Flagged":
        return "Fetch"
    return "Home"


def go_to_page(page: str) -> None:
    if page_available(page):
        st.session_state["page"] = page
        st.session_state["workflow_notice"] = ""
        st.session_state["scroll_to_top"] = True
        return

    st.session_state["page"] = fallback_page_for(page)
    st.session_state["workflow_notice"] = page_prerequisite(page)
    st.session_state["scroll_to_top"] = True


def enforce_workflow_page() -> None:
    page = st.session_state.get("page", "Home")
    if page_available(page):
        return
    st.session_state["page"] = fallback_page_for(page)
    st.session_state["workflow_notice"] = page_prerequisite(page)
    st.session_state["scroll_to_top"] = True


def render_workflow_notice() -> None:
    notice = st.session_state.get("workflow_notice")
    if notice:
        st.warning(notice)
        st.session_state["workflow_notice"] = ""


def render_scroll_to_top() -> None:
    if not st.session_state.get("scroll_to_top"):
        return
    components.html(
        """
        <script>
        window.parent.scrollTo({ top: 0, behavior: "instant" });
        const main = window.parent.document.querySelector('section.main');
        if (main) {
          main.scrollTo({ top: 0, behavior: "instant" });
        }
        </script>
        """,
        height=0,
    )
    st.session_state["scroll_to_top"] = False


def workflow_status_label(page: str) -> str:
    if page == "Fetch":
        return "1. Search Organizations"
    if page == "Flagged":
        return "2. Review Shortlist"
    if page == "Analyze":
        return "3. Run Analysis"
    if page == "Report":
        return "4. View Report"
    return page


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
    st.title("FundTrace")
    st.caption("Find Canadian organizations collecting public money with nothing to show for it.")
    st.divider()

    st.subheader("What this app does")
    st.write(
        "Every year, billions in federal grants flow to Canadian non-profits and charities. "
        "Most organizations use that funding responsibly — but some show patterns that raise questions: "
        "no employees, near-zero program spending, revenue almost entirely from government, "
        "and federal disbursements that far exceed what CRA filings show was spent on delivery. "
        "FundTrace connects federal grants records with CRA charity filings to surface those patterns "
        "and turn them into evidence-ready findings."
    )

    st.subheader("How it works")
    if HOME_IMAGE_PATH.exists():
        st.image(str(HOME_IMAGE_PATH), use_container_width=True)
    st.write(
        "The workflow is intentionally linear. Search for candidate organizations, build a shortlist, "
        "run the analysis, then export a report. Each step stays locked until the previous one is complete "
        "— so findings are always grounded in a consistent review process."
    )

    st.button(
        "Start Investigation",
        type="primary",
        use_container_width=True,
        on_click=go_to_page,
        args=("Fetch",),
    )

    st.divider()

    st.subheader("Why FundTrace is Different")
    impact_cols = st.columns(4)
    impact_cols[0].markdown("**Connects Siloed Data**")
    impact_cols[0].markdown("Links **federal grants** and **CRA charity filings** that are never published together — surfacing patterns invisible in either dataset alone.")
    impact_cols[1].markdown("**Shows Its Work**")
    impact_cols[1].markdown("Every risk score comes with **the signals that drove it** — so reviewers can assess the evidence, not just accept a number.")
    impact_cols[2].markdown("**Human Judgment in the Loop**")
    impact_cols[2].markdown("AI surfaces candidates and scores risk. **Humans decide** which organizations to investigate and what action to take.")
    impact_cols[3].markdown("**Report-Ready Output**")
    impact_cols[3].markdown("Findings export as **structured reports** that can support audit referrals, program reviews, or public accountability work.")

    st.divider()

    orig_cols = st.columns(4)
    orig_cols[0].markdown("**Artificial Intelligence (AI) and Data Science (DS)**")
    orig_cols[0].markdown("Uses **AI and DS methods** to move beyond **keyword search** and surface **patterns across public records**.")
    orig_cols[1].markdown("**Explainability**")
    orig_cols[1].markdown("Shows **why an entity was flagged** and what **evidence supports the finding** to strengthen **accountability**.")
    orig_cols[2].markdown("**Semi-Automated With a Purpose**")
    orig_cols[2].markdown("Uses **AI automation** to increase **efficiency** while humans serve as **guardrails** to maintain **output quality**.")
    orig_cols[3].markdown("**Data-Driven Decision Making**")
    orig_cols[3].markdown("Turns **connected records** into **evidence-based reporting** that can support **review and action**.")


# ─── Zombie recipient context page ────────────────────────────────────────────

def render_zombie_context() -> None:
    st.title("About FundTrace")
    st.caption("The problem we're solving and how the tool approaches it.")
    st.divider()

    st.subheader("What is ghost capacity?")
    st.write(
        "Ghost capacity describes an organization that keeps receiving government funding "
        "but shows no credible evidence it can deliver what it was funded to do. "
        "The signals: revenue almost entirely from government, near-zero program spending, "
        "no reported employees, and federal disbursements that far exceed what CRA filings show was spent on programs. "
        "These patterns persist across multiple years — these are not startups or organizations winding down. "
        "They remain registered, keep receiving money, and leave little public trace of delivery."
    )
    st.write(
        "The label is a triage signal, not a verdict. FundTrace surfaces organizations where the public "
        "record raises questions worth investigating — it leaves the conclusion to human reviewers with access "
        "to context the data alone cannot provide."
    )

    st.subheader("Why this is hard to spot manually")
    st.write(
        "Federal grants data and CRA charity filings are published separately, in different formats, "
        "across different time periods. A single organization can appear dozens of times — across departments, "
        "grant programs, fiscal years, and T3010 filings — with no easy way to connect the records. "
        "Ghost capacity patterns only become visible when those datasets are linked and compared at scale."
    )

    st.subheader("How FundTrace Works")
    st.write(
        "The tool guides reviewers through a structured four-step workflow: search for candidate organizations, "
        "build a shortlist based on judgment and signals, run deterministic risk scoring, and export findings "
        "as a structured report. "
        "Risk scores are built from five dimensions — government revenue dependency, program delivery deficit, "
        "compensation burden, pass-through transfers, and employee count — combined into a single ghost score "
        "with full signal-level transparency. "
        "No finding is presented without the evidence behind it."
    )


# ─── Open Search page ──────────────────────────────────────────────────────────

def render_open_search(show_header: bool = True) -> None:
    if show_header:
        st.title("FundTrace")
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
