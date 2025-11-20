"""
chroma_instance.py
Chroma persistence and access helpers.
"""

from __future__ import annotations

import os
from typing import Optional

from chromadb.config import Settings
from langchain_chroma import Chroma

from rag.config.settings import CHROMA_DB_DIR
from rag.models.embedding_model.factory import EMBEDDINGS

# Ensure telemetry is disabled everywhere before Chroma spins up.
os.environ.setdefault("ANONYMIZED_TELEMETRY", "false")
os.environ.setdefault("CHROMA_TELEMETRY", "false")

_vectordb: Optional[Chroma] = None

CHROMA_SETTINGS = Settings(
    anonymized_telemetry=False,
)


def get_vectordb() -> Chroma:
    """Return a Chroma vector store instance (singleton)."""
    global _vectordb
    if _vectordb is None:
        _vectordb = Chroma(
            embedding_function=EMBEDDINGS,
            persist_directory=str(CHROMA_DB_DIR),
            client_settings=CHROMA_SETTINGS,
        )
    return _vectordb


__all__ = ["get_vectordb", "CHROMA_SETTINGS"]
