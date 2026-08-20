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

from ui import state  # noqa: E402
from ui.views import cohorts, overview, patterns, student, upload_setup  # noqa: E402

setup_page = st.Page(
    upload_setup.render, title="Upload & Setup", icon="📥", url_path="setup",
    default=True,
)
pages = [setup_page]
registry = {"setup": setup_page}

if state.bundle() is not None:
    overview_page = st.Page(
        overview.render, title="Overview", icon="📊", url_path="overview"
    )
    student_page = st.Page(
        student.render, title="Student", icon="🧑‍🎓", url_path="student"
    )
    cohorts_page = st.Page(
        cohorts.render, title="Cohorts", icon="👥", url_path="cohorts"
    )
    patterns_page = st.Page(
        patterns.render, title="Patterns", icon="📅", url_path="patterns"
    )
    pages += [overview_page, student_page, cohorts_page, patterns_page]
    registry.update(
        overview=overview_page,
        student=student_page,
        cohorts=cohorts_page,
        patterns=patterns_page,
    )

st.session_state["_pages"] = registry

with st.sidebar:
    bundle = state.bundle()
    if bundle is not None:
        matched = int(bundle.metrics["matched"].sum())
        st.caption(f"✅ {matched} caseload students loaded")
    st.caption(
        "🔒 Data stays on this computer, in memory only — nothing is uploaded "
        "or saved."
    )

st.navigation(pages).run()
