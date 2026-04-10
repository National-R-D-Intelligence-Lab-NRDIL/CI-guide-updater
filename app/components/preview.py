"""Preview helpers for markdown and structured JSON."""

from __future__ import annotations

import json
from typing import Any

import streamlit as st


def markdown_preview(content: str, title: str = "Markdown Preview") -> None:
    """Render markdown preview in an expander."""
    with st.expander(title, expanded=True):
        st.markdown(content)


def json_preview(data: Any, title: str = "JSON Preview") -> None:
    """Render JSON-style preview in an expander."""
    with st.expander(title, expanded=False):
        st.code(json.dumps(data, indent=2), language="json")
