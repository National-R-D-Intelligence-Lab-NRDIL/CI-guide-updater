"""Validation helpers for user-provided program and path inputs."""

from __future__ import annotations

from pathlib import Path

from src.utils.errors import UserFacingError


def require_non_empty(value: str, field_name: str) -> str:
    """Validate that a field has a non-empty string value."""
    cleaned = value.strip()
    if not cleaned:
        raise UserFacingError(f"{field_name} is required.")
    return cleaned


def ensure_path_exists(path_str: str, field_name: str) -> Path:
    """Validate an existing filesystem path and return it."""
    candidate = Path(path_str).expanduser()
    if not candidate.exists():
        raise UserFacingError(f"{field_name} does not exist.", str(candidate))
    return candidate
