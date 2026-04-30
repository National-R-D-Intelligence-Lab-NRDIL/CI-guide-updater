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
from app.components.preview import markdown_preview
from app.components.status import render_storage_status
from app.state.session import init_session_state
from src.services.output_service import load_outputs
from src.services.pipeline_service import run_weekly_update
from src.services.review_service import (
    add_approved_pdf_source,
    add_approved_url_source,
    get_program_display_name,
    list_program_slugs,
    load_approved_sources,
    remove_approved_source,
    update_approved_source,
)


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
st.caption("Each run uses the latest generated guide as its starting point when one exists, then writes both latest files and timestamped history files.")

st.markdown("### Choose the program to update")
st.caption("Select a program that already has a promoted baseline guide.")
selected_slug = select_program_form(list_program_slugs(), key_prefix="pipeline")
if selected_slug:
    st.session_state["selected_program_slug"] = selected_slug
    st.session_state["selected_program_name"] = get_program_display_name(selected_slug)
if not selected_slug:
    st.stop()

source_feedback = str(st.session_state.pop("weekly_source_feedback", "")).strip()
if source_feedback:
    st.success(source_feedback)

st.divider()
st.markdown("### Sources for this update")
st.caption("Add, remove, or adjust approved public sources before running the weekly update.")
sources_result = load_approved_sources(selected_slug)
if not sources_result["ok"]:
    st.error(sources_result["error"])
    if sources_result.get("detail"):
        st.caption(sources_result["detail"])
    st.stop()

sources = sources_result["sources"]
st.write(f"**Approved source file:** `{sources_result['path']}`")
st.metric("Approved sources", sources_result["count"])

source_rows = []
for src in sources:
    source_rows.append(
        {
            "name": src.get("name", ""),
            "title": src.get("title", ""),
            "url": src.get("url", ""),
            "file_path": src.get("file_path", ""),
            "sections": ", ".join(src.get("sections", [])),
            "origin": src.get("source_origin", ""),
        }
    )
with st.expander("View current approved sources", expanded=False):
    st.dataframe(source_rows, use_container_width=True, hide_index=True)

with st.expander("Modify source list before update", expanded=False):
    st.markdown("#### Edit or remove an existing source")
    source_names = [str(src.get("name", "")) for src in sources]
    chosen_source = st.selectbox(
        "Source to edit",
        options=source_names,
        format_func=lambda name: next(
            (
                str(src.get("title") or src.get("url") or src.get("file_path") or name)
                for src in sources
                if str(src.get("name", "")) == name
            ),
            name,
        ),
        key="weekly_edit_source",
    )
    selected_source = next((src for src in sources if str(src.get("name", "")) == chosen_source), {})
    with st.form("weekly_edit_source_form"):
        edit_title = st.text_input(
            "Title / label",
            value=str(selected_source.get("title", "")),
        )
        edit_url = st.text_input(
            "URL",
            value=str(selected_source.get("url", "")),
            disabled=bool(str(selected_source.get("file_path", "")).strip()),
            help="Uploaded PDF sources keep their file path; URL editing is for web sources.",
        )
        edit_sections = st.text_input(
            "Mapped sections",
            value=", ".join(selected_source.get("sections", [])),
            help="Comma-separated section names, such as Eligibility, Key Dates.",
        )
        edit_col, remove_col = st.columns(2)
        save_source_clicked = edit_col.form_submit_button("Save Source Changes", use_container_width=True)
        remove_source_clicked = remove_col.form_submit_button("Remove Source", use_container_width=True)

    if save_source_clicked:
        updated_source = update_approved_source(
            selected_slug,
            chosen_source,
            title=edit_title,
            url=edit_url,
            sections_text=edit_sections,
        )
        if updated_source["ok"]:
            st.session_state["weekly_source_feedback"] = "Source list updated."
            st.rerun()
        else:
            st.error(updated_source["error"])
            if updated_source.get("detail"):
                st.caption(updated_source["detail"])

    if remove_source_clicked:
        removed_source = remove_approved_source(selected_slug, chosen_source)
        if removed_source["ok"]:
            st.session_state["weekly_source_feedback"] = "Source removed from the approved list."
            st.rerun()
        else:
            st.error(removed_source["error"])
            if removed_source.get("detail"):
                st.caption(removed_source["detail"])

    st.markdown("#### Add a public URL source")
    with st.form("weekly_add_url_source_form", clear_on_submit=True):
        add_url = st.text_input("URL", placeholder="https://...")
        add_title = st.text_input("Title / label", placeholder="Program FAQ")
        add_sections = st.text_input(
            "Mapped sections",
            placeholder="Eligibility, Key Dates",
            help="Optional comma-separated guide sections.",
        )
        add_url_clicked = st.form_submit_button("Add URL Source", use_container_width=True)

    if add_url_clicked:
        added_source = add_approved_url_source(
            selected_slug,
            url=add_url,
            title=add_title,
            sections_text=add_sections,
        )
        if added_source["ok"]:
            st.session_state["weekly_source_feedback"] = "URL source added to the approved list."
            st.rerun()
        else:
            st.error(added_source["error"])
            if added_source.get("detail"):
                st.caption(added_source["detail"])

    st.markdown("#### Upload a public PDF source")
    with st.form("weekly_add_pdf_source_form", clear_on_submit=True):
        add_pdf = st.file_uploader(
            "PDF file",
            type=["pdf"],
            accept_multiple_files=False,
            help="The PDF must be public and safe to send to the LLM.",
        )
        add_pdf_title = st.text_input("PDF title / label", placeholder="Funding announcement PDF")
        add_pdf_sections = st.text_input(
            "PDF mapped sections",
            placeholder="Application Requirements",
        )
        add_pdf_clicked = st.form_submit_button("Upload PDF Source", use_container_width=True)

    if add_pdf_clicked:
        if add_pdf is None:
            st.error("Please choose a PDF file to upload.")
        else:
            added_pdf = add_approved_pdf_source(
                selected_slug,
                file_name=add_pdf.name,
                file_bytes=add_pdf.getvalue(),
                title=add_pdf_title,
                sections_text=add_pdf_sections,
            )
            if added_pdf["ok"]:
                st.session_state["weekly_source_feedback"] = "PDF source added to the approved list."
                st.rerun()
            else:
                st.error(added_pdf["error"])
                if added_pdf.get("detail"):
                    st.caption(added_pdf["detail"])

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
    st.caption("Private-data checks run before source text is sent to the LLM.")
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
    st.write(f"**Compared against guide:** `{result['guide_path']}`")
    st.write(f"**Sources:** `{result['sources_path']}`")
    st.write(f"**Output directory:** `{result['output_dir']}`")

    col1, col2, col3 = st.columns(3)
    col1.metric("Changed sources", result["changed_sources_count"])
    col2.metric("Changed sections", result["changed_sections_count"])
    col3.metric("Artifacts produced", len(result["artifacts"]))

    if result["artifacts"]:
        st.subheader("Artifacts saved by this run")
        for artifact in result["artifacts"]:
            st.code(artifact)

    outputs = load_outputs(selected_slug)
    if outputs.get("ok") and outputs.get("markdown_content"):
        markdown_preview(outputs["markdown_content"], title="Updated Guide Preview")

    render_storage_status(result.get("storage"))
    with st.expander("Execution logs", expanded=False):
        st.code(result["logs"] or "(no logs)")
