"""
High-level generation helpers and the overall application workflow.
"""

from __future__ import annotations

import logging
from datetime import datetime
from time import perf_counter
from typing import Any, Dict, Iterator, Optional

from pathlib import Path

from resumate.config.settings import OUT_DIR, RAG_DIR
from resumate.services.profile import load_profile
from resumate.utils.exceptions import ProfileNotConfiguredError
from resumate.services.ingestion import index_profile_docs, index_jd_text
from resumate.services.retrieval import retrieve, format_docs
from resumate.services.keywords import extract_keywords, compute_alignment
from resumate.services.context_builder import build_shared_context, jd_for_prompt
from resumate.services.evidence import load_evidence
from resumate.services.jd_sections import parse_jd
from resumate.services.analysis import analyse
from resumate.services.tasks import TaskContext, run_ats, run_cover, run_emails, run_skills
from resumate.utils.progress import PipelineProgress, tracked_block
from resumate.prompts.templates import SHARED_SYSTEM

logger = logging.getLogger("resumate")


def generate_application_package(
    jd_text: str,
    save_to_disk: bool = False,
    progress: Optional[PipelineProgress] = None,
    user_data_dir: Path | None = None,
    force: bool = False,
) -> Iterator[tuple[str, Any]]:
    """
    Full workflow -- generator that yields (event, value) tuples:
      ("progress", str), ("token", {task, chunk}),
      ("cover" | "emails" | "skills" | "ats", str),
      ("blocked", dict)  <- JD judged outside the profile's domain (unless force)
      ("_meta", dict)    <- analysis, keywords, flags

    1. Build ID'd evidence from the profile docs; trim the JD to its requirements.
    2. Analyse in code: keywords, match band, gap, requirement->evidence pairs, domain guard.
    3. Run each task as several small, validated model calls (services/tasks.py).

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
            jd_text, save_to_disk, progress, profile, user_data_dir, force
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
    force: bool = False,
) -> Iterator[tuple[str, Any]]:
    db_path = (user_data_dir / "chroma_db") if user_data_dir else None
    user_dir = user_data_dir or RAG_DIR

    yield ("progress", "Indexing your profile documents...")
    with tracked_block("index_profile_docs", progress):
        index_profile_docs(user_data_dir)
    with tracked_block("load_evidence", progress):
        evidence = load_evidence(user_dir, profile)

    yield ("progress", "Analyzing job description...")
    with tracked_block("parse_jd", progress):
        jd = parse_jd(jd_text)
    if jd.structured:
        jd_prompt_text = jd.text
        rag_jd = ""
    else:
        # No recognisable headings: fall back to intro + retrieved requirement chunks.
        with tracked_block("index_jd_text", progress):
            index_jd_text(jd_text, user_data_dir)
        with tracked_block("retrieve_jd_focus", progress):
            rag_jd = format_docs(retrieve(
                "List must-have requirements and responsibilities.",
                k=6, doc_type="jd", db_path=db_path,
            ))
        jd_prompt_text = jd_for_prompt(jd_text, rag_jd)

    yield ("progress", "Matching your experience to the role...")
    with tracked_block("analyse", progress):
        analysis = analyse(jd, jd_text, profile, evidence)
    if not analysis.domain_ok and not force:
        yield ("blocked", {
            "message": (f"This role ({analysis.role_title or 'unknown role'}) looks outside your profile: "
                        f"none of its tools match your skills and the overall fit is low."),
            "role_title": analysis.role_title,
            "domain_similarity": round(analysis.domain_similarity, 3),
            "missing": analysis.missing[:8],
            "requirements": analysis.requirements[:4],
        })
        yield ("_meta", analysis.to_meta())
        return

    # Legacy fields kept for _meta consumers.
    with tracked_block("extract_keywords", progress):
        jd_hard, jd_soft, keywords = extract_keywords(jd_text)
        have_hard, have_soft, gaps = compute_alignment(profile.get("skills", []), jd_hard, jd_soft)

    yield ("progress", "Building context for generation...")
    with tracked_block("build_context", progress):
        # Shared prefix for every call: identical bytes => Ollama reuses the
        # prefilled KV cache, so only the first call pays for the full context.
        shared_prefix = SHARED_SYSTEM + "\n" + build_shared_context(profile, jd_prompt_text, analysis.selected)
    ctx = TaskContext(shared_prefix=shared_prefix, analysis=analysis, evidence=evidence,
                      profile=profile, jd_text=jd_text)

    # Order matches the UI tabs: cover -> emails -> skills -> ats.
    runners = (("cover", run_cover), ("emails", run_emails), ("skills", run_skills), ("ats", run_ats))
    results: dict[str, str] = {}
    with tracked_block("generation_sequential", progress):
        for task_name, runner in runners:
            gen_key = f"gen_{task_name}"
            if progress is not None:
                progress.start(gen_key)
            t0 = perf_counter()
            try:
                for event in runner(ctx):
                    if event[0] == task_name:
                        results[task_name] = event[1]
                    yield event
            except Exception:
                if progress is not None:
                    progress.finish(gen_key, "error", (perf_counter() - t0) * 1000)
                raise
            if progress is not None:
                progress.finish(gen_key, "ok", (perf_counter() - t0) * 1000)
    if ctx.flags:
        logger.info("generation flags: %s", ctx.flags)

    if save_to_disk:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        (OUT_DIR / f"{ts}_skills_keywords.md").write_text(results.get("skills", ""), encoding="utf-8")
        (OUT_DIR / f"{ts}_cover_letter.md").write_text(results.get("cover", ""), encoding="utf-8")
        (OUT_DIR / f"{ts}_emails.md").write_text(results.get("emails", ""), encoding="utf-8")
        (OUT_DIR / f"{ts}_ats_summary.md").write_text(results.get("ats", ""), encoding="utf-8")

    yield ("_meta", {
        **analysis.to_meta(),
        "jd_hard": jd_hard,
        "jd_soft": jd_soft,
        "keywords": keywords,
        "have_hard": have_hard,
        "have_soft": have_soft,
        "gaps": gaps,
        "jd_dropped_sections": jd.dropped_sections,
        "flags": ctx.flags,
    })


# Backwards-compatible alias for legacy imports
generate_all_from_jd = generate_application_package


__all__ = [
    "generate_application_package",
    "generate_all_from_jd",
]
