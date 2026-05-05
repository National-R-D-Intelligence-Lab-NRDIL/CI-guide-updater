"""Page: program portfolio dashboard with search and pagination."""

from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.runtime import bootstrap  # noqa: E402
bootstrap()

import streamlit as st

from app.components.shell import apply_app_chrome, render_page_header, render_sidebar
from app.state.session import init_session_state
from src.services.review_service import get_program_display_name, list_program_records

_PROGRAMS_PER_PAGE = 10


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


st.set_page_config(page_title="Program Dashboard", layout="wide")
init_session_state()
apply_app_chrome()
render_sidebar("pages/0_Program_Dashboard.py")
render_page_header(
    "Program Dashboard",
    "Browse, search, and select from all program workspaces.",
    step_label="Dashboard",
)

records = list_program_records()
if not records:
    st.info("No programs yet. Create one using Set Up Program.")
    st.page_link("pages/1_Create_New_Program.py", label="Go to Set Up Program")
    st.stop()

programs = [_load_program_status(r["slug"]) for r in records]

search_query = st.text_input(
    "Filter programs",
    placeholder="Type to filter by name…",
    label_visibility="collapsed",
    key="program_search",
)

if search_query:
    query_lower = search_query.lower()
    programs = [
        p for p in programs
        if query_lower in p["display_name"].lower() or query_lower in p["slug"]
    ]

if st.session_state.get("_prev_search") != search_query:
    st.session_state["_prev_search"] = search_query
    st.session_state["dashboard_page"] = 0

total = len(programs)
total_pages = max(1, -(-total // _PROGRAMS_PER_PAGE))

page = st.session_state.get("dashboard_page", 0)
page = min(page, total_pages - 1)

start = page * _PROGRAMS_PER_PAGE
page_programs = programs[start : start + _PROGRAMS_PER_PAGE]

st.markdown(f"### All Programs ({total})")

cols = st.columns([2.5, 1, 1, 1, 1.5])
cols[0].markdown("**Program**")
cols[1].markdown("**Sources**")
cols[2].markdown("**Guide**")
cols[3].markdown("**Output**")
cols[4].markdown("**Last Updated**")

for prog in page_programs:
    cols = st.columns([2.5, 1, 1, 1, 1.5])
    if cols[0].button(prog["display_name"], key=f"select_{prog['slug']}", use_container_width=True):
        st.session_state["selected_program_slug"] = prog["slug"]
        st.session_state["selected_program_name"] = prog["display_name"]
        st.rerun()
    cols[1].write(str(prog["source_count"]))
    cols[2].write("Yes" if prog["has_guide"] else "—")
    cols[3].write("Yes" if prog["has_output"] else "—")
    cols[4].write(prog["last_updated"] or "—")

if total_pages > 1:
    nav_left, nav_info, nav_right = st.columns([1, 2, 1])
    with nav_left:
        if st.button("← Previous", disabled=(page == 0), key="dash_prev"):
            st.session_state["dashboard_page"] = page - 1
            st.rerun()
    with nav_info:
        st.markdown(
            f"<div style='text-align:center;padding-top:6px'>Page {page + 1} of {total_pages}</div>",
            unsafe_allow_html=True,
        )
    with nav_right:
        if st.button("Next →", disabled=(page >= total_pages - 1), key="dash_next"):
            st.session_state["dashboard_page"] = page + 1
            st.rerun()

selected_slug = str(st.session_state.get("selected_program_slug", "")).strip()
if selected_slug:
    st.markdown("---")
    selected_name = str(st.session_state.get("selected_program_name", "")).strip()
    if not selected_name:
        selected_name = get_program_display_name(selected_slug)
    st.success(f"Selected program: **{selected_name}**")
    st.page_link("pages/2_Review_Sources.py", label="Continue to Review Sources →")
