"""
chroma_instance.py
Chroma persistence and access helpers.
"""

from __future__ import annotations

import os
from pathlib import Path

from chromadb.config import Settings
from langchain_chroma import Chroma

from rag.config.settings import CHROMA_DB_DIR
from rag.models.embedding_model.factory import EMBEDDINGS

# Ensure telemetry is disabled everywhere before Chroma spins up.
os.environ.setdefault("ANONYMIZED_TELEMETRY", "false")
os.environ.setdefault("CHROMA_TELEMETRY", "false")

CHROMA_SETTINGS = Settings(
    anonymized_telemetry=False,
)

# Per-path cache: key = str(persist_directory) → Chroma instance.
# Allows isolated vector stores for different users without reloading embeddings.
_vectordb_cache: dict[str, Chroma] = {}


def get_vectordb(db_path: Path | None = None) -> Chroma:
    """Return a Chroma vector store for the given path (cached per path).

    Args:
        db_path: Absolute path to the chroma persist directory.
                 Defaults to the legacy global CHROMA_DB_DIR when None.
    """
    path = db_path if db_path is not None else CHROMA_DB_DIR
    key = str(path)
    if key not in _vectordb_cache:
        _vectordb_cache[key] = Chroma(
            embedding_function=EMBEDDINGS,
            persist_directory=key,
            client_settings=CHROMA_SETTINGS,
        )
    return _vectordb_cache[key]


__all__ = ["get_vectordb", "CHROMA_SETTINGS"]
