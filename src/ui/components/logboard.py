"""
Thread-safe pipeline progress + toast UI for Streamlit.

Default rendering uses ``streamlit.components.v1.html`` (iframe). Optional
``use_viewport_st_html=True`` uses ``st.html`` for a viewport-fixed toast that
inherits the app's Streamlit ``--color-*`` CSS variables.
"""

from __future__ import annotations

import html
import threading
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from time import perf_counter
from typing import Any, Iterator, Literal, Mapping, Optional

import streamlit as st

StageStatus = Literal["pending", "running", "done", "error"]


@dataclass
class _Stage:
    label: str
    running_hint: str
    status: StageStatus = "pending"
    duration_ms: Optional[float] = None


_STAGE_DEFS: dict[str, tuple[str, str]] = {
    "index_profile_docs": ("Reading your profile", "Pulling in your CV and profile docs…"),
    "index_jd_text": ("Analysing the job posting", "Breaking down the role so we match it well…"),
    "retrieve_jd_focus": ("Matching role requirements", "Finding the must-haves in this JD…"),
    "retrieve_profile_focus": ("Surfacing your highlights", "Locating your strongest proof points…"),
    "format_retrieved_docs": ("Organising snippets", "Lining up evidence from you and the role…"),
    "extract_keywords": ("Extracting keywords", "Spotting skills and phrases recruiters scan for…"),
    "compute_alignment": ("Checking fit", "Mapping what you have to what they need…"),
    "build_context": ("Building your brief", "Assembling the story we will write from…"),
    "generation_parallel_bundle": (
        "Generating your application pack",
        "Running the heavy lifting in parallel — almost there…",
    ),
    "gen_skills": ("Crafting your skills summary", "Shaping skills and keywords that resonate… hang tight"),
    "gen_cover": ("Writing your cover letter", "Crafting a compelling story about you and this company… hang tight"),
    "gen_emails": ("Drafting outreach emails", "Tuning emails that sound like you… hang tight"),
    "gen_ats": ("Optimising for ATS", "Tightening a scanner-friendly summary… hang tight"),
}

_ORDER_MAIN = [
    "index_profile_docs",
    "index_jd_text",
    "retrieve_jd_focus",
    "retrieve_profile_focus",
    "format_retrieved_docs",
    "extract_keywords",
    "compute_alignment",
    "build_context",
]

GEN_PARALLEL_KEYS = ("gen_skills", "gen_cover", "gen_emails", "gen_ats")


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
                self._stages[key] = _Stage(label=key, running_hint="Working…")
            self._stages[key].status = "running"
            self._stages[key].duration_ms = None

    def finish(self, key: str, status: Literal["ok", "error"], duration_ms: float) -> None:
        with self._lock:
            if key not in self._stages:
                self._stages[key] = _Stage(label=key, running_hint="Working…")
            self._stages[key].status = "done" if status == "ok" else "error"
            self._stages[key].duration_ms = duration_ms

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "stages": {k: (s.label, s.running_hint, s.status, s.duration_ms) for k, s in self._stages.items()},
                "pipeline_start": self._pipeline_start,
                "pipeline_end": self._pipeline_end,
            }


def _format_duration_ms(ms: float) -> str:
    if ms >= 10000:
        return f"{ms / 1000:.1f}s"
    if ms >= 1000:
        return f"{ms / 1000:.2f}s"
    return f"{ms:.0f}ms"


def format_relative_time(ts: datetime) -> str:
    """Human-readable relative time from a naive local timestamp."""
    now = datetime.now()
    delta = now - ts
    secs = int(delta.total_seconds())
    if secs < 45:
        return "just now"
    if secs < 3600:
        m = max(1, secs // 60)
        return f"{m} min ago"
    if secs < 86400:
        h = max(1, secs // 3600)
        return f"{h} hr ago" if h == 1 else f"{h} hrs ago"
    if secs < 172800:
        return "yesterday"
    d = secs // 86400
    return f"{d} days ago"


def build_run_history_label(jd_text: str, profile: Mapping[str, Any]) -> str:
    first = next((ln.strip() for ln in jd_text.splitlines() if ln.strip()), "Job posting")
    company = (first[:80] + "…") if len(first) > 80 else first
    role = (profile.get("title") or profile.get("target_role") or "Role").strip() or "Role"
    return f"{company} — {role}"


@contextmanager
def tracked_block(
    key: str,
    progress: Optional[PipelineProgress],
    metadata: Mapping[str, Any] | None = None,
) -> Iterator[None]:
    from rag.utils.logging import timed_block

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


def _toast_css(*, iframe_mode: bool) -> str:
    pos_block = (
        """
  position: relative;
  width: 340px;
  max-width: 100%;
  align-self: flex-end;
  margin-top: auto;
"""
        if iframe_mode
        else """
  position: fixed;
  bottom: 20px;
  right: 20px;
  width: 340px;
  max-width: calc(100vw - 40px);
  z-index: 99999;
"""
    )
    return (
        """
<style>
#rag-toast {
  box-sizing: border-box;
"""
        + pos_block
        + """
  background: var(--color-background-primary, Canvas);
  color: var(--color-text-primary, CanvasText);
  border: 1px solid var(--color-border-secondary, ButtonBorder);
  border-radius: 10px;
  font-family: var(--font, system-ui, -apple-system, sans-serif);
  font-size: 0.875rem;
  line-height: 1.4;
  overflow: hidden;
}
#rag-toast summary {
  list-style: none;
  cursor: pointer;
}
#rag-toast summary::-webkit-details-marker { display: none; }
.rag-toast-head {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.65rem 0.75rem;
  border-bottom: 1px solid var(--color-border-secondary, ButtonBorder);
  background: var(--color-secondary-background-color, var(--color-background-secondary, Canvas));
}
.rag-toast-head-pulse {
  width: 10px;
  height: 10px;
  border-radius: 50%;
  background: #3b82f6;
  flex-shrink: 0;
  animation: rag-hpulse 1.2s ease-in-out infinite;
}
#rag-toast.rag-done .rag-toast-head-pulse {
  animation: none;
  background: #10b981;
}
@keyframes rag-hpulse {
  0%, 100% { opacity: 1; transform: scale(1); }
  50% { opacity: 0.45; transform: scale(0.9); }
}
.rag-toast-head-title {
  flex: 1;
  font-weight: 600;
  color: var(--color-text-primary);
}
.rag-toast-head-time {
  font-variant-numeric: tabular-nums;
  color: var(--color-text-secondary, var(--color-text-primary));
  font-size: 0.8rem;
}
.rag-toast-chevron {
  color: var(--color-text-secondary, var(--color-text-primary));
  font-size: 0.75rem;
  user-select: none;
}
#rag-toast:not([open]) .rag-toast-chevron-open { display: inline; }
#rag-toast:not([open]) .rag-toast-chevron-shut { display: none; }
#rag-toast[open] .rag-toast-chevron-open { display: none; }
#rag-toast[open] .rag-toast-chevron-shut { display: inline; }
.rag-toast-scroll {
  max-height: 300px;
  overflow-y: auto;
  padding: 0.4rem 0.65rem 0.5rem;
  scrollbar-width: thin;
  scrollbar-color: var(--color-border-secondary) transparent;
}
.rag-toast-scroll::-webkit-scrollbar { width: 6px; }
.rag-toast-scroll::-webkit-scrollbar-thumb {
  background: var(--color-border-secondary);
  border-radius: 4px;
}
.rag-stage-row {
  display: flex;
  align-items: flex-start;
  gap: 0.45rem;
  padding: 0.35rem 0;
  border-bottom: 1px solid var(--color-border-secondary);
}
.rag-stage-row:last-child { border-bottom: none; }
.rag-stage-pending { opacity: 0.3; }
.rag-stage-mid { flex: 1; min-width: 0; }
.rag-stage-label { font-weight: 500; color: var(--color-text-primary); }
.rag-stage-hint {
  font-size: 0.78rem;
  color: var(--color-text-secondary, var(--color-text-primary));
  margin-top: 0.15rem;
}
.rag-stage-row:not(.rag-stage-running) .rag-stage-hint { display: none; }
.rag-stage-dur {
  font-variant-numeric: tabular-nums;
  font-size: 0.78rem;
  color: var(--color-text-secondary, var(--color-text-primary));
  white-space: nowrap;
  align-self: center;
}
.rag-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  margin-top: 0.35rem;
  flex-shrink: 0;
  background: var(--color-border-secondary);
}
.rag-stage-running .rag-dot {
  background: #3b82f6;
  animation: rag-hpulse 1.2s ease-in-out infinite;
}
.rag-stage-done .rag-dot { background: #10b981; animation: none; }
.rag-stage-warn .rag-dot { background: #f59e0b; animation: none; }
.rag-gen-group {
  margin-top: 0.25rem;
  padding-left: 0.5rem;
  border-left: 2px solid var(--color-border-secondary);
}
.rag-gen-group .rag-stage-row { padding-left: 0.15rem; }
.rag-prev-wrap {
  margin-top: 0.35rem;
  padding-top: 0.35rem;
  border-top: 1px solid var(--color-border-secondary);
}
.rag-prev-wrap summary {
  font-size: 0.8rem;
  font-weight: 600;
  color: var(--color-text-secondary, var(--color-text-primary));
  padding: 0.25rem 0;
  cursor: pointer;
}
.rag-prev-list { list-style: none; margin: 0; padding: 0 0 0.35rem 0; }
.rag-prev-item {
  font-size: 0.78rem;
  padding: 0.35rem 0;
  border-bottom: 1px solid var(--color-border-secondary);
  color: var(--color-text-primary);
}
.rag-prev-item:last-child { border-bottom: none; }
.rag-prev-meta { color: var(--color-text-secondary, var(--color-text-primary)); font-size: 0.72rem; margin-top: 0.15rem; }
</style>
"""
    )


def _stage_row(key: str, stages: dict[str, Any], *, sub: bool = False) -> str:
    if key not in stages:
        return ""
    label, hint, status, duration_ms = stages[key]
    esc_label = html.escape(label)
    esc_hint = html.escape(hint)
    row_cls = ["rag-stage-row"]
    dot_cls = "rag-dot"
    dur_html = ""
    if status == "running":
        row_cls.append("rag-stage-running")
    elif status == "done" and duration_ms is not None:
        row_cls.append("rag-stage-done")
        dur_html = html.escape(_format_duration_ms(duration_ms))
    elif status == "error" and duration_ms is not None:
        row_cls.append("rag-stage-warn")
        dur_html = html.escape(_format_duration_ms(duration_ms))
    else:
        row_cls.append("rag-stage-pending")

    hint_block = f'<div class="rag-stage-hint">{esc_hint}</div>'
    dur_block = f'<div class="rag-stage-dur">{dur_html}</div>' if dur_html else '<div class="rag-stage-dur"></div>'
    sub_attr = ' style="padding-left:0"' if sub else ""
    return (
        f'<div class="{" ".join(row_cls)}"{sub_attr}>'
        f'<span class="{dot_cls}"></span>'
        f'<div class="rag-stage-mid"><div class="rag-stage-label">{esc_label}</div>{hint_block}</div>'
        f"{dur_block}</div>"
    )


def _normalize_ts(entry: Mapping[str, Any]) -> datetime:
    ts = entry.get("timestamp")
    if isinstance(ts, datetime):
        return ts
    if isinstance(ts, str):
        return datetime.fromisoformat(ts)
    return datetime.now()


def build_progress_toast_html(
    snapshot: Mapping[str, Any],
    run_history: list[dict[str, Any]],
    *,
    show_previous_runs: bool,
    previous_runs_open: bool,
    iframe_mode: bool = False,
) -> str:
    stages = snapshot["stages"]
    t0 = snapshot["pipeline_start"]
    t1 = snapshot["pipeline_end"]
    now = perf_counter()
    if t0 is None:
        elapsed_ms = 0.0
    elif t1 is not None:
        elapsed_ms = (t1 - t0) * 1000
    else:
        elapsed_ms = (now - t0) * 1000

    done = t1 is not None
    head_title = "Complete" if done else "Generating application pack"
    toast_cls = "rag-done" if done else ""
    open_attr = " open" if not done else ""

    parts: list[str] = [_toast_css(iframe_mode=iframe_mode), f'<details id="rag-toast" class="{toast_cls}"{open_attr}>']
    parts.append("<summary class=\"rag-toast-head\">")
    parts.append('<span class="rag-toast-head-pulse"></span>')
    parts.append(f'<span class="rag-toast-head-title">{html.escape(head_title)}</span>')
    parts.append(f'<span class="rag-toast-head-time">{html.escape(_format_duration_ms(elapsed_ms))}</span>')
    parts.append('<span class="rag-toast-chevron"><span class="rag-toast-chevron-open">▼</span>')
    parts.append('<span class="rag-toast-chevron-shut">▲</span></span>')
    parts.append("</summary>")

    parts.append('<div class="rag-toast-scroll">')
    for k in _ORDER_MAIN:
        parts.append(_stage_row(k, stages))
    parts.append(_stage_row("generation_parallel_bundle", stages))
    parts.append('<div class="rag-gen-group">')
    for gk in GEN_PARALLEL_KEYS:
        parts.append(_stage_row(gk, stages, sub=True))
    parts.append("</div>")

    if show_previous_runs and run_history:
        prev_open = " open" if previous_runs_open else ""
        parts.append(f'<div class="rag-prev-wrap"><details{prev_open}><summary>Previous runs</summary>')
        parts.append('<ul class="rag-prev-list">')
        for entry in reversed(run_history[-15:]):
            label = html.escape(str(entry.get("label", "Run")))
            dms = entry.get("duration_ms", 0)
            try:
                dstr = _format_duration_ms(float(dms))
            except (TypeError, ValueError):
                dstr = "—"
            rel = format_relative_time(_normalize_ts(entry))
            parts.append(
                f'<li class="rag-prev-item"><div>{label}</div>'
                f'<div class="rag-prev-meta">{html.escape(dstr)} · {html.escape(rel)}</div></li>'
            )
        parts.append("</ul></details></div>")

    parts.append("</div></details>")
    return "".join(parts)


def render_progress_toast(
    progress: PipelineProgress,
    run_history: list[dict[str, Any]],
    *,
    show_previous_runs: bool,
    previous_runs_open: bool,
    use_viewport_st_html: bool = False,
) -> None:
    """
    Render the toast via ``components.v1.html`` by default (iframe + Canvas fallbacks).

    Pass ``use_viewport_st_html=True`` for ``position:fixed`` on the host page via ``st.html``.
    """
    snap = progress.snapshot()
    inner = build_progress_toast_html(
        snap,
        run_history,
        show_previous_runs=show_previous_runs,
        previous_runs_open=previous_runs_open,
        iframe_mode=not use_viewport_st_html,
    )
    if use_viewport_st_html:
        st.html(inner)
        return

    import streamlit.components.v1 as components

    doc = (
        "<!DOCTYPE html><html><head><meta charset=\"utf-8\">"
        '<meta name="color-scheme" content="light dark">'
        "</head><body style=\"margin:0;background:transparent;display:flex;"
        "flex-direction:column;justify-content:flex-end;align-items:flex-end;"
        f'min-height:380px;">{inner}</body></html>'
    )
    components.html(doc, height=400, width=352, scrolling=False)


# Backwards compatibility
def render_logboard(progress: PipelineProgress) -> None:
    render_progress_toast(
        progress,
        [],
        show_previous_runs=False,
        previous_runs_open=False,
    )


__all__ = [
    "PipelineProgress",
    "tracked_block",
    "render_progress_toast",
    "render_logboard",
    "build_run_history_label",
    "format_relative_time",
    "build_progress_toast_html",
    "GEN_PARALLEL_KEYS",
]
