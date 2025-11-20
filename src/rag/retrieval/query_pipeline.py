"""
query_pipeline.py
Utility for a lightweight RAG answer without full pipeline context.
"""

from __future__ import annotations

from rag.config.settings import TOP_K
from rag.profile import load_profile
from rag.utils.exceptions import ProfileNotConfiguredError
from rag.vectorstore.chroma_instance import get_vectordb
from rag.generation.prompts.templates import build_basic_system_prompt
from rag.models.llm.ollama_client import run_prompt


def generate_answer(query: str, k: int = TOP_K) -> str:
    """Simple query over profile documents using the shared vector store."""
    profile = load_profile()
    if not profile:
        raise ProfileNotConfiguredError(
            "USER_PROFILE is not set. Use the UI profile settings or edit data/job_rag/profile_settings.json."
        )

    vectordb = get_vectordb()
    retriever = vectordb.as_retriever(search_kwargs={"k": k})

    docs = retriever.get_relevant_documents(query)
    context = "\n\n".join(d.page_content for d in docs)

    system_prompt = build_basic_system_prompt(profile)

    role_label = (
        profile.get("target_role")
        or profile.get("domain_focus")
        or profile.get("role_preferences", {}).get("role_description")
        or "AI/ML"
    )

    prompt_text = f"""{system_prompt}

Context from my documents:
{context}

User request:
{query}

Write a clear, professional answer tailored for {role_label} job applications.
Avoid hallucinating technologies I don't know unless the user explicitly asks to learn them.
"""

    return run_prompt("You are a helpful assistant.", prompt_text)


__all__ = ["generate_answer"]
