"""Shared layout helpers for the Streamlit app."""

from __future__ import annotations

import html
from typing import Iterable

import streamlit as st

from src.services.review_service import get_program_display_name


WORKFLOW_STEPS = [
    {
        "label": "Home",
        "path": "main.py",
        "description": "See the workflow and jump into the right task.",
    },
    {
        "label": "1. Set Up Program",
        "path": "pages/1_Create_New_Program.py",
        "description": "Create a new workspace and discover candidate sources.",
    },
    {
        "label": "2. Review & Generate",
        "path": "pages/2_Review_Sources.py",
        "description": "Approve sources, generate the first draft with citations, and get output files.",
    },
    {
        "label": "3. View Outputs",
        "path": "pages/4_Outputs.py",
        "description": "Preview and download the latest guide files.",
    },
    {
        "label": "4. Weekly Update",
        "path": "pages/3_Run_Weekly_Update.py",
        "description": "Refresh an existing guide when source pages change.",
    },
    {
        "label": "5. Audit Evidence",
        "path": "pages/5_Audit_Evidence.py",
        "description": "Check diffs, citations, and evidence traceability.",
    },
]


def apply_app_chrome() -> None:
    """Apply shared styling for a calmer, task-first interface."""
    st.markdown(
        """
        <style>
        [data-testid="stSidebarNav"] {
            display: none;
        }

        .block-container {
            padding-top: 2rem;
            padding-bottom: 3rem;
        }

        div[data-testid="stVerticalBlock"] div.app-hero {
            background: linear-gradient(135deg, #f5efe4 0%, #ffffff 58%, #e8f1ec 100%);
            border: 1px solid rgba(82, 102, 89, 0.18);
            border-radius: 24px;
            padding: 1.4rem 1.5rem;
            margin-bottom: 1.25rem;
        }

        .app-eyebrow {
            color: #5c5f52;
            font-size: 0.82rem;
            font-weight: 700;
            letter-spacing: 0.08em;
            text-transform: uppercase;
            margin-bottom: 0.4rem;
        }

        .app-hero h1 {
            color: #1e3127;
            font-size: 2rem;
            line-height: 1.15;
            margin: 0;
        }

        .app-hero p {
            color: #3f463d;
            font-size: 1rem;
            margin: 0.7rem 0 0;
            max-width: 56rem;
        }

        div[data-testid="stSidebarUserContent"] {
            padding-top: 0.5rem;
        }

        .workflow-note {
            background: #f5f7f1;
            border: 1px solid rgba(82, 102, 89, 0.18);
            border-radius: 16px;
            padding: 0.9rem 1rem;
            color: #334038;
            font-size: 0.95rem;
            margin-bottom: 0.8rem;
        }

        .program-card {
            background: linear-gradient(180deg, #f6f8f4 0%, #edf2ea 100%);
            border: 1px solid rgba(82, 102, 89, 0.18);
            border-radius: 16px;
            padding: 0.95rem 1rem;
            margin-bottom: 0.8rem;
        }

        .program-card-label {
            display: block;
            font-size: 0.78rem;
            font-weight: 700;
            letter-spacing: 0.08em;
            text-transform: uppercase;
            color: #657060;
            margin-bottom: 0.35rem;
        }

        .program-card-name {
            display: block;
            color: #173225;
            font-size: 1rem;
            font-weight: 700;
            line-height: 1.35;
            margin-bottom: 0.25rem;
            word-break: break-word;
        }

        .program-card-slug {
            display: block;
            color: #5b6a60;
            font-size: 0.84rem;
            line-height: 1.35;
            word-break: break-word;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def render_sidebar(current_path: str) -> None:
    """Render a workflow-oriented custom sidebar."""
    with st.sidebar:
        st.markdown("## Sponsor Guide Workspace")
        st.caption("A guided workflow for creating and updating funding guides.")

        selected_slug = str(st.session_state.get("selected_program_slug", "")).strip()
        if selected_slug:
            selected_name = str(st.session_state.get("selected_program_name", "")).strip()
            if not selected_name:
                selected_name = get_program_display_name(selected_slug)
            safe_name = html.escape(selected_name)
            safe_slug = html.escape(selected_slug)
            st.markdown(
                f"""
                <div class="program-card">
                    <span class="program-card-label">Current program</span>
                    <span class="program-card-name">{safe_name}</span>
                    <span class="program-card-slug">{safe_slug}</span>
                </div>
                """,
                unsafe_allow_html=True,
            )
        else:
            st.info("No program selected yet. Start with setup or choose a program on another page.")

        st.markdown("### Workflow")
        for step in WORKFLOW_STEPS:
            active = step["path"] == current_path
            label = f"• {step['label']}" if active else step["label"]
            st.page_link(step["path"], label=label)
            st.caption(step["description"])

        st.markdown("### Tips")
        st.caption("New program? Start at Set Up Program, then Review & Generate to get your first guide with citations.")
        st.caption("Ready to download? Go to View Outputs right after generating the draft.")
        st.caption("Keeping a guide current? Use Weekly Update when sponsor pages change.")
        st.caption("Need proof? Use Audit Evidence to trace citations back to sources.")



def render_page_header(title: str, summary: str, step_label: str = "") -> None:
    """Render a shared page hero to clarify task intent."""
    eyebrow = step_label or "Sponsor Guide Workflow"
    st.markdown(
        f"""
        <div class="app-hero">
            <div class="app-eyebrow">{eyebrow}</div>
            <h1>{title}</h1>
            <p>{summary}</p>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_next_steps(steps: Iterable[str], title: str = "What to do next") -> None:
    """Render a compact list of next-step guidance."""
    items = [step for step in steps if step]
    if not items:
        return
    st.markdown(f"### {title}")
    for step in items:
        st.write(f"- {step}")
