"""Streamlit frontend entry point for CI Sponsor Guide Tool."""

from __future__ import annotations

import streamlit as st

from app.components.shell import (
    WORKFLOW_STEPS,
    apply_app_chrome,
    render_next_steps,
    render_page_header,
    render_sidebar,
)
from app.state.session import init_session_state
from src.services.review_service import get_program_display_name


def main() -> None:
    """Render landing page and initialize common app state."""
    st.set_page_config(
        page_title="CI Sponsor Guide Tool",
        page_icon="📄",
        layout="wide",
    )
    init_session_state()
    apply_app_chrome()
    render_sidebar("main.py")

    render_page_header(
        "Sponsor Guide Workflow",
        "A simpler workspace for teammates to create a new sponsor guide, review source links, run updates, and export the latest files.",
        step_label="Home",
    )

    overview_col, quick_start_col = st.columns([1.5, 1], gap="large")

    with overview_col:
        st.markdown("### How the workflow works")
        st.write(
            "The process is designed to move left to right: set up a program, approve sources, generate or update the guide, then review outputs and evidence."
        )

        st.markdown("### Workflow map")
        for step in WORKFLOW_STEPS[1:]:
            with st.container(border=True):
                st.write(f"**{step['label']}**")
                st.write(step["description"])
                st.page_link(step["path"], label=f"Open {step['label']}")

    with quick_start_col:
        st.markdown("### Start here")
        st.info("Choose the path that matches the job you need to do today.")
        st.page_link("pages/1_Create_New_Program.py", label="Create a new guide workspace")
        st.page_link("pages/3_Run_Weekly_Update.py", label="Update an existing guide")
        st.page_link("pages/4_Outputs.py", label="Open outputs and downloads")

        selected_slug = str(st.session_state.get("selected_program_slug", "")).strip()
        if selected_slug:
            selected_name = str(st.session_state.get("selected_program_name", "")).strip()
            if not selected_name:
                selected_name = get_program_display_name(selected_slug)
            st.success(f"Current program: {selected_name}")
            st.caption(selected_slug)
        else:
            st.caption("A selected program will appear here after you choose one in the workflow.")

    render_next_steps(
        [
            "Use Set Up Program for a brand-new funding opportunity.",
            "Use Review Sources to approve links before creating the first draft.",
            "Use Weekly Update when a baseline guide already exists and needs a refresh.",
        ]
    )


if __name__ == "__main__":
    main()
