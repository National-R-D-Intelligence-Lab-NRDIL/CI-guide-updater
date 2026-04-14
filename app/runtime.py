"""Runtime bootstrap helpers for Streamlit entrypoints."""

from __future__ import annotations

import sys
from pathlib import Path


def ensure_project_root_on_path() -> Path:
    """Add the repository root to `sys.path` when a file is run as a script."""
    project_root = Path(__file__).resolve().parents[1]
    root_str = str(project_root)
    if root_str not in sys.path:
        sys.path.insert(0, root_str)
    return project_root
