from pathlib import Path

import streamlit as st

from views import general
# OPTIMIZATION: Lazy load heavy view modules only when needed
# from views import fetch, analyze, report
# OPTIMIZATION: Lazy load preload only when needed
# from tools.preload import start_fetch_preload

PAGE_OPTIONS = [
    "Home",
    "Fetch",
    "Flagged",
    "Analyze",
    "Report",
]

st.set_page_config(page_title="FundTrace", layout="wide")

SIDEBAR_ICON_PATH = Path(__file__).resolve().parent / "Gemini_Generated_Icon.png"

general.init_session_state()
general.enforce_workflow_page()

# OPTIMIZATION: Only start preload if user is on Fetch page or has flagged entities
# This prevents heavy background queries on initial app load
if st.session_state.get("page") in ["Fetch", "Flagged"] or st.session_state.get("flagged_list"):
    from tools.preload import start_fetch_preload
    start_fetch_preload()

# OPTIMIZATION: Disable portfolio cache warming - it's too slow for startup
# The cache will warm naturally when user first visits Analyze page
# if "portfolio_cache_warmed" not in st.session_state:
#     st.session_state["portfolio_cache_warmed"] = True
#     try:
#         from views.analyze import _cached_run_portfolio_analysis
#         _cached_run_portfolio_analysis(0.0)
#     except Exception:
#         pass

with st.sidebar:
    if SIDEBAR_ICON_PATH.exists():
        st.image(str(SIDEBAR_ICON_PATH), width=132)
    st.markdown(
        "<div style='margin-top:-0.5rem; margin-bottom:0.15rem; font-size:2rem; font-weight:700;'>FundTrace</div>",
        unsafe_allow_html=True,
    )
    st.caption("Track public funding. Surface zombie & ghost recipients.")
    st.divider()
    st.markdown(
        "<div style='text-align:center; font-size:1.5rem; font-weight:700; margin-bottom:0.5rem;'>Workflow</div>",
        unsafe_allow_html=True,
    )
    for option in PAGE_OPTIONS:
        button_type = "primary" if st.session_state["page"] == option else "secondary"
        disabled = not general.page_available(option)
        label = general.workflow_status_label(option)
        if st.button(
            label,
            type=button_type,
            use_container_width=True,
            disabled=disabled,
            key=f"sidebar_nav_{option.lower()}",
        ):
            general.go_to_page(option)
            st.rerun()
    st.caption("Greyed-out buttons mean you are not there yet. Complete the current page first.")
    st.divider()
    if st.button(
        "Start Over",
        type="secondary",
        use_container_width=True,
        key="sidebar_start_over",
    ):
        general.reset_workflow()
        st.rerun()
    st.divider()
    if st.button(
        "About This Tool",
        type="primary" if st.session_state["page"] == "Zombie Context" else "secondary",
        use_container_width=True,
        key="sidebar_about_tool",
    ):
        general.go_to_page("Zombie Context")
        st.rerun()

page = st.session_state["page"]
general.render_workflow_notice()

if page == "Home":
    general.render_home()
elif page == "Fetch":
    from views import fetch
    fetch.render_fetch()
elif page == "Flagged":
    from views import fetch
    fetch.render_flagged()
elif page == "Analyze":
    from views import analyze
    analyze.render_analyze()
elif page == "Report":
    from views import report
    report.render_report()
elif page == "Zombie Context":
    general.render_zombie_context()

general.render_scroll_to_top()
