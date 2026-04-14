"""Runtime bootstrap helpers for Streamlit entrypoints.

Call ``bootstrap()`` at the **very top** of every Streamlit page or
``app/main.py`` *before* importing anything from ``app`` or ``src``.
The function is designed to be imported via a relative path trick so
it works without the project root already being on ``sys.path``.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[1]


def bootstrap() -> Path:
    """Ensure the repository root is the first entry on ``sys.path``.

    Also invalidates Python's import caches so that editable-install
    or ``__pycache__`` staleness on Streamlit Cloud never shadows the
    real source files.
    """
    root_str = str(_PROJECT_ROOT)
    if root_str not in sys.path:
        sys.path.insert(0, root_str)
    elif sys.path[0] != root_str:
        sys.path.remove(root_str)
        sys.path.insert(0, root_str)
    importlib.invalidate_caches()
    return _PROJECT_ROOT


# Keep backward compat for any call sites that used the old name.
ensure_project_root_on_path = bootstrap
