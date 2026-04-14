"""Streamlit frontend entry point for CI Sponsor Guide Tool."""

from __future__ import annotations

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.runtime import bootstrap  # noqa: E402
bootstrap()

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
            "The process is designed to move left to right: set up a program, approve sources and generate the first draft with citations, then view outputs. Use Weekly Update later when sponsor pages change."
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
        st.page_link("pages/2_Review_Sources.py", label="Review sources and generate first draft")
        st.page_link("pages/4_Outputs.py", label="Preview and download outputs")
        st.page_link("pages/3_Run_Weekly_Update.py", label="Refresh an existing guide (weekly update)")

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
            "Use Review & Generate to approve links, create the first draft with citations, and get output files.",
            "Use View Outputs to preview and download the guide right after generation.",
            "Use Weekly Update only when sponsor pages have changed and you need to refresh an existing guide.",
        ]
    )


if __name__ == "__main__":
    main()
