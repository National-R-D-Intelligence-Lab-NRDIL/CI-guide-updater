"""Error types and formatting utilities for UI-safe failures."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class UserFacingError(Exception):
    """Exception with a concise message safe to surface in Streamlit."""

    message: str
    detail: str = ""

    def __str__(self) -> str:
        if self.detail:
            return f"{self.message} ({self.detail})"
        return self.message


def format_exception(exc: Exception) -> str:
    """Return a compact user-facing message for unexpected exceptions."""
    return f"{exc.__class__.__name__}: {exc}"
