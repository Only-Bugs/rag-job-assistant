"""
generator.py
High-level generation helpers and the overall application workflow.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from time import perf_counter
from typing import Any, Callable, Dict, Optional

from rag.config.settings import LLM_MAX_TOKENS, LLM_PARALLEL_WORKERS, OUT_DIR
from rag.utils.resources import effective_parallel_workers
from rag.profile import load_profile
from rag.utils.exceptions import ProfileNotConfiguredError
from rag.ingestion.ingest import index_profile_docs, index_jd_text
from rag.retrieval.retriever import retrieve, format_docs
from rag.ingestion.preprocessing.keywords import extract_keywords, compute_alignment
from rag.generation.context_builder import build_context, build_task_context
from rag.models.llm.ollama_client import run_prompt
from rag.utils.logging import get_request_id, set_request_id, timed
from ui.components.logboard import GEN_PARALLEL_KEYS, PipelineProgress, tracked_block

from rag.generation.prompts.templates import (
    SYSTEM_SKILLS,
    SYSTEM_COVER,
    SYSTEM_EMAILS,
    SYSTEM_ATS,
)


@timed
def gen_skills(context: str) -> str:
    return run_prompt(SYSTEM_SKILLS, context, max_tokens=int(LLM_MAX_TOKENS.get("skills", 450)))


@timed
def gen_cover(context: str) -> str:
    return run_prompt(SYSTEM_COVER, context, max_tokens=int(LLM_MAX_TOKENS.get("cover", 650)))


@timed
def gen_emails(context: str) -> str:
    return run_prompt(SYSTEM_EMAILS, context, max_tokens=int(LLM_MAX_TOKENS.get("emails", 700)))


@timed
def gen_ats(context: str) -> str:
    return run_prompt(SYSTEM_ATS, context, max_tokens=int(LLM_MAX_TOKENS.get("ats", 280)))


@timed
def generate_application_package(
    jd_text: str,
    save_to_disk: bool = False,
    progress: Optional[PipelineProgress] = None,
) -> Dict[str, Any]:
    """
    Full workflow:
    1. Index profile docs and this JD.
    2. Retrieve focused snippets.
    3. Extract skills/keywords + compute alignment.
    4. Build the consolidated context block.
    5. Generate skills, cover letter, emails, ATS summary.
    """
    profile = load_profile()
    if not profile:
        raise ProfileNotConfiguredError(
            "USER_PROFILE is not set. Use the UI profile settings or edit data/job_rag/profile_settings.json."
        )

    if progress is not None:
        progress.pipeline_start()
    try:
        return _generate_application_package_body(
            jd_text, save_to_disk, progress, profile
        )
    finally:
        if progress is not None:
            progress.pipeline_end()


def _generate_application_package_body(
    jd_text: str,
    save_to_disk: bool,
    progress: Optional[PipelineProgress],
    profile: Dict[str, Any],
) -> Dict[str, Any]:
    with tracked_block("index_profile_docs", progress):
        index_profile_docs()
    with tracked_block("index_jd_text", progress):
        index_jd_text(jd_text)

    with tracked_block("retrieve_jd_focus", progress):
        jd_focus = retrieve("List must-have requirements and responsibilities.", k=6, doc_type="jd")
    with tracked_block("retrieve_profile_focus", progress):
        profile_focus = retrieve("Find bullets that prove impact, results, metrics.", k=6, doc_type="profile")
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

    parallel_workers_effective = effective_parallel_workers(int(LLM_PARALLEL_WORKERS))

    meta = {
        "workers": parallel_workers_effective,
        "workers_configured": int(LLM_PARALLEL_WORKERS),
    }

    def _run_generation_tasks() -> tuple[str, str, str, str]:
        workers = parallel_workers_effective
        request_id = get_request_id()

        def _tracked_gen(gen_key: str, fn: Callable[[str], str], context: str) -> str:
            set_request_id(request_id)
            t0 = perf_counter()
            try:
                return fn(context)
            except Exception:
                if progress is not None:
                    progress.finish(gen_key, "error", (perf_counter() - t0) * 1000)
                raise
            else:
                if progress is not None:
                    progress.finish(gen_key, "ok", (perf_counter() - t0) * 1000)

        if progress is not None:
            for gk in GEN_PARALLEL_KEYS:
                progress.start(gk)

        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = {
                "skills": executor.submit(_tracked_gen, "gen_skills", gen_skills, task_ctx["skills"]),
                "cover": executor.submit(_tracked_gen, "gen_cover", gen_cover, task_ctx["cover"]),
                "emails": executor.submit(_tracked_gen, "gen_emails", gen_emails, task_ctx["emails"]),
                "ats": executor.submit(_tracked_gen, "gen_ats", gen_ats, task_ctx["ats"]),
            }
            return (
                futures["skills"].result(),
                futures["cover"].result(),
                futures["emails"].result(),
                futures["ats"].result(),
            )

    with tracked_block("generation_parallel_bundle", progress, metadata=meta):
        skills_out, cover_out, emails_out, ats_out = _run_generation_tasks()

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
