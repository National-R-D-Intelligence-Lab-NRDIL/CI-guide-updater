"""Reusable Streamlit form controls."""

from __future__ import annotations

from typing import Sequence

import streamlit as st

from src.services.review_service import get_program_display_name


def select_program_form(slugs: Sequence[str], key_prefix: str = "program") -> str:
    """Render a standard program selector and return selected slug."""
    if not slugs:
        st.info("No programs found in `programs/` yet.")
        return ""
    options = sorted(list(slugs), key=lambda slug: get_program_display_name(slug).lower())
    selected_slug = str(st.session_state.get("selected_program_slug", "")).strip()
    query_key = f"{key_prefix}_search"
    query = str(st.session_state.get(query_key, "")).strip().lower()
    if query:
        filtered = [
            slug
            for slug in options
            if query in slug.lower() or query in get_program_display_name(slug).lower()
        ]
    else:
        filtered = options

    if not filtered:
        st.warning("No programs match that search. Try part of the program name or slug.")
        st.session_state["selected_program_slug"] = ""
        st.session_state["selected_program_name"] = ""
        return ""

    if selected_slug not in filtered:
        selected_slug = filtered[0]
    default_index = filtered.index(selected_slug)

    selector_key = f"{key_prefix}_selector"
    current_choice = str(st.session_state.get(selector_key, "")).strip()
    if current_choice and current_choice not in filtered:
        st.session_state.pop(selector_key, None)

    st.text_input(
        "Search programs",
        placeholder="Type part of a program name or slug",
        key=query_key,
        help="Filter the list before choosing a workspace.",
    )
    chosen = st.selectbox(
        "Program workspace",
        options=filtered,
        index=default_index,
        key=selector_key,
        format_func=lambda slug: get_program_display_name(slug),
        help="Choose the workspace to operate on. You can search first, then pick the readable program name.",
    )
    st.session_state["selected_program_slug"] = chosen
    st.session_state["selected_program_name"] = get_program_display_name(chosen)
    return chosen
