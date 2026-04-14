"""Status and result display helpers."""

from __future__ import annotations

import streamlit as st


def render_outcome(ok: bool, success_text: str, error_text: str) -> None:
    """Render a success/error banner based on an operation outcome."""
    if ok:
        st.success(success_text)
    else:
        st.error(error_text)


def render_storage_status(storage: dict | None) -> None:
    """Render remote persistence sync status when available."""
    if not storage:
        return

    enabled = bool(storage.get("enabled"))
    ok = bool(storage.get("ok"))
    message = str(storage.get("message", "")).strip()
    detail = str(storage.get("detail", "")).strip()
    remote_url = str(storage.get("remote_url", "")).strip()

    if not enabled:
        st.caption("Remote persistence is disabled; files are stored on local runtime disk only.")
        return

    if ok:
        st.caption(message or "Remote persistence sync completed.")
        if remote_url:
            st.markdown(f"[Open remote program files]({remote_url})")
        return

    st.warning("Remote persistence is enabled but this sync failed.")
    if message:
        st.caption(message)
    if detail:
        st.caption(detail)
