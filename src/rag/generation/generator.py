"""
generator.py
High-level generation helpers and the overall application workflow.
"""

from __future__ import annotations

import logging

import time
from datetime import datetime
from time import perf_counter
from typing import Any, Callable, Dict, Iterator, Optional

from pathlib import Path

from rag.config.settings import LLM_MAX_TOKENS, OUT_DIR
from rag.profile import load_profile
from rag.utils.exceptions import ProfileNotConfiguredError
from rag.ingestion.ingest import index_profile_docs, index_jd_text
from rag.retrieval.retriever import retrieve, format_docs
from rag.ingestion.preprocessing.keywords import extract_keywords, compute_alignment
from rag.generation.context_builder import build_context, build_task_context
from rag.models.llm.ollama_client import run_prompt
from rag.utils.logging import timed
from ui.components.logboard import PipelineProgress, tracked_block

from rag.generation.prompts.templates import (
    SYSTEM_SKILLS,
    SYSTEM_COVER,
    SYSTEM_EMAILS,
    SYSTEM_ATS,
)

logger = logging.getLogger("rag")


@timed
def gen_skills(context: str) -> str:
    return run_prompt(
        SYSTEM_SKILLS,
        context,
        max_tokens=int(LLM_MAX_TOKENS.get("skills", 450)),
        task_name="gen_skills",
        stage="generation",
    )


@timed
def gen_cover(context: str) -> str:
    return run_prompt(
        SYSTEM_COVER,
        context,
        max_tokens=int(LLM_MAX_TOKENS.get("cover", 650)),
        task_name="gen_cover",
        stage="generation",
    )


@timed
def gen_emails(context: str) -> str:
    return run_prompt(
        SYSTEM_EMAILS,
        context,
        max_tokens=int(LLM_MAX_TOKENS.get("emails", 700)),
        task_name="gen_emails",
        stage="generation",
    )


@timed
def gen_ats(context: str) -> str:
    return run_prompt(
        SYSTEM_ATS,
        context,
        max_tokens=int(LLM_MAX_TOKENS.get("ats", 280)),
        task_name="gen_ats",
        stage="generation",
    )


def generate_application_package(
    jd_text: str,
    save_to_disk: bool = False,
    progress: Optional[PipelineProgress] = None,
    user_data_dir: Path | None = None,
) -> Iterator[tuple[str, Any]]:
    """
    Full workflow — generator that yields (task_name, value) tuples:
      ("skills", str), ("cover", str), ("emails", str), ("ats", str),
      ("_meta", dict)   <- context, keywords, alignment fields

    1. Index profile docs and this JD.
    2. Retrieve focused snippets.
    3. Extract skills/keywords + compute alignment.
    4. Build the consolidated context block.
    5. Yield each generation task result as it completes.

    Args:
        user_data_dir: Per-user data root (e.g. ``data/users/dev_user``).
                       Falls back to the legacy global paths when None.
    """
    profile = load_profile(user_data_dir)
    if not profile:
        raise ProfileNotConfiguredError(
            "USER_PROFILE is not set. Use the UI profile settings or edit the profile JSON."
        )

    if progress is not None:
        progress.pipeline_start()
    try:
        yield from _generate_application_package_body(
            jd_text, save_to_disk, progress, profile, user_data_dir
        )
    finally:
        if progress is not None:
            progress.pipeline_end()


def _generate_application_package_body(
    jd_text: str,
    save_to_disk: bool,
    progress: Optional[PipelineProgress],
    profile: Dict[str, Any],
    user_data_dir: Path | None = None,
) -> Iterator[tuple[str, Any]]:
    db_path = (user_data_dir / "chroma_db") if user_data_dir else None

    with tracked_block("index_profile_docs", progress):
        index_profile_docs(user_data_dir)
    with tracked_block("index_jd_text", progress):
        index_jd_text(jd_text, user_data_dir)

    with tracked_block("retrieve_jd_focus", progress):
        jd_focus = retrieve("List must-have requirements and responsibilities.", k=6, doc_type="jd", db_path=db_path)
    with tracked_block("retrieve_profile_focus", progress):
        profile_focus = retrieve("Find bullets that prove impact, results, metrics.", k=6, doc_type="profile", db_path=db_path)
    with tracked_block("format_retrieved_docs", progress):
        rag_jd = format_docs(jd_focus)
        rag_profile = format_docs(profile_focus)

    with tracked_block("extract_keywords", progress):
        jd_hard, jd_soft, keywords = extract_keywords(jd_text)
    with tracked_block("compute_alignment", progress):
        have_hard, have_soft, gaps = compute_alignment(profile.get("skills", []), jd_hard, jd_soft)

    with tracked_block("build_context", progress):
        ctx = build_context(
            profile,
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

    _ctx_args = (
        profile,
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
    task_ctx = {name: build_task_context(name, *_ctx_args) for name in ("skills", "cover", "emails", "ats")}

    def _is_connection_error(exc: Exception) -> bool:
        text = f"{type(exc).__name__} {exc}".lower()
        return any(kw in text for kw in (
            "disconnected", "connectionerror", "connect error",
            "remoteprotocol", "timeout",
        ))

    def _tracked_gen(gen_key: str, fn: Callable[[str], str], context: str) -> str:
        if progress is not None:
            progress.start(gen_key)
        t0 = perf_counter()
        try:
            result = fn(context)
        except Exception as exc:
            if _is_connection_error(exc):
                time.sleep(2)
                try:
                    result = fn(context)
                except Exception as retry_exc:
                    if progress is not None:
                        progress.finish(gen_key, "error", (perf_counter() - t0) * 1000)
                    raise RuntimeError(
                        f"[{gen_key}] Ollama connection error after retry: {retry_exc}"
                    ) from retry_exc
            else:
                if progress is not None:
                    progress.finish(gen_key, "error", (perf_counter() - t0) * 1000)
                raise RuntimeError(f"[{gen_key}] failed: {exc}") from exc
        if progress is not None:
            progress.finish(gen_key, "ok", (perf_counter() - t0) * 1000)
        return result

    # Generation: yield each result as it completes so the UI can render
    # progressively. tracked_block("generation_sequential") times the full
    # span from gen_skills start to gen_ats end.
    with tracked_block("generation_sequential", progress):
        skills_out = _tracked_gen("gen_skills", gen_skills, task_ctx["skills"])
        yield ("skills", skills_out)
        cover_out = _tracked_gen("gen_cover", gen_cover, task_ctx["cover"])
        yield ("cover", cover_out)
        emails_out = _tracked_gen("gen_emails", gen_emails, task_ctx["emails"])
        yield ("emails", emails_out)
        ats_out = _tracked_gen("gen_ats", gen_ats, task_ctx["ats"])
        yield ("ats", ats_out)

    if save_to_disk:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        (OUT_DIR / f"{ts}_skills_keywords.md").write_text(skills_out, encoding="utf-8")
        (OUT_DIR / f"{ts}_cover_letter.md").write_text(cover_out, encoding="utf-8")
        (OUT_DIR / f"{ts}_emails.md").write_text(emails_out, encoding="utf-8")
        (OUT_DIR / f"{ts}_ats_summary.md").write_text(ats_out, encoding="utf-8")

    yield ("_meta", {
        "context": ctx,
        "jd_hard": jd_hard,
        "jd_soft": jd_soft,
        "keywords": keywords,
        "have_hard": have_hard,
        "have_soft": have_soft,
        "gaps": gaps,
    })


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
