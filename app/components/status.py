"""Status and result display helpers."""

from __future__ import annotations

import streamlit as st


def render_outcome(ok: bool, success_text: str, error_text: str) -> None:
    """Render a success/error banner based on an operation outcome."""
    if ok:
        st.success(success_text)
    else:
        st.error(error_text)
