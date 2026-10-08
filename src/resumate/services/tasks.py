"""
Decomposed generation tasks.

Each public runner (run_cover / run_emails / run_skills / run_ats) is a
generator yielding ("token", {"task", "chunk"}) events while it works and a
final (task_name, full_text) event — the same contract the SSE route and the
frontend already consume. Inside, a task is several small model calls; all
structure (headings, keyword lists, sign-offs, email delimiters) is written by
code, and every model-written bullet is validated against the evidence item
it cites, retried once with the specific problem, then grounded as a fallback.
"""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass, field
from typing import Any, Iterator

from resumate.config.settings import task_options
from resumate.models.llm import chat_stream
from resumate.prompts import templates as T
from resumate.services.analysis import JobAnalysis
from resumate.services.evidence import EvidenceItem, EvidenceSet
from resumate.services.validate import (
    clean_line, clean_prose, drop_unsupported, first_sentences, ground_line,
    has_ungrounded_number, line_problems,
)

logger = logging.getLogger("resumate")

Event = tuple[str, Any]


@dataclass
class TaskContext:
    shared_prefix: str
    analysis: JobAnalysis
    evidence: EvidenceSet
    profile: dict
    jd_text: str = ""
    flags: list[str] = field(default_factory=list)

    @property
    def name(self) -> str:
        name = (self.profile.get("name") or "").strip()
        return name.title() if name.isupper() else name

    @property
    def grounding(self) -> str:
        """Text every number in prose must come from: the candidate's evidence + the JD."""
        return "\n".join([*(it.text for it in self.evidence.items), self.jd_text])

    @property
    def candidate_tools(self) -> list[str]:
        return [*self.allowed_tools, *(t for it in self.evidence.items for t in it.tools)]

    @property
    def title(self) -> str:
        return (self.profile.get("title") or "").strip() or "Professional"

    @property
    def role(self) -> str:
        return self.analysis.role_title or "this"

    @property
    def allowed_tools(self) -> list[str]:
        return [*self.profile.get("skills", []), *self.evidence.skills]


# ---------------------------------------------------------------------------
# Model call helper
# ---------------------------------------------------------------------------
def _is_connection_error(exc: Exception) -> bool:
    text = f"{type(exc).__name__} {exc}".lower()
    return any(kw in text for kw in ("disconnected", "connectionerror", "connect error", "remoteprotocol", "timeout"))


def _call(ctx: TaskContext, task: str, instructions: str, *, prefill: str | None = None,
          stop: list[str] | None = None, num_predict: int | None = None, label: str = "") -> Iterator[str]:
    """Stream one model call. Retries once on a connection error before the first token."""
    opts = task_options(task)
    if num_predict:
        opts["num_predict"] = num_predict
    if stop:
        opts["stop"] = stop
    messages = [{"role": "user", "content": ctx.shared_prefix + "\n\n" + instructions}]
    name = f"gen_{task}" + (f":{label}" if label else "")
    for attempt in (1, 2):
        started = False
        try:
            for piece in chat_stream(messages, options=opts, prefill=prefill, task_name=name):
                started = True
                yield piece
            return
        except Exception as exc:
            if attempt == 1 and not started and _is_connection_error(exc):
                time.sleep(2)
                continue
            raise RuntimeError(f"[{name}] failed: {exc}") from exc


def _collect(ctx: TaskContext, task: str, instructions: str, **kw) -> str:
    return "".join(_call(ctx, task, instructions, **kw))


def _tok(task: str, chunk: str) -> Event:
    return ("token", {"task": task, "chunk": chunk})


def _validated_line(ctx: TaskContext, task: str, instructions: str, item: EvidenceItem,
                    label: str, num_predict: int = 70) -> str:
    """One-line generation with evidence validation, one targeted retry, then grounding."""
    first = clean_line(_collect(ctx, task, instructions, stop=["\n"], num_predict=num_predict, label=label))
    probs = line_problems(first, item, ctx.allowed_tools)
    if not probs:
        return first
    second = clean_line(_collect(ctx, task, instructions + T.retry_suffix(first, probs),
                                 stop=["\n"], num_predict=num_predict, label=label + ":retry"))
    probs2 = line_problems(second, item, ctx.allowed_tools)
    best = second if len(probs2) <= len(probs) else first
    remaining = probs2 if best is second else probs
    if not remaining:
        return best
    ctx.flags.append(f"{task}/{label} [{item.id}]: {'; '.join(remaining)}")
    if any("tools" in p for p in remaining):
        # An unsupported tool claim can't be repaired by substitution: fall back to
        # the candidate's own wording of this achievement, which is true by construction.
        return clean_line(item.text)
    return ground_line(best, item)


# ---------------------------------------------------------------------------
# Cover letter
# ---------------------------------------------------------------------------
def _jd_term(a: JobAnalysis) -> str:
    """A concrete phrase from the JD the letter should echo."""
    for req in a.requirements:
        for t in a.have:
            if t.lower() in req.lower():
                return t
    return (a.have or a.jd_terms or [a.role_title or "this role"])[0]


def run_cover(ctx: TaskContext) -> Iterator[Event]:
    a = ctx.analysis
    items = [p.item for p in a.pairs[:2]] or a.selected[:2]
    greeting = "Dear Hiring Manager,\n\n"
    yield _tok("cover", greeting)
    parts: list[str] = []
    for piece in _call(ctx, "cover", T.cover_task(ctx.role, a.company, _jd_term(a), items),
                       prefill=greeting, stop=T.SIGN_OFF_STOPS):
        parts.append(piece)
        yield _tok("cover", piece)
    body, flags = clean_prose("".join(parts))
    body, removed = drop_unsupported(body, grounding=ctx.grounding)
    ctx.flags += [f"cover: {f}" for f in flags] + [f"cover: dropped unsupported sentence: {r}" for r in removed]
    paras = [re.sub(r"\s+", " ", p).strip() for p in re.split(r"\n\s*\n", body) if p.strip()]
    paras = [p for p in paras if not p.lower().startswith("dear ")][:3]
    sign_off = f"\n\nSincerely,\n{ctx.name}" if ctx.name else "\n\nSincerely,"
    yield _tok("cover", sign_off)
    yield ("cover", greeting + "\n\n".join(paras) + sign_off)


# ---------------------------------------------------------------------------
# Emails — 3 calls, frontend delimiter format written by code
# ---------------------------------------------------------------------------
_GREETINGS = {1: "Dear Hiring Manager,", 2: "Hi there,", 3: "Dear Hiring Manager,"}
_EMAIL_PREDICT = {1: 220, 2: 150, 3: 150}


def _email_items(a: JobAnalysis) -> dict[int, EvidenceItem | None]:
    paired = [p.item for p in a.pairs]
    with_metrics = sorted(a.selected, key=lambda it: -len(it.metrics))
    pool = paired + [it for it in with_metrics if it not in paired]
    first = pool[0] if pool else None
    outreach = next((it for it in with_metrics if it.metrics), first)
    second = next((it for it in pool if it not in (first, outreach)), first)
    return {1: first, 2: outreach, 3: second}


def _fallback_subject(kind: int, ctx: TaskContext) -> str:
    company = f" at {ctx.analysis.company}" if ctx.analysis.company else ""
    who = f" – {ctx.name}" if ctx.name else ""
    return {1: f"Application: {ctx.role}{company}{who}",
            2: f"{ctx.role}{company}: quick introduction{who}",
            3: f"Following up: {ctx.role} application{who}"}[kind]


def _split_email(raw: str, kind: int) -> tuple[str, str]:
    text, _ = clean_prose(raw)
    lines = text.strip().split("\n")
    subject = re.sub(r"^\s*Subject:\s*", "", lines[0], flags=re.I).strip() if lines else ""
    body = "\n".join(lines[1:]).strip()
    body = re.sub(r"^\s*Body:\s*", "", body, flags=re.I)
    # Replace whatever greeting the model wrote with the fixed one.
    body_lines = body.split("\n")
    if body_lines and re.match(r"^\s*(dear|hi|hello|hey)\b", body_lines[0], re.I):
        body_lines = body_lines[1:]
    body = "\n".join(body_lines).strip()
    paras = [re.sub(r"[ \t]+", " ", p).strip() for p in re.split(r"\n\s*\n", body) if p.strip()]
    return subject, _GREETINGS[kind] + "\n\n" + "\n\n".join(paras)


def run_emails(ctx: TaskContext) -> Iterator[Event]:
    a = ctx.analysis
    items = _email_items(a)
    sign_off = f"\n\nBest regards,\n{ctx.name}" if ctx.name else "\n\nBest regards,"
    blocks: list[str] = []
    for kind in (1, 2, 3):
        label = T.EMAIL_KINDS[kind][0]
        header = ("" if kind == 1 else "\n\n") + f"=== Email {kind}: {label} ===\nSubject: "
        yield _tok("emails", header)
        parts: list[str] = []
        for piece in _call(ctx, "emails", T.email_task(kind, ctx.role, a.company, items[kind]),
                           prefill="Subject: ", stop=T.SIGN_OFF_STOPS,
                           num_predict=_EMAIL_PREDICT[kind], label=label.lower().replace(" ", "_")):
            parts.append(piece)
            yield _tok("emails", piece)
        yield _tok("emails", sign_off)
        subject, body = _split_email("".join(parts), kind)
        # Subjects are short claims: their numbers must come from this email's own evidence.
        subject_grounding = " ".join([items[kind].text if items[kind] else "", ctx.role, a.company])
        if not subject or has_ungrounded_number(subject, subject_grounding) or len(subject.split()) > 14:
            ctx.flags.append(f"emails/{label}: replaced subject {subject!r}")
            subject = _fallback_subject(kind, ctx)
        greeting, _, rest = body.partition("\n\n")
        rest, removed = drop_unsupported(rest, grounding=ctx.grounding)
        ctx.flags += [f"emails/{label}: dropped unsupported sentence: {r}" for r in removed]
        body = greeting + "\n\n" + rest
        blocks.append(f"=== Email {kind}: {label} ===\nSubject: {subject}\nBody:\n{body}{sign_off}")
    yield ("emails", "\n\n".join(blocks))


# ---------------------------------------------------------------------------
# Skills — headings and keyword lists in code; model writes sentences/lines
# ---------------------------------------------------------------------------
def _bullet_plan(a: JobAnalysis, n: int = 4) -> list[tuple[EvidenceItem, str | None]]:
    plan: list[tuple[EvidenceItem, str | None]] = [(p.item, p.requirement) for p in a.pairs[:n]]
    used = {it.id for it, _ in plan}
    for it in a.selected:
        if len(plan) == n:
            break
        if it.id not in used and it.section != "summary":
            plan.append((it, None))
            used.add(it.id)
    return plan


def run_skills(ctx: TaskContext) -> Iterator[Event]:
    a = ctx.analysis
    out: list[str] = []

    def emit(text: str) -> Event:
        out.append(text)
        return _tok("skills", text)

    yield emit("## Match Snapshot\n")
    strengths = a.have[:3] or [p.requirement for p in a.pairs[:2]]
    snap = "".join(_call(ctx, "skills", T.snapshot_task(a.band, ctx.role, strengths),
                         prefill="You ", stop=["\n\n"], num_predict=60, label="snapshot"))
    sentence = first_sentences(clean_line(re.sub(r"\s+", " ", snap)), 1)
    if len(sentence.split()) < 4 or has_ungrounded_number(sentence, ctx.grounding):
        sentence = (f"are a {a.band.lower()} match for the {ctx.role} role, "
                    f"with {', '.join(strengths[:3]) or 'relevant experience'} already on your profile.")
    yield emit("You " + sentence)

    have = ", ".join(a.have[:8]) or "none of the JD's named tools yet"
    missing = ", ".join(a.missing[:8]) or "none — you cover every tool the JD names"
    yield emit(f"\n\n## ATS Keywords\n- **Already on your profile:** {have}\n"
               f"- **Missing from your profile:** {missing}\n\n## Tailored Resume Bullets\n")

    for n, (item, req) in enumerate(_bullet_plan(a), 1):
        line = _validated_line(ctx, "skills", T.bullet_task(item, req), item, label=f"bullet{n}")
        yield emit(f"- {line}\n")

    yield emit("\n## Gap to Close\n")
    if a.top_gap:
        gap: list[str] = []
        for piece in _call(ctx, "skills", T.gap_task(a.top_gap, a.gap_terms, a.have[:4]),
                           stop=["\n\n"], num_predict=90, label="gap"):
            gap.append(piece)
            yield _tok("skills", piece)
        text, _ = clean_prose("".join(gap))
        out.append(first_sentences(text, 2))
    else:
        yield emit("No major gaps against this job's stated requirements.")
    yield ("skills", "".join(out).strip())


# ---------------------------------------------------------------------------
# ATS summary
# ---------------------------------------------------------------------------
def _ats_items(a: JobAnalysis, skills_used: set[str], n: int = 3) -> list[EvidenceItem]:
    """Prefer evidence not already used by skills bullets 1-2 (avoid repeating content)."""
    ranked = [p.item for p in a.pairs] + [it for it in a.selected if it not in [p.item for p in a.pairs]]
    fresh = [it for it in ranked if it.id not in skills_used and it.section != "summary"]
    rest = [it for it in ranked if it not in fresh and it.section != "summary"]
    return (fresh + rest)[:n]


def run_ats(ctx: TaskContext) -> Iterator[Event]:
    a = ctx.analysis
    prefill = f"{ctx.title} with"
    yield _tok("ats", prefill)
    parts: list[str] = []
    for piece in _call(ctx, "ats", T.ats_summary_task(ctx.role, a.have[:3]),
                       prefill=prefill, stop=["\n"], num_predict=100, label="summary"):
        parts.append(piece)
        yield _tok("ats", piece)
    summary, _ = clean_prose(prefill + "".join(parts))
    summary = first_sentences(summary, 2)
    # Resume voice claims: drop sentences naming tools the candidate doesn't have
    # (the model likes to copy the JD's stack) or carrying invented numbers.
    summary, removed = drop_unsupported(summary, grounding=ctx.grounding, allowed_tools=ctx.candidate_tools)
    ctx.flags += [f"ats: dropped unsupported sentence: {r}" for r in removed]
    if not summary.startswith(ctx.title):
        # The opening (prefilled) sentence was dropped: restore a factual one.
        opener = f"{ctx.title} with hands-on experience in {', '.join(a.have[:3]) or 'the core stack'}."
        summary = first_sentences((opener + " " + summary).strip(), 2)

    stack = a.core_stack or ctx.profile.get("skills", [])[:8]
    core = f"\n\nCore Stack: {', '.join(stack)}\n"
    yield _tok("ats", core)

    skills_used = {it.id for it, _ in _bullet_plan(a)[:2]}
    lines: list[str] = []
    for n, item in enumerate(_ats_items(a, skills_used), 1):
        line = _validated_line(ctx, "ats", T.ats_outcome_task(item), item, label=f"outcome{n}", num_predict=60)
        lines.append(f"- {line}")
        yield _tok("ats", f"- {line}\n")
    yield ("ats", summary + core + "\n".join(lines))


__all__ = ["TaskContext", "run_cover", "run_emails", "run_skills", "run_ats"]
