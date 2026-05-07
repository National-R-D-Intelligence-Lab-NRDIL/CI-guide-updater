"""Page: focused output markdown preview with dashboard back navigation."""

from __future__ import annotations

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.runtime import bootstrap  # noqa: E402
bootstrap()

import streamlit as st

from app.components.preview import markdown_preview
from app.components.shell import apply_app_chrome, render_page_header, render_sidebar
from app.state.session import init_session_state
from src.services.review_service import get_program_display_name


def _load_output_markdown_preview(slug: str) -> str:
    """Read latest output markdown for focused preview page."""
    output_md = Path("programs") / slug / "output" / "sponsor_guide_updated.md"
    if not output_md.exists():
        return ""
    try:
        return output_md.read_text(encoding="utf-8")
    except Exception:
        return ""


st.set_page_config(page_title="Output Preview", layout="wide")
init_session_state()
apply_app_chrome()
render_sidebar("pages/6_Output_Preview.py")
render_page_header(
    "Output Preview",
    "Read the latest generated markdown for one program and quickly return to the dashboard.",
    step_label="Preview",
)

selected_slug = str(st.session_state.get("dashboard_preview_slug", "")).strip()
if not selected_slug:
    selected_slug = str(st.session_state.get("selected_program_slug", "")).strip()

if not selected_slug:
    st.info("No program selected for preview.")
    st.page_link("pages/0_Program_Dashboard.py", label="← Back to Program Dashboard")
    st.stop()

selected_name = str(st.session_state.get("dashboard_preview_name", "")).strip()
if not selected_name:
    selected_name = str(st.session_state.get("selected_program_name", "")).strip()
if not selected_name:
    selected_name = get_program_display_name(selected_slug)

top_left, top_right = st.columns([1, 2])
with top_left:
    if st.button("← Back to Program Dashboard", use_container_width=True):
        st.switch_page("pages/0_Program_Dashboard.py")
with top_right:
    st.page_link("pages/2_Review_Sources.py", label="Continue to Review Sources →")

st.markdown(f"### {selected_name}")
st.caption(selected_slug)

preview_markdown = _load_output_markdown_preview(selected_slug)
if preview_markdown:
    markdown_preview(preview_markdown, title="Latest output markdown")
else:
    st.info("No generated output markdown found yet for this program.")
    st.page_link("pages/4_Outputs.py", label="Open full output details →")
