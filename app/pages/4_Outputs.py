"""Page: output artifacts and preview."""

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
from app.components.tables import show_table
from app.state.session import init_session_state
from src.services.output_service import load_outputs, read_artifact_bytes
from src.services.review_service import get_program_display_name, list_program_slugs


st.set_page_config(page_title="Outputs", layout="wide")
init_session_state()
apply_app_chrome()
render_sidebar("pages/4_Outputs.py")
render_page_header(
    "Preview and Download Outputs",
    "View the guide as soon as the first draft is generated. Preview the markdown and download output files your team needs to share.",
    step_label="Step 3",
)

st.markdown("### Choose a program")
selected_slug = select_program_form(list_program_slugs(), key_prefix="outputs")
if selected_slug:
    st.session_state["selected_program_slug"] = selected_slug
    st.session_state["selected_program_name"] = get_program_display_name(selected_slug)
if not selected_slug:
    st.stop()

result = load_outputs(selected_slug)
if not result["ok"]:
    st.error(result["error"])
    if result.get("detail"):
        st.caption(result["detail"])
    st.stop()

st.markdown("### Available files")
st.write(f"**Output directory:** `{result['output_dir']}`")
if result.get("remote_program_url"):
    st.markdown(f"[Open persisted program files]({result['remote_program_url']})")
if result.get("note"):
    st.info(result["note"])
if result.get("baseline_path"):
    st.caption(f"Baseline guide: `{result['baseline_path']}`")
if result.get("draft_path"):
    st.caption(f"Pre-baseline draft: `{result['draft_path']}`")
show_table(result["artifacts"], title="Artifact Metadata")

if result["markdown_content"]:
    markdown_preview(result["markdown_content"], title="Latest Markdown")
else:
    st.info("No markdown artifact available to preview.")

st.markdown("### Downloads")
if not result["artifacts"]:
    st.info("No artifacts available.")
else:
    for artifact in result["artifacts"]:
        file_name = artifact["name"]
        file_path = artifact["path"]
        mime = "application/octet-stream"
        if file_name.endswith(".md"):
            mime = "text/markdown"
        elif file_name.endswith(".pdf"):
            mime = "application/pdf"
        elif file_name.endswith(".docx"):
            mime = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        elif file_name.endswith(".json"):
            mime = "application/json"

        st.download_button(
            label=f"Download {file_name}",
            data=read_artifact_bytes(file_path),
            file_name=file_name,
            mime=mime,
            key=f"download_{file_name}",
            use_container_width=True,
        )
