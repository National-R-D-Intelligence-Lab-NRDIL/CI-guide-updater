"""Secret-loading helpers shared by CLI and Streamlit entrypoints."""

from __future__ import annotations

import os


def get_secret(name: str) -> str:
    """Return a secret from the environment or Streamlit secrets.

    Streamlit Community Cloud exposes values from the app secrets field via
    ``st.secrets`` and, in many cases, environment variables. We check both so
    the app works the same way locally and in the cloud.
    """
    value = os.getenv(name, "")
    if value:
        return value

    try:
        import streamlit as st
    except Exception:
        return ""

    try:
        secret_value = st.secrets.get(name, "")
    except Exception:
        return ""

    return str(secret_value).strip()
