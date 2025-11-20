"""
factory.py
Embedding model factory shared across the RAG pipeline.
"""

from __future__ import annotations

import torch
from langchain_huggingface import HuggingFaceEmbeddings

from rag.config.settings import EMBED_MODEL

device = "cuda" if torch.cuda.is_available() else "cpu"

# Sentence Transformer embeddings used across ingestion/retrieval.
EMBEDDINGS = HuggingFaceEmbeddings(
    model_name=EMBED_MODEL,
    model_kwargs={"device": device},
)

__all__ = ["EMBEDDINGS"]
