"""
Embedding model factory shared across the ResuMate pipeline.

The model is loaded lazily on first call to ``get_embeddings()`` so that
importing this module does NOT trigger the ~6-10 s HuggingFace model load.
"""

from __future__ import annotations

import logging

from resumate.config.settings import EMBED_MODEL

logger = logging.getLogger("resumate")
_embeddings = None


def get_embeddings():
    """Return the shared HuggingFaceEmbeddings singleton (lazy-loaded)."""
    global _embeddings
    if _embeddings is None:
        import torch
        from langchain_huggingface import HuggingFaceEmbeddings

        device = "cuda" if torch.cuda.is_available() else "cpu"
        logger.info("Loading embedding model %s on %s...", EMBED_MODEL, device)
        _embeddings = HuggingFaceEmbeddings(
            model_name=EMBED_MODEL,
            model_kwargs={"device": device},
        )
        logger.info("Embedding model loaded.")
    return _embeddings


__all__ = ["get_embeddings"]
