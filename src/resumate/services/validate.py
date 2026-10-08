"""
Output validation for generated lines and prose.

Lines (resume bullets, ATS outcome lines) are checked against the single
evidence item they cite: every number must be one of that item's metrics and
every named tool must be on that item or the candidate's skill list.
Prose (cover letter, emails) is sanitised: markdown and placeholders removed.
"""

from __future__ import annotations

import re

from resumate.services.evidence import EvidenceItem, tools_in
from resumate.utils.metrics import METRIC_RE, is_grounded, metric_keys
from resumate.utils.text import HARD_SKILL_LEXICON

MAX_LINE_WORDS = 32
_PLACEHOLDER_RE = re.compile(r"\[(?!add metric\])[^\]\n]{2,40}\]")
_IRREGULAR_PAST = {
    "built", "led", "ran", "made", "cut", "wrote", "drove", "grew", "won", "set", "took", "gave",
    "kept", "met", "shipped", "spearheaded", "brought", "sold", "taught", "began", "chose", "found",
    "held", "lent", "rebuilt", "redid", "overhauled", "oversaw", "put", "rewrote", "sped", "split",
}


def clean_line(text: str) -> str:
    """Normalise a model-written single line: strip bullets, quotes, markdown, trailing junk."""
    s = text.strip().split("\n")[0].strip()
    s = re.sub(r"^\s*(?:[-*•▪]\s*|\d+[.)]\s*)", "", s)
    s = s.replace("**", "").replace("`", "").strip().strip('"“”').strip()
    # The model sometimes echoes the evidence render format ("… Tools: X. Metrics: Y").
    s = re.sub(r"\s*\(?\b(?:Tools|Metrics)\s*:.*$", "", s).strip()
    s = re.sub(r"\s*\[E\d+\]", "", s).strip()
    if s and s[-1] not in ".!?)":
        s += "."
    return s


def line_problems(text: str, item: EvidenceItem, allowed_tools: list[str]) -> list[str]:
    """
    Problems with a bullet/outcome line that cites `item`. Empty list = valid.
    Tools must appear in the cited item itself — a skill the candidate has
    elsewhere is still a false claim when attached to this achievement.
    `allowed_tools` only widens the vocabulary used to *detect* tool names.
    """
    probs: list[str] = []
    grounded = metric_keys(item.text)
    bad_nums = [m.group(0).strip() for m in METRIC_RE.finditer(text) if not is_grounded(m.group(0), grounded)]
    if bad_nums:
        probs.append(f"uses numbers not in [{item.id}]: {', '.join(bad_nums)}")
    vocab = sorted({*HARD_SKILL_LEXICON, *allowed_tools, *item.tools}, key=str.lower)
    item_text = item.text.lower()
    bad_tools = [t for t in tools_in(text, vocab) if t.lower() not in item_text]
    if bad_tools:
        probs.append(f"names tools that [{item.id}] does not mention: {', '.join(bad_tools)}")
    words = text.split()
    if len(words) > MAX_LINE_WORDS:
        probs.append(f"too long ({len(words)} words; keep it to one line)")
    first = words[0].lower().strip(",.") if words else ""
    if first and not (first.endswith("ed") or first in _IRREGULAR_PAST):
        probs.append("must start with a past-tense action verb")
    if _PLACEHOLDER_RE.search(text):
        probs.append("contains a bracketed placeholder")
    return probs


def ground_line(text: str, item: EvidenceItem) -> str:
    """Fallback: replace numbers not in the cited item with [add metric]."""
    grounded = metric_keys(item.text)
    return METRIC_RE.sub(lambda m: m.group(0) if is_grounded(m.group(0), grounded) else "[add metric]", text)


def clean_prose(text: str) -> tuple[str, list[str]]:
    """Strip markdown and drop sentences carrying [placeholders]. Returns (text, flags)."""
    flags: list[str] = []
    s = text.replace("**", "").replace("`", "")
    s = re.sub(r"(?m)^\s*#{1,6}\s*", "", s)
    s = re.sub(r"(?m)^\s*[*•]\s+", "", s)
    if _PLACEHOLDER_RE.search(s):
        flags.append("removed placeholder sentences")
        kept = []
        for para in re.split(r"\n\s*\n", s):
            sentences = re.split(r"(?<=[.!?])\s+", para.strip())
            sentences = [x for x in sentences if not _PLACEHOLDER_RE.search(x)]
            if sentences:
                kept.append(" ".join(sentences))
        s = "\n\n".join(kept)
    return s.strip(), flags


def split_sentences(text: str) -> list[str]:
    return [x for x in re.split(r"(?<=[.!?])\s+", text.strip()) if x]


def drop_unsupported(text: str, *, grounding: str, allowed_tools: list[str] | None = None) -> tuple[str, list[str]]:
    """
    Remove sentences that carry a number not found in `grounding` or (when
    `allowed_tools` is given) name a known tool the candidate doesn't have.
    Paragraph breaks are preserved. Returns (text, removed sentences).
    """
    grounded = metric_keys(grounding)
    allowed = {t.lower() for t in allowed_tools} if allowed_tools is not None else None
    vocab = sorted({*HARD_SKILL_LEXICON, *(allowed_tools or [])}, key=str.lower)
    removed: list[str] = []
    paras = []
    for para in re.split(r"\n\s*\n", text.strip()):
        kept = []
        for sent in split_sentences(para):
            bad_num = any(not is_grounded(m.group(0), grounded) for m in METRIC_RE.finditer(sent))
            bad_tool = allowed is not None and any(t.lower() not in allowed for t in tools_in(sent, vocab))
            (removed if bad_num or bad_tool else kept).append(sent)
        if kept:
            paras.append(" ".join(kept))
    return "\n\n".join(paras), removed


def has_ungrounded_number(text: str, grounding: str) -> bool:
    grounded = metric_keys(grounding)
    return any(not is_grounded(m.group(0), grounded) for m in METRIC_RE.finditer(text))


def first_sentences(text: str, n: int) -> str:
    parts = re.split(r"(?<=[.!?])\s+", text.strip())
    return " ".join(parts[:n]).strip()


__all__ = ["clean_line", "line_problems", "ground_line", "clean_prose", "drop_unsupported",
           "has_ungrounded_number", "split_sentences", "first_sentences", "MAX_LINE_WORDS"]
