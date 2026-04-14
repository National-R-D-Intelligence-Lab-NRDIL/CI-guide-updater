"""Page: run existing weekly update pipeline."""

from __future__ import annotations

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.runtime import bootstrap  # noqa: E402
bootstrap()

import streamlit as st

from app.components.shell import apply_app_chrome, render_page_header, render_sidebar
from app.components.forms import select_program_form
from app.components.status import render_storage_status
from app.state.session import init_session_state
from src.services.pipeline_service import run_weekly_update
from src.services.review_service import get_program_display_name, list_program_slugs


st.set_page_config(page_title="Run Weekly Update", layout="wide")
init_session_state()
apply_app_chrome()
render_sidebar("pages/3_Run_Weekly_Update.py")
render_page_header(
    "Weekly Guide Update",
    "Refresh an existing sponsor guide when source pages have changed. This is optional until you need to pick up website updates after the initial draft.",
    step_label="Step 4",
)
st.info("Weekly Update requires a baseline `guide.md`. Generate the first draft and promote it in **Review & Generate** before running updates here.")

st.markdown("### Choose the program to update")
st.caption("Select a program that already has a promoted baseline guide.")
selected_slug = select_program_form(list_program_slugs(), key_prefix="pipeline")
if selected_slug:
    st.session_state["selected_program_slug"] = selected_slug
    st.session_state["selected_program_name"] = get_program_display_name(selected_slug)
if not selected_slug:
    st.stop()

st.divider()
st.markdown("### What do you want to update?")
update_mode = st.radio(
    "Choose an update mode",
    options=["full", "citations_only"],
    format_func=lambda x: {
        "full": "Full update — check sources for changes and update the guide",
        "citations_only": "Refresh citations only — regenerate citations without re-scraping sources",
    }[x],
    index=0,
    label_visibility="collapsed",
)

refresh_citations_only = update_mode == "citations_only"
with_citations = True

if not refresh_citations_only:
    refresh_citations = st.checkbox(
        "Also refresh citations even if no source changes are found",
        value=False,
    )
else:
    refresh_citations = True

st.divider()
st.markdown("### Review before running")
with st.container(border=True):
    mode_label = (
        "refresh citations on the current guide"
        if refresh_citations_only
        else "check all sources for updates and regenerate the guide"
    )
    st.warning(f"This will **{mode_label}** for the selected workspace.")
    confirm = st.checkbox(
        "I confirm I want to run the update now",
        value=False,
        help="Use this guard to avoid accidental or repeated runs.",
    )

st.divider()
run_clicked = st.button(
    "Run Weekly Update",
    disabled=not confirm,
    use_container_width=True,
)

if run_clicked:
    if not confirm:
        st.warning("Please confirm execution before running the update.")
        st.stop()

    with st.status("Running pipeline...", expanded=True) as status:
        result = run_weekly_update(
            selected_slug,
            with_citations=with_citations,
            refresh_citations=refresh_citations,
            refresh_citations_only=refresh_citations_only,
        )
        if result["ok"]:
            status.update(label="Pipeline finished.", state="complete")
        else:
            status.update(label="Pipeline failed.", state="error")

    if not result["ok"]:
        st.error(result["error"])
        if result.get("detail"):
            st.caption(result["detail"])
        st.stop()

    st.session_state["last_run_result"] = result
    st.success("Weekly update executed.")
    st.write(f"**Program:** `{result['program_slug']}`")
    st.write(f"**Guide input:** `{result['guide_path']}`")
    st.write(f"**Sources:** `{result['sources_path']}`")
    st.write(f"**Output directory:** `{result['output_dir']}`")

    col1, col2, col3 = st.columns(3)
    col1.metric("Changed sources", result["changed_sources_count"])
    col2.metric("Changed sections", result["changed_sections_count"])
    col3.metric("Artifacts produced", len(result["artifacts"]))

    if result["artifacts"]:
        st.subheader("Artifacts")
        for artifact in result["artifacts"]:
            st.code(artifact)

    render_storage_status(result.get("storage"))
    with st.expander("Execution logs", expanded=False):
        st.code(result["logs"] or "(no logs)")
