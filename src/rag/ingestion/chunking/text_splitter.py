"""Chunking utilities shared across ingestion tasks."""

from __future__ import annotations

from langchain_text_splitters import RecursiveCharacterTextSplitter

from rag.config.settings import CHUNK_SIZE, CHUNK_OVERLAP

SPLITTER = RecursiveCharacterTextSplitter(
    chunk_size=CHUNK_SIZE,
    chunk_overlap=CHUNK_OVERLAP,
    separators=["\n\n", "\n", " ", ""],
)

__all__ = ["SPLITTER"]
