"""
Deterministic checks over generated application material.

Used by scripts/eval_prompts.py to score runs, and intended to be reused by the
runtime validators (Phase 5). Every check returns plain data (lists / bools) so
results serialise straight to JSON.
"""

from __future__ import annotations

import re
from typing import Any

from resumate.utils.metrics import METRIC_RE, metric_key, metric_keys

TASKS = ("cover", "emails", "skills", "ats")
# Tasks whose output is plain text (no markdown allowed).
PLAIN_TEXT_TASKS = {"cover", "emails", "ats"}
SKILLS_SECTIONS = ("## Match Snapshot", "## ATS Keywords", "## Tailored Resume Bullets", "## Gap to Close")
BLOCKED_MARKER = "Outside Your Profile Domain"

_PLACEHOLDER_RE = re.compile(r"\[[^\]\n]{2,40}\]")
_ALLOWED_PLACEHOLDERS = {"[add metric]"}
_BULLET_PREFIXES = ("-", "*", "•")
_EMAIL_SPLIT_RE = re.compile(r"\**={2,}\s*Email\s*(\d+)\s*(?::[^=\n]*)?={2,}\**", re.I)


def ungrounded_numbers(text: str, evidence: str, *, bullets_only: bool = False) -> list[str]:
    """Numbers in `text` (or only its bullet lines) whose metric key is absent from `evidence`."""
    grounded = metric_keys(evidence)
    lines = text.split("\n")
    if bullets_only:
        lines = [l for l in lines if l.lstrip().startswith(_BULLET_PREFIXES)]
    out: list[str] = []
    for line in lines:
        for m in METRIC_RE.finditer(line):
            if metric_key(m.group(0)) not in grounded:
                out.append(m.group(0).strip())
    return out


def markdown_leaks(text: str) -> list[str]:
    """Markdown constructs that should not appear in plain-text outputs."""
    leaks: list[str] = []
    if "**" in text:
        leaks.append("**")
    if "`" in text:
        leaks.append("`")
    for line in text.split("\n"):
        s = line.lstrip()
        if s.startswith("#"):
            leaks.append("heading: " + s[:40])
        elif s.startswith("* "):
            leaks.append("star-bullet: " + s[:40])
    return leaks


def placeholders(text: str) -> list[str]:
    return [p for p in _PLACEHOLDER_RE.findall(text) if p not in _ALLOWED_PLACEHOLDERS]


def parse_emails(raw: str) -> list[dict[str, Any]]:
    """Python port of frontend/shared/common.js parseEmails()."""
    blocks = _EMAIL_SPLIT_RE.split(raw)[1:]
    emails = []
    for i in range(0, len(blocks), 2):
        num = int(blocks[i])
        text = (blocks[i + 1] if i + 1 < len(blocks) else "").strip()
        subj = re.search(r"^\W*Subject:\W*\s*(.+)", text, re.I | re.M)
        body = re.search(r"Body:\**\s*\n?([\s\S]*)", text, re.I)
        if body:
            body_text = body.group(1)
        elif subj:
            body_text = text[subj.end():]
        else:
            body_text = text
        emails.append({
            "index": num,
            "subject": subj.group(1).replace("**", "").strip() if subj else "",
            "body": body_text.replace("**", "").strip(),
        })
    return emails


def format_problems(task: str, text: str) -> list[str]:
    """Shape problems that would break or degrade the frontend rendering."""
    probs: list[str] = []
    t = text.strip()
    if not t:
        return ["empty output"]
    if task == "emails":
        emails = parse_emails(t)
        if [e["index"] for e in emails] != [1, 2, 3]:
            probs.append(f"expected emails 1,2,3 got {[e['index'] for e in emails]}")
        for e in emails:
            if not e["subject"]:
                probs.append(f"email {e['index']}: no subject")
            if len(e["body"].split()) < 15:
                probs.append(f"email {e['index']}: body too short")
    elif task == "skills":
        if BLOCKED_MARKER in t:
            return probs
        for sec in SKILLS_SECTIONS:
            if sec not in t:
                probs.append(f"missing section {sec}")
        if "## Tailored Resume Bullets" in t:
            part = t.split("## Tailored Resume Bullets", 1)[1].split("##", 1)[0]
            n = sum(1 for l in part.split("\n") if l.lstrip().startswith(_BULLET_PREFIXES))
            if n != 4:
                probs.append(f"expected 4 bullets, got {n}")
    elif task == "ats":
        lines = [l.strip() for l in t.split("\n") if l.strip()]
        if not any(l.startswith("Core Stack:") for l in lines):
            probs.append("missing 'Core Stack:' line")
        n = sum(1 for l in lines if l.startswith(_BULLET_PREFIXES))
        if n != 3:
            probs.append(f"expected 3 outcome lines, got {n}")
    elif task == "cover":
        if not t.startswith("Dear"):
            probs.append("does not start with a greeting")
        paras = [p for p in re.split(r"\n\s*\n", t) if p.strip()]
        if len(paras) < 4:  # greeting + 3 body paragraphs (+ sign-off)
            probs.append(f"only {len(paras)} paragraphs")
    return probs


def run_checks(
    task: str,
    text: str,
    *,
    profile_evidence: str,
    jd_text: str,
    prompt_tokens_est: int | None = None,
    num_ctx: int | None = None,
) -> dict[str, Any]:
    """All checks for one task output. Empty lists / True mean pass."""
    # Email delimiter lines ("=== Email 2: … ===") carry structural numbers.
    content = _EMAIL_SPLIT_RE.sub("", text) if task == "emails" else text
    result: dict[str, Any] = {
        # Prose may legitimately quote JD numbers ("5,000+ engineers").
        "invented_numbers": ungrounded_numbers(content, profile_evidence + "\n" + jd_text),
        "format_problems": format_problems(task, text),
        "placeholders": placeholders(text),
    }
    if task in ("skills", "ats"):
        # Resume bullets must only carry the candidate's own numbers.
        result["bullet_numbers_not_in_profile"] = ungrounded_numbers(text, profile_evidence, bullets_only=True)
    if task in PLAIN_TEXT_TASKS:
        result["markdown_leaks"] = markdown_leaks(text)
    if prompt_tokens_est is not None and num_ctx:
        result["prompt_tokens_est"] = prompt_tokens_est
        result["prompt_fits_ctx"] = prompt_tokens_est < num_ctx
    result["failures"] = sum(
        len(v) for k, v in result.items() if isinstance(v, list)
    ) + (0 if result.get("prompt_fits_ctx", True) else 1)
    return result


__all__ = [
    "TASKS", "PLAIN_TEXT_TASKS", "BLOCKED_MARKER",
    "ungrounded_numbers", "markdown_leaks", "placeholders",
    "parse_emails", "format_problems", "run_checks",
]
