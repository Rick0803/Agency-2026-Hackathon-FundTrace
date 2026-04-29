import streamlit as st

from views import general, fetch, analyze, report
from tools.preload import start_fetch_preload

PAGE_OPTIONS = [
    "Home",
    "Fetch",
    "Flagged",
    "Analyze",
    "Report",
]

st.set_page_config(page_title="ZombieTrace", layout="wide")

general.init_session_state()
general.enforce_workflow_page()
start_fetch_preload()

# Warm the portfolio cache once per session so "Run Portfolio Analysis" is instant
if "portfolio_cache_warmed" not in st.session_state:
    st.session_state["portfolio_cache_warmed"] = True
    try:
        from views.analyze import _cached_run_portfolio_analysis
        _cached_run_portfolio_analysis(0.0)
    except Exception:
        pass

with st.sidebar:
    st.title("ZombieTrace")
    st.caption("Track public funding. Surface ghost recipients.")
    st.divider()
    st.markdown(
        "<div style='text-align:center; font-size:1.5rem; font-weight:700; margin-bottom:0.5rem;'>Workflow</div>",
        unsafe_allow_html=True,
    )
    for option in PAGE_OPTIONS:
        button_type = "primary" if st.session_state["page"] == option else "secondary"
        disabled = not general.page_available(option)
        label = general.workflow_status_label(option)
        st.button(
            label,
            type=button_type,
            use_container_width=True,
            disabled=disabled,
            on_click=general.go_to_page,
            args=(option,),
        )
    st.caption("Greyed-out buttons mean you are not there yet. Complete the current page first.")
    st.divider()
    st.button(
        "About This Tool",
        type="primary" if st.session_state["page"] == "Zombie Context" else "secondary",
        use_container_width=True,
        on_click=general.go_to_page,
        args=("Zombie Context",),
    )

page = st.session_state["page"]
general.render_workflow_notice()

if page == "Home":
    general.render_home()
elif page == "Fetch":
    fetch.render_fetch()
elif page == "Flagged":
    fetch.render_flagged()
elif page == "Analyze":
    analyze.render_analyze()
elif page == "Report":
    report.render_report()
elif page == "Zombie Context":
    general.render_zombie_context()
