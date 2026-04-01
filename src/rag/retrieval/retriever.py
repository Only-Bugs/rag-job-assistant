"""
retriever.py
Utilities for querying and formatting snippets from Chroma.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from rag.vectorstore.chroma_instance import get_vectordb


def retrieve(
    query: str,
    k: int = 6,
    doc_type: Optional[str] = None,
    db_path: Path | None = None,
):
    """Retrieve top-k documents for a query, optionally filtered by type.

    Args:
        query: Similarity search query string.
        k: Number of documents to return after filtering.
        doc_type: If set, filter results to this ``doc_type`` metadata value.
        db_path: Path to the Chroma persist directory. Defaults to the global
                 CHROMA_DB_DIR when None (backward-compatible).
    """
    vectordb = get_vectordb(db_path)
    docs = vectordb.similarity_search(query, k=24)
    if doc_type:
        docs = [d for d in docs if d.metadata.get("doc_type") == doc_type]
    return docs[:k]


def format_docs(docs) -> str:
    """Return a numbered snippet list for prompt context."""
    return "\n\n".join(f"[{i+1}] {d.page_content}" for i, d in enumerate(docs, 1))


def cite_sources(docs) -> str:
    """Simple textual citation list for debugging or display."""
    return "\n".join(f"[{i}] {d.metadata.get('source', '')}" for i, d in enumerate(docs, 1))


__all__ = ["retrieve", "format_docs", "cite_sources"]
