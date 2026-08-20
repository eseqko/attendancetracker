"""Session-state management. All uploaded student data lives in
st.session_state only — nothing is ever written to disk by the app."""

from __future__ import annotations

import streamlit as st

from attendance_tracker.model import DataBundle

#: Setup-wizard keys all share this prefix so Start Over can clear them.
SETUP_PREFIX = "setup_"
BUNDLE_KEY = "bundle"
BUNDLE_WARNINGS_KEY = "bundle_warnings"
SELECTED_STUDENT_KEY = "selected_student_id"


def bundle() -> DataBundle | None:
    return st.session_state.get(BUNDLE_KEY)


def set_bundle(new_bundle: DataBundle, warnings: list[str]) -> None:
    st.session_state[BUNDLE_KEY] = new_bundle
    st.session_state[BUNDLE_WARNINGS_KEY] = warnings


def bundle_warnings() -> list[str]:
    return st.session_state.get(BUNDLE_WARNINGS_KEY, [])


def get_setup(key: str, default=None):
    return st.session_state.get(SETUP_PREFIX + key, default)


def set_setup(key: str, value) -> None:
    st.session_state[SETUP_PREFIX + key] = value


def clear_setup_from(keys: list[str]) -> None:
    """Invalidate downstream wizard state when an earlier section is edited."""
    for key in keys:
        st.session_state.pop(SETUP_PREFIX + key, None)
    st.session_state.pop(BUNDLE_KEY, None)
    st.session_state.pop(BUNDLE_WARNINGS_KEY, None)


def clear_all() -> None:
    """Start over: drop every setup key, the bundle, and selections."""
    for key in list(st.session_state.keys()):
        if key.startswith(SETUP_PREFIX) or key in (
            BUNDLE_KEY,
            BUNDLE_WARNINGS_KEY,
            SELECTED_STUDENT_KEY,
        ):
            del st.session_state[key]


def selected_student() -> str | None:
    return st.session_state.get(SELECTED_STUDENT_KEY)


def select_student(student_id: str) -> None:
    st.session_state[SELECTED_STUDENT_KEY] = student_id
