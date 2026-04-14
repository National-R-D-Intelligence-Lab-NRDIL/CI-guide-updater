"""Page: audit and evidence traceability."""

from __future__ import annotations

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.runtime import bootstrap  # noqa: E402
bootstrap()

import streamlit as st

from app.components.shell import apply_app_chrome, render_page_header, render_sidebar
from app.components.forms import select_program_form
from app.components.tables import show_table
from app.state.session import init_session_state
from src.services.audit_service import load_audit_data
from src.services.review_service import get_program_display_name, list_program_slugs


st.set_page_config(page_title="Audit / Evidence", layout="wide")
init_session_state()
apply_app_chrome()
render_sidebar("pages/5_Audit_Evidence.py")
render_page_header(
    "Audit Changes and Evidence",
    "Review what changed in the guide, inspect citation links, and trace evidence back to the supporting sources.",
    step_label="Step 5",
)

st.markdown("### Choose a program")
selected_slug = select_program_form(list_program_slugs(), key_prefix="audit")
if selected_slug:
    st.session_state["selected_program_slug"] = selected_slug
    st.session_state["selected_program_name"] = get_program_display_name(selected_slug)
if not selected_slug:
    st.stop()

result = load_audit_data(selected_slug)
if not result["ok"]:
    st.error(result["error"])
    if result.get("detail"):
        st.caption(result["detail"])
    st.stop()

if result.get("remote_program_url"):
    st.markdown(f"[Open persisted program files]({result['remote_program_url']})")

tabs = st.tabs(["Guide Diff", "Citations", "Evidence Map"])

with tabs[0]:
    st.write(f"Baseline: `{result['baseline_path']}`")
    st.write(f"Updated: `{result['updated_path']}`")
    if result["diff_text"]:
        st.code(result["diff_text"])
    else:
        st.info("No diff available yet. Run weekly update first.")

with tabs[1]:
    show_table(result["citations"], title="Citation Links")
    if not result["citations"]:
        st.info("No inline citation links found in updated markdown.")

with tabs[2]:
    st.write(f"Evidence file: `{result['evidence_path']}`")
    if result["evidence"]:
        show_table(
            [
                {
                    "line_id": item.get("line_id", ""),
                    "claim": item.get("claim", ""),
                    "sources": ", ".join(item.get("sources", [])),
                    "urls": ", ".join(item.get("urls", [])),
                }
                for item in result["evidence"]
            ],
            title="Evidence Summary",
        )
        with st.expander("Raw Evidence JSON", expanded=False):
            st.json(result["evidence"])
    else:
        st.info("No evidence map found.")
