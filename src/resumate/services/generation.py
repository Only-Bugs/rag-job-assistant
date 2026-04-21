"""
High-level generation helpers and the overall application workflow.
"""

from __future__ import annotations

import logging

import time
from datetime import datetime
from time import perf_counter
from typing import Any, Callable, Dict, Iterator, Optional

from pathlib import Path

from resumate.config.settings import LLM_MAX_TOKENS, OUT_DIR
from resumate.services.profile import load_profile
from resumate.utils.exceptions import ProfileNotConfiguredError
from resumate.services.ingestion import index_profile_docs, index_jd_text
from resumate.services.retrieval import retrieve, format_docs
from resumate.services.keywords import extract_keywords, compute_alignment
from resumate.services.context_builder import build_context, build_task_context
from resumate.models.llm import run_prompt, stream_prompt
from resumate.utils.logging import timed
from resumate.utils.progress import PipelineProgress, tracked_block

from resumate.prompts.templates import (
    SYSTEM_SKILLS,
    SYSTEM_COVER,
    SYSTEM_EMAILS,
    SYSTEM_ATS,
)

logger = logging.getLogger("resumate")


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
    Full workflow -- generator that yields (task_name, value) tuples:
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

    yield ("progress", "Indexing your profile documents...")
    with tracked_block("index_profile_docs", progress):
        index_profile_docs(user_data_dir)

    yield ("progress", "Analyzing job description...")
    with tracked_block("index_jd_text", progress):
        index_jd_text(jd_text, user_data_dir)

    yield ("progress", "Retrieving relevant context...")
    with tracked_block("retrieve_jd_focus", progress):
        jd_focus = retrieve("List must-have requirements and responsibilities.", k=6, doc_type="jd", db_path=db_path)
    with tracked_block("retrieve_profile_focus", progress):
        profile_focus = retrieve("Find bullets that prove impact, results, metrics.", k=6, doc_type="profile", db_path=db_path)
    with tracked_block("format_retrieved_docs", progress):
        rag_jd = format_docs(jd_focus)
        rag_profile = format_docs(profile_focus)

    yield ("progress", "Extracting keywords & computing skill alignment...")
    with tracked_block("extract_keywords", progress):
        jd_hard, jd_soft, keywords = extract_keywords(jd_text)
    with tracked_block("compute_alignment", progress):
        have_hard, have_soft, gaps = compute_alignment(profile.get("skills", []), jd_hard, jd_soft)

    yield ("progress", "Building context for generation...")
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

    _TASK_DEFS: list[tuple[str, str, str]] = [
        ("skills", SYSTEM_SKILLS, str(LLM_MAX_TOKENS.get("skills", 450))),
        ("cover", SYSTEM_COVER, str(LLM_MAX_TOKENS.get("cover", 650))),
        ("emails", SYSTEM_EMAILS, str(LLM_MAX_TOKENS.get("emails", 700))),
        ("ats", SYSTEM_ATS, str(LLM_MAX_TOKENS.get("ats", 280))),
    ]

    def _tracked_gen_stream(
        task_name: str, system_prompt: str, context: str, max_tokens: int,
    ) -> Iterator[tuple[str, Any]]:
        gen_key = f"gen_{task_name}"
        if progress is not None:
            progress.start(gen_key)
        t0 = perf_counter()
        parts: list[str] = []
        try:
            for chunk in stream_prompt(
                system_prompt, context, max_tokens,
                task_name=gen_key, stage="generation",
            ):
                parts.append(chunk)
                yield ("token", {"task": task_name, "chunk": chunk})
        except Exception as exc:
            if _is_connection_error(exc):
                time.sleep(2)
                parts.clear()
                try:
                    for chunk in stream_prompt(
                        system_prompt, context, max_tokens,
                        task_name=gen_key, stage="generation",
                    ):
                        parts.append(chunk)
                        yield ("token", {"task": task_name, "chunk": chunk})
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
        yield (task_name, "".join(parts))

    results: dict[str, str] = {}
    with tracked_block("generation_sequential", progress):
        for task_name, sys_prompt, max_tok in _TASK_DEFS:
            for event in _tracked_gen_stream(task_name, sys_prompt, task_ctx[task_name], int(max_tok)):
                if event[0] == task_name:
                    results[task_name] = event[1]
                yield event

    if save_to_disk:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        (OUT_DIR / f"{ts}_skills_keywords.md").write_text(results.get("skills", ""), encoding="utf-8")
        (OUT_DIR / f"{ts}_cover_letter.md").write_text(results.get("cover", ""), encoding="utf-8")
        (OUT_DIR / f"{ts}_emails.md").write_text(results.get("emails", ""), encoding="utf-8")
        (OUT_DIR / f"{ts}_ats_summary.md").write_text(results.get("ats", ""), encoding="utf-8")

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
