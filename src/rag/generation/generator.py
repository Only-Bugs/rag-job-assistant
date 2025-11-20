"""
generator.py
High-level generation helpers and the overall application workflow.
"""

from __future__ import annotations

from datetime import datetime
from typing import Dict, Any

from rag.config.settings import OUT_DIR

try:
    from rag.config.profile import USER_PROFILE
except ImportError:
    USER_PROFILE = None

from rag.utils.exceptions import ProfileNotConfiguredError
from rag.ingestion.ingest import index_profile_docs, index_jd_text
from rag.retrieval.retriever import retrieve, format_docs
from rag.ingestion.preprocessing.keywords import extract_keywords, compute_alignment
from rag.generation.context_builder import build_context
from rag.models.llm.ollama_client import run_prompt
from rag.generation.prompts.templates import (
    SYSTEM_SKILLS,
    SYSTEM_COVER,
    SYSTEM_EMAILS,
    SYSTEM_ATS,
)


def gen_skills(context: str) -> str:
    return run_prompt(SYSTEM_SKILLS, context)


def gen_cover(context: str) -> str:
    return run_prompt(SYSTEM_COVER, context)


def gen_emails(context: str) -> str:
    return run_prompt(SYSTEM_EMAILS, context)


def gen_ats(context: str) -> str:
    return run_prompt(SYSTEM_ATS, context)


def generate_application_package(jd_text: str, save_to_disk: bool = False) -> Dict[str, Any]:
    """
    Full workflow:
    1. Index profile docs and this JD.
    2. Retrieve focused snippets.
    3. Extract skills/keywords + compute alignment.
    4. Build the consolidated context block.
    5. Generate skills, cover letter, emails, ATS summary.
    """
    if USER_PROFILE is None:
        raise ProfileNotConfiguredError("USER_PROFILE is not set. Fill in rag/config/profile.py locally.")

    index_profile_docs()
    index_jd_text(jd_text)

    jd_focus = retrieve("List must-have requirements and responsibilities.", k=6, doc_type="jd")
    profile_focus = retrieve("Find bullets that prove impact, results, metrics.", k=6, doc_type="profile")
    rag_jd = format_docs(jd_focus)
    rag_profile = format_docs(profile_focus)

    jd_hard, jd_soft, keywords = extract_keywords(jd_text)
    have_hard, have_soft, gaps = compute_alignment(USER_PROFILE["skills"], jd_hard, jd_soft)

    ctx = build_context(
        USER_PROFILE,
        jd_text,
        rag_jd,
        rag_profile,
        jd_hard,
        jd_soft,
        keywords,
        have_hard,
        have_soft,
        gaps,
    )

    skills_out = gen_skills(ctx)
    cover_out = gen_cover(ctx)
    emails_out = gen_emails(ctx)
    ats_out = gen_ats(ctx)

    if save_to_disk:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        (OUT_DIR / f"{ts}_skills_keywords.md").write_text(skills_out, encoding="utf-8")
        (OUT_DIR / f"{ts}_cover_letter.md").write_text(cover_out, encoding="utf-8")
        (OUT_DIR / f"{ts}_emails.md").write_text(emails_out, encoding="utf-8")
        (OUT_DIR / f"{ts}_ats_summary.md").write_text(ats_out, encoding="utf-8")

    return {
        "context": ctx,
        "skills": skills_out,
        "cover": cover_out,
        "emails": emails_out,
        "ats": ats_out,
        "jd_hard": jd_hard,
        "jd_soft": jd_soft,
        "keywords": keywords,
        "have_hard": have_hard,
        "have_soft": have_soft,
        "gaps": gaps,
    }


# Backwards-compatible alias for legacy imports
generate_all_from_jd = generate_application_package


__all__ = [
    "gen_skills",
    "gen_cover",
    "gen_emails",
    "gen_ats",
    "generate_application_package",
    "generate_all_from_jd",
]
