"""Attendance Tracker — entry point.

Registers pages with st.navigation; the analysis pages only appear once setup
has produced a DataBundle. Run with: streamlit run app.py
"""

from __future__ import annotations

import streamlit as st

st.set_page_config(
    page_title="Attendance Tracker",
    page_icon="🏫",
    layout="wide",
)

from ui import state, theme  # noqa: E402

theme.inject()
from ui.views import (  # noqa: E402
    breakdowns,
    cohorts,
    overview,
    patterns,
    student,
    upload_setup,
)

setup_page = st.Page(
    upload_setup.render, title="Upload & Setup", icon=":material/upload_file:",
    url_path="setup", default=True,
)
pages = [setup_page]
registry = {"setup": setup_page}

if state.bundle() is not None:
    overview_page = st.Page(
        overview.render, title="Overview", icon=":material/dashboard:",
        url_path="overview",
    )
    breakdowns_page = st.Page(
        breakdowns.render, title="Breakdowns", icon=":material/analytics:",
        url_path="breakdowns",
    )
    student_page = st.Page(
        student.render, title="Student", icon=":material/person:",
        url_path="student",
    )
    cohorts_page = st.Page(
        cohorts.render, title="Cohorts", icon=":material/groups:",
        url_path="cohorts",
    )
    patterns_page = st.Page(
        patterns.render, title="Patterns", icon=":material/calendar_month:",
        url_path="patterns",
    )
    pages += [
        overview_page, breakdowns_page, student_page, cohorts_page, patterns_page,
    ]
    registry.update(
        overview=overview_page,
        breakdowns=breakdowns_page,
        student=student_page,
        cohorts=cohorts_page,
        patterns=patterns_page,
    )

st.session_state["_pages"] = registry

with st.sidebar:
    bundle = state.bundle()
    if bundle is not None:
        matched = int(bundle.metrics["matched"].sum())
        st.caption(f"{matched} caseload students loaded")
    st.caption(
        "Data stays on this computer, in memory only — nothing is uploaded "
        "or saved."
    )

st.navigation(pages).run()
