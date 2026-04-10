"""Session state defaults for Streamlit pages."""

from __future__ import annotations

import streamlit as st


def init_session_state() -> None:
    """Initialize shared session keys once per app session."""
    defaults = {
        "selected_program_slug": "",
        "selected_program_name": "",
        "last_run_result": None,
        "active_review_context": {},
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value
