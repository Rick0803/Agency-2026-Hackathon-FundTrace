import streamlit as st

from views import general, fetch, analyze, report

PAGE_OPTIONS = [
    "Home",
    "Fetch",
    "Flagged",
    "Analyze",
    "Report",
]

st.set_page_config(page_title="Public Funding Risk Intelligence", layout="wide")

general.init_session_state()

with st.sidebar:
    st.title("Risk Intelligence")
    st.caption("CRA + federal funding review")
    st.divider()
    for option in PAGE_OPTIONS:
        button_type = "primary" if st.session_state["page"] == option else "secondary"
        st.button(
            option,
            type=button_type,
            use_container_width=True,
            on_click=general.go_to_page,
            args=(option,),
        )

page = st.session_state["page"]

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
