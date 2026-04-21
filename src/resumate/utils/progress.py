"""Thread-safe pipeline progress tracker.

Extracted from ui/components/logboard.py — no Streamlit dependency.
"""

from __future__ import annotations

import threading
from contextlib import contextmanager
from dataclasses import dataclass
from time import perf_counter
from typing import Any, Iterator, Literal, Mapping, Optional


StageStatus = Literal["pending", "running", "done", "error"]


@dataclass
class _Stage:
    label: str
    running_hint: str
    status: StageStatus = "pending"
    duration_ms: Optional[float] = None


_STAGE_DEFS: dict[str, tuple[str, str]] = {
    "index_profile_docs": ("Reading your profile", "Pulling in your CV and profile docs..."),
    "index_jd_text": ("Analysing the job posting", "Breaking down the role so we match it well..."),
    "retrieve_jd_focus": ("Matching role requirements", "Finding the must-haves in this JD..."),
    "retrieve_profile_focus": ("Surfacing your highlights", "Locating your strongest proof points..."),
    "format_retrieved_docs": ("Organising snippets", "Lining up evidence from you and the role..."),
    "extract_keywords": ("Extracting keywords", "Spotting skills and phrases recruiters scan for..."),
    "compute_alignment": ("Checking fit", "Mapping what you have to what they need..."),
    "build_context": ("Building your brief", "Assembling the story we will write from..."),
    "generation_sequential": ("Generating your application pack", "Running generation tasks sequentially..."),
    "gen_skills": ("Crafting your skills summary", "Shaping skills and keywords that resonate..."),
    "gen_cover": ("Writing your cover letter", "Crafting a compelling story about you..."),
    "gen_emails": ("Drafting outreach emails", "Tuning emails that sound like you..."),
    "gen_ats": ("Optimising for ATS", "Tightening a scanner-friendly summary..."),
}


class PipelineProgress:
    """Thread-safe progress tracker for ``generate_application_package``."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._stages: dict[str, _Stage] = {
            k: _Stage(label=v[0], running_hint=v[1]) for k, v in _STAGE_DEFS.items()
        }
        self._pipeline_start: Optional[float] = None
        self._pipeline_end: Optional[float] = None

    def pipeline_start(self) -> None:
        with self._lock:
            self._pipeline_start = perf_counter()
            self._pipeline_end = None

    def pipeline_end(self) -> None:
        with self._lock:
            self._pipeline_end = perf_counter()

    def start(self, key: str) -> None:
        with self._lock:
            if key not in self._stages:
                self._stages[key] = _Stage(label=key, running_hint="Working...")
            self._stages[key].status = "running"
            self._stages[key].duration_ms = None

    def finish(self, key: str, status: Literal["ok", "error"], duration_ms: float) -> None:
        with self._lock:
            if key not in self._stages:
                self._stages[key] = _Stage(label=key, running_hint="Working...")
            self._stages[key].status = "done" if status == "ok" else "error"
            self._stages[key].duration_ms = duration_ms

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "stages": {k: (s.label, s.running_hint, s.status, s.duration_ms) for k, s in self._stages.items()},
                "pipeline_start": self._pipeline_start,
                "pipeline_end": self._pipeline_end,
            }


@contextmanager
def tracked_block(
    key: str,
    progress: Optional[PipelineProgress],
    metadata: Mapping[str, Any] | None = None,
) -> Iterator[None]:
    from resumate.utils.logging import timed_block

    if progress is not None:
        progress.start(key)
    start = perf_counter()
    try:
        with timed_block(key, metadata=metadata):
            yield
    except Exception:
        if progress is not None:
            progress.finish(key, "error", (perf_counter() - start) * 1000)
        raise
    if progress is not None:
        progress.finish(key, "ok", (perf_counter() - start) * 1000)


__all__ = ["PipelineProgress", "tracked_block"]
