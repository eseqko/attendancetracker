"""Attendance Tracker — entry point.

Registers pages with st.navigation; the analysis pages only appear once setup
has produced a DataBundle. Run with: streamlit run app.py
"""

from __future__ import annotations

import sys
from pathlib import Path

# Always run the code that sits in this folder. Without this, a `pip install .`
# from an earlier version shadows updated modules in src/ and the app crashes
# with ImportError after an update.
_SRC = Path(__file__).resolve().parent / "src"
if _SRC.is_dir() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

import streamlit as st

st.set_page_config(
    page_title="Attendance Tracker",
    page_icon="🏫",
    layout="wide",
)

from ui import state, theme  # noqa: E402

theme.inject()

from ui.views import upload_setup as _setup_view  # noqa: E402

if (
    state.bundle() is None
    and not st.session_state.get("suppress_autoload")
    and not st.session_state.get("autoload_attempted")
):
    st.session_state["autoload_attempted"] = True
    with st.spinner("Loading saved setup…"):
        _setup_view.restore_saved_setup()
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
        saved_on = st.session_state.get("loaded_from_profile")
        if saved_on:
            st.caption(f"Saved setup from {saved_on} — change it in Upload & Setup")
    st.caption(
        "Data stays on this computer and is never sent anywhere."
    )

st.navigation(pages).run()
