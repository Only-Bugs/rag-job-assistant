"""Generic helper utilities for the RAG stack."""

from __future__ import annotations

from pathlib import Path


def ensure_dir(path: Path) -> None:
    """Create a directory (and parents) if it does not exist."""
    path.mkdir(parents=True, exist_ok=True)


__all__ = ["ensure_dir"]
