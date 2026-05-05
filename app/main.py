"""Streamlit frontend entry point for CI Sponsor Guide Tool."""

from __future__ import annotations

import json
import sys
from datetime import datetime
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
from src.services.review_service import get_program_display_name, list_program_records


def _load_program_status(slug: str) -> dict:
    """Gather status info for a single program."""
    program_dir = Path("programs") / slug
    status: dict = {
        "slug": slug,
        "display_name": get_program_display_name(slug),
        "source_count": 0,
        "has_guide": False,
        "has_output": False,
        "last_updated": None,
    }

    sources_path = program_dir / "sources.json"
    if sources_path.exists():
        try:
            sources = json.loads(sources_path.read_text(encoding="utf-8"))
            status["source_count"] = len(sources) if isinstance(sources, list) else 0
        except Exception:
            pass

    guide_path = program_dir / "guide.md"
    status["has_guide"] = guide_path.exists()

    output_dir = program_dir / "output"
    output_md = output_dir / "sponsor_guide_updated.md"
    status["has_output"] = output_md.exists()

    state_path = program_dir / "state.json"
    if state_path.exists():
        try:
            state = json.loads(state_path.read_text(encoding="utf-8"))
            timestamps = [
                entry.get("last_checked", "")
                for entry in state.values()
                if isinstance(entry, dict) and entry.get("last_checked")
            ]
            if timestamps:
                latest = max(timestamps)
                try:
                    dt = datetime.fromisoformat(latest.replace("Z", "+00:00"))
                    status["last_updated"] = dt.strftime("%b %d, %Y")
                except Exception:
                    status["last_updated"] = latest[:10]
        except Exception:
            pass

    if not status["last_updated"] and status["has_output"]:
        try:
            mtime = output_md.stat().st_mtime
            status["last_updated"] = datetime.fromtimestamp(mtime).strftime("%b %d, %Y")
        except Exception:
            pass

    return status


def _render_portfolio_dashboard() -> None:
    """Render the program portfolio overview."""
    records = list_program_records()
    if not records:
        st.info("No programs yet. Create one using Set Up Program.")
        return

    st.markdown(f"### All Programs ({len(records)})")

    programs = [_load_program_status(r["slug"]) for r in records]

    cols = st.columns([2.5, 1, 1, 1, 1.5])
    cols[0].markdown("**Program**")
    cols[1].markdown("**Sources**")
    cols[2].markdown("**Guide**")
    cols[3].markdown("**Output**")
    cols[4].markdown("**Last Updated**")

    for prog in programs:
        cols = st.columns([2.5, 1, 1, 1, 1.5])
        if cols[0].button(prog["display_name"], key=f"select_{prog['slug']}", use_container_width=True):
            st.session_state["selected_program_slug"] = prog["slug"]
            st.session_state["selected_program_name"] = prog["display_name"]
            st.rerun()
        cols[1].write(str(prog["source_count"]))
        cols[2].write("Yes" if prog["has_guide"] else "—")
        cols[3].write("Yes" if prog["has_output"] else "—")
        cols[4].write(prog["last_updated"] or "—")


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

    _render_portfolio_dashboard()

    st.markdown("---")

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
