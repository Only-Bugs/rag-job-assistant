"""
query_pipeline.py
Utility for a lightweight RAG answer without full pipeline context.
"""

from __future__ import annotations

from rag.config.settings import TOP_K

try:
    from rag.config.profile import USER_PROFILE
except ImportError:
    USER_PROFILE = None

from rag.utils.exceptions import ProfileNotConfiguredError
from rag.vectorstore.chroma_instance import get_vectordb
from rag.generation.prompts.templates import build_basic_system_prompt
from rag.models.llm.ollama_client import run_prompt


def generate_answer(query: str, k: int = TOP_K) -> str:
    """Simple query over profile documents using the shared vector store."""
    if USER_PROFILE is None:
        raise ProfileNotConfiguredError("USER_PROFILE is not set. Fill in rag/config/profile.py locally.")

    vectordb = get_vectordb()
    retriever = vectordb.as_retriever(search_kwargs={"k": k})

    docs = retriever.get_relevant_documents(query)
    context = "\n\n".join(d.page_content for d in docs)

    system_prompt = build_basic_system_prompt(USER_PROFILE)

    prompt_text = f"""{system_prompt}

Context from my documents:
{context}

User request:
{query}

Write a clear, professional answer tailored for AI/ML job applications.
Avoid hallucinating technologies I don't know unless the user explicitly asks to learn them.
"""

    return run_prompt("You are a helpful assistant.", prompt_text)


__all__ = ["generate_answer"]
