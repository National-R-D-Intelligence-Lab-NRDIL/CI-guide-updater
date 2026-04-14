"""Page: create a new program workspace."""

from __future__ import annotations

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.runtime import bootstrap  # noqa: E402
bootstrap()

import streamlit as st

from app.components.shell import (
    apply_app_chrome,
    render_next_steps,
    render_page_header,
    render_sidebar,
)
from app.components.status import render_storage_status
from app.components.tables import show_table
from app.state.session import init_session_state
from src.services.bootstrap_service import create_new_program


st.set_page_config(page_title="Create New Program", layout="wide")
init_session_state()
apply_app_chrome()
render_sidebar("pages/1_Create_New_Program.py")
render_page_header(
    "Set Up a New Program",
    "Create a workspace for a new sponsor guide. This first step gathers candidate sources so your team can review and approve them before drafting.",
    step_label="Step 1",
)
st.info("This step does not create the guide draft yet. It prepares the workspace and source list for review.")

# Keep this toggle outside the form so Streamlit reruns immediately
# and dependent fields can enable/disable interactively.
async_review = st.checkbox(
    "Create a shareable async review package",
    value=bool(st.session_state.get("create_async_review", False)),
    key="create_async_review",
    help="Creates and publishes a shared review package from discovered sources.",
)
enable_alternative_monitor = st.checkbox(
    "Enable Alternative Funding Intelligence Monitor",
    value=bool(st.session_state.get("enable_alternative_monitor", False)),
    key="enable_alternative_monitor",
    help="Expands discovery beyond federal opportunities to foundations, corporate, international, and pharma partnership pages.",
)

if enable_alternative_monitor:
    st.markdown("### How to enter the funding topic")
    st.write(
        "Describe the problem area you want to fund, not a federal program title. This helps discovery find foundations, corporate, international, and pharma partnership opportunities."
    )
    st.caption(
        "Best format: audience or problem + research domain (for example: maternal health implementation science)."
    )
    st.code("Alternative funding opportunities for translational oncology research")
    with st.expander("Examples", expanded=False):
        st.markdown(
            "\n".join(
                [
                    "- Alternative funding opportunities for translational oncology research",
                    "- University research funding opportunities for maternal health implementation science",
                    "- Non-federal funding for digital mental health interventions",
                    "- Corporate and foundation funding for AI-enabled diagnostics",
                ]
            )
        )
else:
    st.markdown("### How to enter the program name")
    st.write(
        "Use the most specific official name you know. If the program is commonly known by an acronym, include both the full name and the acronym so source discovery has better context."
    )
    st.caption(
        "Best format: Official full name first, acronym in parentheses, and agency if helpful."
    )
    st.code("Department of Defense Young Investigator Program (DoD YIP)")
    st.caption(
        "Short acronyms by themselves may work sometimes, but they are less reliable because the search step uses your text directly."
    )
    with st.expander("Examples", expanded=False):
        st.markdown(
            "\n".join(
                [
                    "- National Science Foundation CAREER Program (NSF CAREER)",
                    "- Department of Defense Young Investigator Program (DoD YIP)",
                    "- National Institutes of Health Academic Research Enhancement Award (NIH AREA R15)",
                    "- NIH Exploratory/Developmental Research Grant Award (R21)",
                    "- Department of Energy Early Career Research Program (DOE ECRP)",
                    "- USDA Agriculture and Food Research Initiative Foundational and Applied Science Program (USDA AFRI)",
                    "- NASA Established Program to Stimulate Competitive Research (NASA EPSCoR)",
                    "- NIH Small Business Innovation Research Program (SBIR)",
                ]
            )
        )

st.markdown("### Funding monitor setup" if enable_alternative_monitor else "### Program setup")
with st.form("create_program_form"):
    program_name = st.text_input(
        "Funding topic" if enable_alternative_monitor else "Program name",
        placeholder=(
            "e.g. Alternative funding opportunities for translational oncology research"
            if enable_alternative_monitor
            else "e.g. Department of Defense Young Investigator Program (DoD YIP)"
        ),
        help=(
            "Used directly during source discovery to find alternative funding opportunities."
            if enable_alternative_monitor
            else "Used directly during source discovery. Best results usually come from the official full name plus acronym."
        ),
    )
    shared_review_dir = st.text_input(
        "Shared review directory (required for async review)",
        placeholder="/path/to/shared/review/folder",
        disabled=not async_review,
    )
    notify_webhook_url = st.text_input(
        "Notification webhook URL (optional)",
        placeholder="https://...",
        disabled=not async_review,
    )
    monitor_sectors_text = st.text_input(
        "Alternative monitor focus areas (optional, comma-separated)",
        placeholder="e.g. cancer research, digital health, implementation science",
        disabled=not enable_alternative_monitor,
    )
    monitor_regions_text = st.text_input(
        "Alternative monitor geographies (optional, comma-separated)",
        placeholder="e.g. US, UK, EU, global",
        disabled=not enable_alternative_monitor,
    )
    submitted = st.form_submit_button(
        "Create Funding Monitor Workspace" if enable_alternative_monitor else "Create Program Workspace",
        use_container_width=True,
    )

if submitted:
    monitor_sectors = [item.strip() for item in monitor_sectors_text.split(",") if item.strip()]
    monitor_regions = [item.strip() for item in monitor_regions_text.split(",") if item.strip()]
    with st.status("Running bootstrap steps...", expanded=True) as status:
        result = create_new_program(
            program_name,
            async_review=async_review,
            shared_review_dir=shared_review_dir,
            notify_webhook_url=notify_webhook_url,
            enable_alternative_monitor=enable_alternative_monitor,
            monitor_sectors=monitor_sectors,
            monitor_regions=monitor_regions,
        )
        if result["ok"]:
            status.update(label="Bootstrap workspace created.", state="complete")
        else:
            status.update(label="Bootstrap failed.", state="error")

    if not result["ok"]:
        st.error(result["error"])
        if result.get("detail"):
            st.caption(result["detail"])
    else:
        st.session_state["selected_program_slug"] = result["slug"]
        st.session_state["selected_program_name"] = result["program"]
        st.success(
            f"Program initialized: `{result['program']}` (`{result['slug']}`)"
        )
        col1, col2, col3 = st.columns(3)
        col1.metric("Candidates discovered", result["candidate_count"])
        col2.metric("Reachable URLs", result["reachable_count"])
        col3.metric("Sources pending review", result["source_count"])

        st.subheader("Created Paths")
        for item in result["created_files"]:
            st.code(item)

        st.subheader("Candidate URL Review")
        candidate_rows = [
            {
                "label": item.get("label", ""),
                "url": item.get("url", ""),
                "sections": ", ".join(item.get("sections", [])),
                "funding_type": item.get("funding_type", ""),
                "funder_name": item.get("funder_name", ""),
                "priority_score": item.get("priority_score", ""),
                "status": item.get("status", ""),
                "reachable": item.get("reachable", False),
                "content_type": item.get("content_type", ""),
            }
            for item in result["candidates"]
        ]
        show_table(candidate_rows)

        if result.get("async_details"):
            st.subheader("Async Review Package")
            st.json(result["async_details"])

        render_storage_status(result.get("storage"))
        render_next_steps(result["next_steps"])
        st.info("This step does not generate a guide draft. Continue to Review Sources to authorize links first.")
