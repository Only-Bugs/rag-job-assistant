"""
Deterministic job-description trimming.

Splits a JD into headed sections, keeps the ones that describe the work
(responsibilities, requirements, skills…) and drops company boilerplate
(about us, benefits, EEO, how to apply). Also pulls out the role title and
company name so prompts can use them without asking the model.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from resumate.config.settings import JD_CHAR_LIMIT

_BULLET_RE = re.compile(r"^\s*(?:[-*•▪●◦‣·]|\d+[.)])\s+")

_KEEP_HINTS = (
    "responsib", "what you'll do", "what you will do", "the role", "about the role", "your role",
    "role overview", "duties", "day to day", "day-to-day", "requirement", "qualification",
    "about you", "what you'll bring", "what you will bring", "you have", "you will have",
    "skills", "experience", "nice to have", "preferred", "bonus", "desirable", "who you are",
    "what we're looking for", "what we are looking for", "the team", "about the team",
)
_DROP_HINTS = (
    "about us", "who we are", "our values", "our culture", "culture", "benefit", "perk",
    "what we offer", "why join", "why work", "diversity", "inclusion", "equal opportunity",
    "eeo", "how to apply", "to apply", "compensation", "salary", "our story", "life at",
)
# Ranked: requirement bullets from these sections matter most for matching.
_REQUIREMENT_HINTS = ("requirement", "qualification", "about you", "bring", "you have", "skills",
                      "experience", "looking for", "who you are")
_RESPONSIBILITY_HINTS = ("responsib", "what you'll do", "what you will do", "duties", "day to day",
                         "day-to-day", "the role", "your role")
_NICE_HINTS = ("nice to have", "preferred", "bonus", "desirable")


@dataclass
class JDSections:
    role_title: str = ""
    company: str = ""
    text: str = ""                          # trimmed JD for the prompt
    requirements: list[str] = field(default_factory=list)       # must-have lines, ranked
    responsibilities: list[str] = field(default_factory=list)
    nice_to_have: list[str] = field(default_factory=list)
    dropped_sections: list[str] = field(default_factory=list)
    structured: bool = False                # False => no headings found, caller may fall back

    @property
    def key_lines(self) -> list[str]:
        """Requirements first, then responsibilities, then nice-to-haves."""
        return self.requirements + self.responsibilities + self.nice_to_have


def _is_heading(line: str, next_line: str | None) -> bool:
    s = line.strip()
    if not s or _BULLET_RE.match(s) or len(s) > 60:
        return False
    if s.endswith(":"):
        return True
    words = s.split()
    if len(words) > 7 or s[-1] in ".!?,;":
        return False
    lowered = s.lower()
    if any(h in lowered for h in _KEEP_HINTS + _DROP_HINTS):
        return True
    # Short Title Case / ALL CAPS line followed by content.
    return bool(next_line) and (s.isupper() or s.istitle()) and len(words) <= 5


def _classify(heading: str) -> str:
    h = heading.lower().rstrip(":")
    if any(k in h for k in _DROP_HINTS):
        return "drop"
    if any(k in h for k in _NICE_HINTS):
        return "nice"
    if any(k in h for k in _REQUIREMENT_HINTS):
        return "requirements"
    if any(k in h for k in _RESPONSIBILITY_HINTS):
        return "responsibilities"
    return "keep"  # unknown headings are kept: dropping real requirements is worse than a few extra tokens


def _title_and_company(lines: list[str]) -> tuple[str, str]:
    nonempty = [l.strip() for l in lines if l.strip()]
    if not nonempty:
        return "", ""
    first = nonempty[0]
    parts = re.split(r"\s+[-–—|]\s+|\s+at\s+", first, maxsplit=1)
    role = parts[0].strip() if parts else first
    company = ""
    second = nonempty[1] if len(nonempty) > 1 else ""
    if second and len(second.split()) <= 8 and ":" not in second and not _BULLET_RE.match(second):
        company = re.split(r"\s*[,–—|]\s*|\s+-\s+", second, maxsplit=1)[0].strip()
    elif len(parts) > 1:
        company = re.split(r"\s*,\s*", parts[1], maxsplit=1)[0].strip()
    return role or first, company


def _strip_bullet(line: str) -> str:
    return _BULLET_RE.sub("", line).strip()


def parse_jd(jd_text: str, char_limit: int = JD_CHAR_LIMIT) -> JDSections:
    lines = [l.rstrip() for l in jd_text.replace("\r\n", "\n").split("\n")]
    role, company = _title_and_company(lines)
    out = JDSections(role_title=role, company=company)

    sections: list[tuple[str, str, list[str]]] = []  # (heading, kind, lines)
    preamble: list[str] = []
    current: tuple[str, str, list[str]] | None = None
    for i, line in enumerate(lines):
        nxt = next((l for l in lines[i + 1:] if l.strip()), None)
        if i > 0 and _is_heading(line, nxt):
            current = (line.strip().rstrip(":"), _classify(line), [])
            sections.append(current)
            continue
        # "About the team: blah" — inline heading + content on one line.
        m = re.match(r"^([A-Z][\w '’/&-]{2,40}):\s+(\S.*)$", line.strip())
        if i > 0 and m and not _BULLET_RE.match(line):
            kind = _classify(m.group(1))
            sections.append((m.group(1), kind, [m.group(2)]))
            current = None if kind == "drop" else sections[-1]
            continue
        if current is None:
            preamble.append(line)
        else:
            current[2].append(line)

    out.structured = any(kind != "keep" for _, kind, _ in sections)

    kept_blocks: list[str] = []
    header = "\n".join(l for l in preamble[:3] if l.strip())
    # Preamble beyond the title block is usually company intro; keep it short.
    intro = " ".join(l.strip() for l in preamble[3:] if l.strip())
    if intro:
        header += "\n" + (intro[:300] + ("…" if len(intro) > 300 else ""))
    if header.strip():
        kept_blocks.append(header.strip())

    for heading, kind, body in sections:
        content = [l for l in body if l.strip()]
        if kind == "drop":
            out.dropped_sections.append(heading)
            continue
        items = [_strip_bullet(l) for l in content]
        if kind == "requirements":
            out.requirements += items
        elif kind == "responsibilities":
            out.responsibilities += items
        elif kind == "nice":
            out.nice_to_have += items
        else:
            out.responsibilities += [x for x in items if len(x.split()) >= 3]
        kept_blocks.append(f"{heading}:\n" + "\n".join(content))

    text = "\n\n".join(kept_blocks).strip()
    if len(text) > char_limit:
        # Drop nice-to-haves first, then hard-cut.
        text = "\n\n".join(b for b in kept_blocks if not any(h in b.split("\n", 1)[0].lower() for h in _NICE_HINTS))
        if len(text) > char_limit:
            text = text[:char_limit].rsplit("\n", 1)[0] + "\n…"
    out.text = text
    return out


__all__ = ["JDSections", "parse_jd"]
