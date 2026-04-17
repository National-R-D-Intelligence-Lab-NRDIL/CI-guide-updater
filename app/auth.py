"""Authentication gate for Streamlit pages.

``require_login()`` is called near the top of every page via ``apply_app_chrome()``.
When the ``[auth]`` section is absent from secrets (e.g. local dev without a
secrets.toml), the function is a complete no-op so the tool works unchanged on
a developer's machine.

Setup
-----
1. Add ``authlib`` to your environment (``pip install "streamlit[auth]"``).
2. Copy ``.streamlit/secrets.toml.example`` to ``.streamlit/secrets.toml`` and
   fill in your Microsoft Azure AD credentials.
3. On Streamlit Cloud, paste the same values into **App settings > Secrets**.
4. Add allowed email addresses to the ``[allowed_users]`` section of secrets.
"""

from __future__ import annotations

import streamlit as st


def _auth_configured() -> bool:
    """Return True only when ``[auth]`` is present in Streamlit secrets."""
    try:
        return "auth" in st.secrets
    except Exception:
        return False


def _allowed_emails() -> set[str]:
    """Return the email allowlist from secrets, or empty set (allow all) if absent."""
    try:
        raw = st.secrets.get("allowed_users", {}).get("emails", [])
        return {e.strip().lower() for e in raw if isinstance(e, str) and e.strip()}
    except Exception:
        return set()


def require_login() -> None:
    """Gate every page behind Microsoft sign-in and an optional email allowlist.

    Behaviour
    ---------
    - **No ``[auth]`` in secrets** → no-op (local dev, CLI usage).
    - **Not logged in** → renders a sign-in page and stops the script.
    - **Logged in, no allowlist configured** → passes through (any account in the tenant).
    - **Logged in, not on allowlist** → renders an access-denied message and stops.
    - **Logged in and allowed** → returns immediately; page renders normally.
    """
    if not _auth_configured():
        return

    if not st.user.is_logged_in:
        st.markdown("## CI Sponsor Guide Tool")
        st.markdown(
            "Sign in with your institutional Microsoft account to continue."
        )
        st.button("Sign in with Microsoft", on_click=st.login, type="primary")
        st.stop()

    allowed = _allowed_emails()
    if allowed and st.user.email.lower() not in allowed:
        st.error(
            f"Access denied. Your account ({st.user.email}) is not on the "
            "access list. Contact the tool administrator to request access."
        )
        st.button("Sign out", on_click=st.logout)
        st.stop()
