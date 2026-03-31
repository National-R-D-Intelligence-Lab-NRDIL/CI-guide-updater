"""Notification helper for async review dispatch."""

from datetime import datetime
from typing import Optional

import requests


def build_async_review_message(
    program: str,
    review_id: str,
    shared_dir: str,
    collect_cmd: str,
) -> str:
    """Build a compact notification message for experts/review coordinators."""
    ts = datetime.now().strftime("%Y-%m-%d %H:%M")
    return (
        f"Review package ready: {program}\n"
        f"Review ID: {review_id}\n"
        f"Shared folder: {shared_dir}\n\n"
        "Please review and edit these files:\n"
        "- sources_pending.json\n"
        "- draft_guide.md\n"
        "- manifest.json (set status to approved when done)\n\n"
        f"Dispatched at: {ts}\n\n"
        "Collector command:\n"
        f"{collect_cmd}"
    )


def send_webhook_message(webhook_url: str, message: str, timeout: int = 10) -> Optional[str]:
    """Send a plain text webhook message.

    Works with Teams Incoming Webhook and many generic webhooks.

    Returns:
        ``None`` when successful; otherwise an error string.
    """
    try:
        resp = requests.post(webhook_url, json={"text": message}, timeout=timeout)
        if 200 <= resp.status_code < 300:
            return None
        return f"HTTP {resp.status_code}: {resp.text[:300]}"
    except Exception as exc:  # pragma: no cover - network dependent
        return str(exc)
