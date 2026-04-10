"""Shared logging/trace helpers for service wrappers."""

from __future__ import annotations

import io
from contextlib import redirect_stderr, redirect_stdout
from typing import Callable, TypeVar

T = TypeVar("T")


def capture_logs(func: Callable[[], T]) -> tuple[T, str]:
    """Run a callable and capture stdout/stderr as a combined log string."""
    buffer = io.StringIO()
    with redirect_stdout(buffer), redirect_stderr(buffer):
        result = func()
    return result, buffer.getvalue()
