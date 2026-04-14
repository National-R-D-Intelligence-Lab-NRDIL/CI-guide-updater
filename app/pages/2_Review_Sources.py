"""Page: review and finalize candidate sources."""

from __future__ import annotations

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.runtime import bootstrap  # noqa: E402
bootstrap()

from urllib.parse import urlparse

import streamlit as st

from app.components.shell import (
    apply_app_chrome,
    render_page_header,
    render_sidebar,
)
from app.components.forms import select_program_form
from app.components.status import render_storage_status
from app.components.tables import show_table
from app.state.session import init_session_state
from src.services.review_service import (
    add_manual_source,
    draft_exists,
    finalize_review,
    generate_first_draft,
    list_program_slugs,
    load_review_context,
    get_program_display_name,
    promote_draft_to_baseline,
    save_review_decision,
)


def _source_display_label(row: dict[str, object], program_slug: str) -> str:
    """Return a short readable label for queue navigation."""
    title = str(row.get("title", "")).strip()
    if title:
        return title

    source_name = str(row.get("name", "")).strip()
    prefix = f"{program_slug}_"
    if source_name.startswith(prefix):
        source_name = source_name[len(prefix):]
    source_name = source_name.replace("_", " ").strip()
    if source_name:
        return source_name[:96] + ("..." if len(source_name) > 96 else "")

    url = str(row.get("url", "")).strip()
    if not url:
        return "Untitled source"

    parsed = urlparse(url)
    tail = parsed.path.strip("/").split("/")[-1] if parsed.path else ""
    return tail or parsed.netloc or url


def _source_queue(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    """Prioritize sources that still need attention."""
    order = {
        "unreviewed": 0,
        "pending_manual_review": 1,
        "approved": 2,
        "rejected": 3,
    }
    return sorted(
        rows,
        key=lambda row: (
            order.get(str(row.get("status", "")), 99),
            str(row.get("title", "") or row.get("name", "")).lower(),
        ),
    )


def _next_source_name(rows: list[dict[str, object]], current_name: str) -> str:
    """Choose the next source after a save, preferring unfinished work."""
    queue = _source_queue(rows)
    remaining = [
        str(row.get("name", ""))
        for row in queue
        if str(row.get("status", "")) in {"unreviewed", "pending_manual_review"}
    ]
    if remaining:
        for name in remaining:
            if name != current_name:
                return name
        return remaining[0]

    all_names = [str(row.get("name", "")) for row in queue]
    if not all_names:
        return ""
    if current_name in all_names:
        idx = all_names.index(current_name)
        if idx + 1 < len(all_names):
            return all_names[idx + 1]
    return all_names[0]


st.set_page_config(page_title="Review Sources", layout="wide")
init_session_state()
apply_app_chrome()
render_sidebar("pages/2_Review_Sources.py")
render_page_header(
    "Review Sources and Generate Guide",
    "Approve the right links, finalize the source list, and generate the first draft with citations. Output files are ready to download as soon as the draft is created.",
    step_label="Step 2",
)

program_slugs = list_program_slugs()
st.markdown("### Choose a program")
selected_slug = select_program_form(program_slugs, key_prefix="review")
if selected_slug:
    st.session_state["selected_program_slug"] = selected_slug
    st.session_state["selected_program_name"] = get_program_display_name(selected_slug)

if not selected_slug:
    st.stop()

manual_source_feedback = str(st.session_state.pop("manual_source_feedback", "")).strip()
if manual_source_feedback:
    st.success(manual_source_feedback)
review_feedback = str(st.session_state.pop("review_feedback", "")).strip()
if review_feedback:
    st.success(review_feedback)

context = load_review_context(selected_slug)
if not context["ok"]:
    st.error(context["error"])
    if context.get("detail"):
        st.caption(context["detail"])
    st.stop()

rows = context["rows"]
st.session_state["active_review_context"] = {"slug": selected_slug, "rows": rows}
for row in rows:
    row["sections_text"] = ", ".join(row["sections"])
    row["display_label"] = _source_display_label(row, selected_slug)

st.markdown("### Source review queue")
review_col, summary_col = st.columns([2, 1], gap="large")
with summary_col:
    total_count = len(rows)
    approved_count = len([r for r in rows if r["status"] == "approved"])
    pending_count = len([r for r in rows if r["status"] == "unreviewed"])
    manual_count = len([r for r in rows if r["status"] == "pending_manual_review"])
    st.metric("Total sources", total_count)
    st.metric("Approved", approved_count)
    st.metric("Still to review", pending_count)
    st.metric("Need manual follow-up", manual_count)

with review_col:
    st.caption("Use the tabs to focus on the sources that still need action.")
status_tabs = st.tabs(["Unreviewed", "Pending Manual", "Approved", "Rejected", "All"])
with status_tabs[0]:
    show_table([r for r in rows if r["status"] == "unreviewed"])
with status_tabs[1]:
    show_table([r for r in rows if r["status"] == "pending_manual_review"])
with status_tabs[2]:
    show_table([r for r in rows if r["status"] == "approved"])
with status_tabs[3]:
    show_table([r for r in rows if r["status"] == "rejected"])
with status_tabs[4]:
    show_table(rows)

if rows:
    st.markdown("### Review decisions")
    queue_rows = _source_queue(rows)
    queue_names = [str(row["name"]) for row in queue_rows]
    source_picker_key = f"review_source_name_{selected_slug}"
    next_source_key = f"{source_picker_key}_next"

    # Freeze the initial queue order so position numbers stay stable
    # as sources are reviewed and the live queue reorders.
    initial_order_key = f"{source_picker_key}_initial_order"
    if initial_order_key not in st.session_state:
        st.session_state[initial_order_key] = list(queue_names)
    frozen_order: list[str] = st.session_state[initial_order_key]
    # If sources were added after the page first loaded, append them at the end.
    for name in queue_names:
        if name not in frozen_order:
            frozen_order.append(name)

    pending_next_source = str(st.session_state.get(next_source_key, "")).strip()
    if pending_next_source in queue_names:
        st.session_state[source_picker_key] = pending_next_source
        st.session_state.pop(next_source_key, None)

    selected_source_name = str(st.session_state.get(source_picker_key, "")).strip()
    if selected_source_name not in queue_names:
        pending_names = [
            str(row["name"])
            for row in queue_rows
            if row["status"] in {"unreviewed", "pending_manual_review"}
        ]
        selected_source_name = pending_names[0] if pending_names else queue_names[0]
        st.session_state[source_picker_key] = selected_source_name

    review_queue_col, detail_col = st.columns([1, 1.7], gap="large")

    with review_queue_col:
        st.caption("Pick a source from the queue. Remaining items stay at the top.")
        source_name = st.radio(
            "Review queue",
            options=queue_names,
            key=source_picker_key,
            format_func=lambda name: next(
                (
                    f"{row['display_label']} | {row['status'].replace('_', ' ')}"
                    for row in queue_rows
                    if row["name"] == name
                ),
                name,
            ),
            label_visibility="collapsed",
        )
        current_position = (
            frozen_order.index(source_name) + 1
            if source_name in frozen_order
            else queue_names.index(source_name) + 1
            if source_name in queue_names
            else 1
        )
        st.caption(f"Viewing {current_position} of {len(frozen_order)}")

    selected_row = next((r for r in rows if r["name"] == source_name), None)
    if selected_row:
        with detail_col:
            with st.container(border=True):
                st.caption(f"Source {current_position} of {len(frozen_order)}")
                st.markdown(f"#### {selected_row['display_label']}")
                meta_col1, meta_col2 = st.columns(2)
                meta_col1.write(f"**Status:** {selected_row.get('status', 'unreviewed').replace('_', ' ')}")
                meta_col2.write(f"**Origin:** {selected_row.get('source_origin', 'auto')}")
                if selected_row.get("title"):
                    st.write(f"**Title:** {selected_row['title']}")
                st.write(f"**URL:** {selected_row['url']}")
                st.write(f"**Sections:** {selected_row['sections_text'] or '(none)'}")
                if selected_row.get("created_at"):
                    st.write(f"**Added at:** `{selected_row['created_at']}`")

                with st.form(f"decision_form_{source_name}"):
                    options = ["approved", "rejected", "unreviewed"]
                    if selected_row.get("source_origin") == "manual":
                        options.append("pending_manual_review")
                    current_status = selected_row.get("status", "unreviewed")
                    if current_status not in options:
                        current_status = "unreviewed"
                    decision = st.radio(
                        "Decision",
                        options=options,
                        index=options.index(current_status),
                        horizontal=True,
                    )
                    notes = st.text_area(
                        "Notes",
                        value=selected_row.get("notes", ""),
                        placeholder="Add context for the next reviewer if needed.",
                    )
                    save_clicked = st.form_submit_button("Save and review next", use_container_width=True)

                if save_clicked:
                    saved = save_review_decision(
                        slug=selected_slug,
                        source_name=source_name,
                        status=decision,
                        notes=notes,
                    )
                    if saved["ok"]:
                        storage = saved.get("storage", {})
                        storage_message = str(storage.get("message", "")).strip()
                        feedback = "Decision saved. Moved to the next source."
                        if storage_message:
                            feedback = f"{feedback} {storage_message}"
                        st.session_state["review_feedback"] = feedback
                        next_name = _next_source_name(
                            [
                                {
                                    **row,
                                    "status": decision if row["name"] == source_name else row["status"],
                                }
                                for row in rows
                            ],
                            source_name,
                        )
                        if next_name:
                            st.session_state[next_source_key] = next_name
                        else:
                            st.session_state.pop(next_source_key, None)
                        st.rerun()
                    else:
                        st.error(saved["error"])
                        if saved.get("detail"):
                            st.caption(saved["detail"])

st.markdown("### Add a missing source")
with st.form("add_manual_source_form", clear_on_submit=True):
    manual_url = st.text_input("URL (required)", placeholder="https://...")
    manual_title = st.text_input("Label/Title (optional)", placeholder="Program FAQ")
    manual_section = st.text_input(
        "Mapped section (optional)",
        placeholder="e.g. Eligibility",
        help="Optional section this source most supports.",
    )
    manual_note = st.text_area(
        "Reviewer note / reason (optional)",
        placeholder="Why this source should be included.",
    )
    add_manual_clicked = st.form_submit_button("Add Source URL")

if add_manual_clicked:
    added = add_manual_source(
        slug=selected_slug,
        url=manual_url,
        title=manual_title,
        mapped_section=manual_section,
        reviewer_note=manual_note,
    )
    if added["ok"]:
        st.session_state["manual_source_feedback"] = "Manual source added for review."
        storage = added.get("storage")
        if storage:
            storage_message = str(storage.get("message", "")).strip()
            if storage_message:
                st.session_state["manual_source_feedback"] += f" {storage_message}"
        st.rerun()
    else:
        st.error(added["error"])
        if added.get("detail"):
            st.caption(added["detail"])

st.divider()
st.markdown("### Finalize the approved source list")
st.write("Lock in the approved sources before generating the draft. Rejected sources will not be used.")
with st.form("finalize_form"):
    include_unreviewed = st.checkbox(
        "Include unreviewed sources as approved",
        value=False,
        help="Use only if you want to keep remaining unreviewed sources.",
    )
    finalize_clicked = st.form_submit_button("Finalize Review", use_container_width=True)

if finalize_clicked:
    result = finalize_review(selected_slug, include_unreviewed=include_unreviewed)
    if result["ok"]:
        st.success(f"Finalized {result['approved_count']} sources.")
        st.code(result["sources_out"])
        render_storage_status(result.get("storage"))
    else:
        st.error(result["error"])
        if result.get("detail"):
            st.caption(result["detail"])

st.divider()
st.markdown("### Generate the first draft")
st.write("Generate the initial draft with citations from approved sources. Output files (markdown, Word, PDF) are created immediately and available on the **View Outputs** page.")
with st.container(border=True):
    draft_citations = st.checkbox("Enable citations", value=True, key="draft_citations")
if st.button("Generate First Draft", use_container_width=True):
    with st.status("Generating first draft with citations...", expanded=True) as status:
        draft_result = generate_first_draft(selected_slug, with_citations=draft_citations)
        if draft_result["ok"]:
            status.update(label="Draft generated.", state="complete")
        else:
            status.update(label="Draft generation failed.", state="error")
    if draft_result["ok"]:
        citation_count = draft_result.get("citation_count", 0)
        msg = "First draft generated from approved sources."
        if citation_count:
            msg += f" {citation_count} citation(s) added."
        st.success(msg)
        st.code(draft_result["draft_path"])
        st.caption(f"Draft size: {draft_result['draft_chars']} characters")
        if draft_result.get("output_dir"):
            st.caption(f"Output files: `{draft_result['output_dir']}`")
        st.page_link("pages/4_Outputs.py", label="Go to View Outputs to preview and download")
        render_storage_status(draft_result.get("storage"))
    else:
        st.error(draft_result["error"])
        if draft_result.get("detail"):
            st.caption(draft_result["detail"])

st.divider()
st.markdown("### Make the draft the working baseline")
st.write("Promote the draft to `guide.md` so the Weekly Update pipeline can use it as the starting point for future refreshes.")
has_draft = draft_exists(selected_slug)
if not has_draft:
    st.info("No draft found at `programs/<slug>/review/draft_guide.md` yet.")
promote_clicked = st.button(
    "Promote Draft to Baseline",
    use_container_width=True,
    disabled=not has_draft,
)
if promote_clicked:
    promote_result = promote_draft_to_baseline(selected_slug)
    if promote_result["ok"]:
        st.success(promote_result["message"])
        st.code(promote_result["baseline_path"])
        st.caption(f"Characters copied: {promote_result['chars_copied']}")
        render_storage_status(promote_result.get("storage"))
    else:
        st.error(promote_result["error"])
        if promote_result.get("detail"):
            st.caption(promote_result["detail"])
