"""Shared helpers for program naming and paths."""

import re


def make_slug(program: str) -> str:
    """Convert a program name to a clean, filesystem-safe slug."""
    slug = program.lower()
    slug = re.sub(r"[^a-z0-9]+", "_", slug)
    return slug.strip("_")
