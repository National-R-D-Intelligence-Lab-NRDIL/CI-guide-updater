"""Reusable table rendering helpers."""

from __future__ import annotations

from typing import Any

import pandas as pd
import streamlit as st


def show_table(rows: list[dict[str, Any]], title: str = "") -> None:
    """Render a dataframe for a list of dictionaries."""
    if title:
        st.subheader(title)
    if not rows:
        st.info("No records to display.")
        return
    st.dataframe(pd.DataFrame(rows), use_container_width=True)
