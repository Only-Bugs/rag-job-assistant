"""
Structured candidate evidence.

Turns the candidate's resume documents (and profile-settings achievements)
into discrete, ID'd evidence items — one per achievement bullet — with the
tools and metrics each one mentions extracted in code. Generation prompts cite
these IDs, and validators check every number/tool against the cited item.

Segmentation is deterministic and tuned for the common resume layout:
section headings (ALL CAPS or markdown), role lines with a date range,
bullets (▪ • - * …) whose wrapped continuation lines get re-joined. If a
document doesn't segment, it falls back to paragraph chunks so generation
still has (unstructured) evidence.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path

from rapidfuzz import fuzz

from resumate.utils.metrics import METRIC_RE
from resumate.utils.text import HARD_SKILL_LEXICON

logger = logging.getLogger("resumate")

_DOC_SUFFIXES = {".pdf", ".txt", ".md"}
_CACHE_FILE = "evidence.json"
_CACHE_VERSION = 2
_MIN_ITEMS = 4
# token_set_ratio thresholds, tuned on two versions of the same resume:
# rephrased duplicates within one role score >= 69, distinct bullets <= 61.
_DEDUPE_SAME_ROLE = 66
_DEDUPE_ANY = 85

_BULLET_RE = re.compile(r"^\s*(?:[▪•●◦‣·*]|-(?=\s))\s*")
_MONTH = r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)[a-z]*\.?"
_DATE = rf"(?:{_MONTH}\s+)?\d{{4}}"
_DATE_RANGE_RE = re.compile(rf"({_DATE})\s*[–—-]\s*({_DATE}|Present|Current|Now|Today)", re.I)
_SECTION_ALIASES = {
    "experience": ("experience", "employment", "work history", "professional history", "career history"),
    "projects": ("project",),
    "summary": ("summary", "profile", "about", "objective", "highlights"),
    "skills": ("skill", "technolog", "tools", "competenc"),
    "education": ("education", "qualification", "certification", "training"),
}


@dataclass
class EvidenceItem:
    id: str
    section: str                 # experience | projects | summary | settings | chunk
    text: str
    role: str = ""
    org: str = ""
    dates: str = ""
    tools: list[str] = field(default_factory=list)
    metrics: list[str] = field(default_factory=list)
    source: str = ""             # file name, or "profile settings"

    @property
    def label(self) -> str:
        return ", ".join(x for x in (self.role, self.org) if x) or self.section.title()

    def render(self) -> str:
        tools = ", ".join(self.tools) or "none"
        metrics = "; ".join(self.metrics) or "none"
        return f"[{self.id}] {self.label} | Tools: {tools} | Metrics: {metrics} | {self.text}"


@dataclass
class EvidenceSet:
    items: list[EvidenceItem]
    skills: list[str]            # resume KEY SKILLS terms + profile settings skills

    def by_id(self, eid: str) -> EvidenceItem | None:
        return next((it for it in self.items if it.id == eid), None)


# ---------------------------------------------------------------------------
# Text extraction
# ---------------------------------------------------------------------------
def _doc_text(path: Path) -> str:
    from resumate.services.resume_parser import extract_text
    return extract_text(path.read_bytes(), path.name)


# ---------------------------------------------------------------------------
# Segmentation
# ---------------------------------------------------------------------------
def _section_of(line: str) -> str | None:
    s = line.strip()
    md = re.match(r"^#{1,2}\s+(.*)$", s)
    if md:
        s = md.group(1).strip()
    elif s.startswith("#") or not (s.isupper() and 3 <= len(s) <= 40 and not _BULLET_RE.match(s)):
        return None
    lowered = s.lower()
    for name, aliases in _SECTION_ALIASES.items():
        if any(a in lowered for a in aliases):
            return name
    return "other"


def _split_role_line(line: str) -> tuple[str, str, str]:
    """'Data Analyst — Acme (Feb 2023 – Present)' / 'SDE May 2026 – Jul 2026' -> (role, org, dates)."""
    s = re.sub(r"^#{1,4}\s+", "", line.strip())
    m = _DATE_RANGE_RE.search(s)
    dates = m.group(0) if m else ""
    head = (s[: m.start()] + s[m.end():]) if m else s
    head = re.sub(r"[()|]", " ", head).strip(" ,–—-")
    parts = re.split(r"\s+[—–]\s+|\s+-\s+|\s+at\s+|\s*\|\s*", head, maxsplit=1)
    role = parts[0].strip()
    org = parts[1].strip() if len(parts) > 1 else ""
    return role, org, dates


def _looks_like_title(line: str, prev_bullet: str | None) -> bool:
    """A short capitalised line after a finished bullet starts a new project/role block."""
    s = line.strip()
    if not s or not s[0].isupper() or len(s.split()) > 6:
        return False
    return prev_bullet is None or prev_bullet.rstrip().endswith((".", "!", "?", ")"))


def segment_text(text: str, source: str) -> tuple[list[EvidenceItem], list[str]]:
    """Return (items without IDs, skills terms listed in a skills section)."""
    items: list[EvidenceItem] = []
    skills_terms: list[str] = []
    section = "summary"
    role = org = dates = ""
    expect_org = False
    awaiting_role = False
    bullet: list[str] | None = None

    def flush():
        nonlocal bullet
        if bullet:
            txt = re.sub(r"\s+", " ", " ".join(bullet)).strip()
            if len(txt.split()) >= 5 and section in ("experience", "projects", "summary", "other"):
                items.append(EvidenceItem(id="", section=section, text=txt, role=role, org=org,
                                          dates=dates, source=source))
        bullet = None

    for raw in text.replace("\r\n", "\n").split("\n"):
        line = raw.strip()
        if not line:
            continue
        sec = _section_of(line)
        if sec and not _DATE_RANGE_RE.search(line):
            flush()
            section, role, org, dates, expect_org, awaiting_role = sec, "", "", "", False, False
            continue
        if section == "skills":
            body = _BULLET_RE.sub("", line)
            body = body.split(" - ", 1)[-1] if " - " in body else body.split(":", 1)[-1]
            skills_terms += [t.strip(" .") for t in re.split(r",|;|\(|\)", body) if 1 < len(t.strip()) <= 30]
            continue
        if section == "education":
            continue
        if _BULLET_RE.match(line) and not re.match(r"^-\d", line):
            flush()
            bullet = [_BULLET_RE.sub("", line)]
            expect_org = awaiting_role = False
            continue
        if _DATE_RANGE_RE.search(line) and len(line.split()) <= 16:
            flush()
            role, org, dates = _split_role_line(line)
            expect_org = not org
            continue
        if expect_org:
            # Line after a role header: "Turtle Down Under Melbourne, VIC" — keep the org,
            # drop a trailing location (two spaces or a trailing "City, ST").
            org = re.split(r"\s{2,}", line)[0]
            org = re.sub(r"\s+[A-Z][a-z]+,\s*(?:[A-Z]{2,3}|[A-Z][a-z]+)$", "", org).strip()
            expect_org = False
            continue
        if bullet is not None and not _looks_like_title(line, bullet[-1]):
            bullet.append(line)  # wrapped continuation of the current bullet
            continue
        heading3 = re.match(r"^#{3,4}\s+(.*)$", line)
        if section in ("projects", "other") and (heading3 or _looks_like_title(line, bullet[-1] if bullet else None)):
            name = re.sub(r"\s*\((?:personal|side project|university|academic)\)\s*$", "", heading3.group(1) if heading3 else line, flags=re.I)
            had_bullets = bullet is not None
            flush()
            if had_bullets or not awaiting_role:
                # New project: "Resumate" — the next short line (if any) is the role.
                org, role, dates, awaiting_role = name.strip(), "", "", True
            else:
                role, awaiting_role = name.strip(), False
            continue
        # Role context / description lines are not evidence bullets.
        flush()
    flush()
    return items, skills_terms


# ---------------------------------------------------------------------------
# Tools / metrics / dedupe
# ---------------------------------------------------------------------------
def tools_in(text: str, vocabulary: list[str]) -> list[str]:
    found = []
    low = text.lower()
    for term in vocabulary:
        t = term.lower()
        if re.search(rf"(?<![\w.]){re.escape(t)}(?![\w])", low):
            found.append(term)
    # Prefer the longest form when one tool name contains another (React vs React Native).
    return [f for f in found if not any(f != g and f.lower() in g.lower() for g in found)]


def _metrics_in(text: str) -> list[str]:
    seen, out = set(), []
    for m in METRIC_RE.finditer(text):
        tok = m.group(0).strip().rstrip(".,")
        if tok not in seen:
            seen.add(tok)
            out.append(tok)
    return out


def _dedupe(items: list[EvidenceItem]) -> list[EvidenceItem]:
    """
    Drop near-duplicate bullets — the same achievement worded differently in two
    resume versions, or repeated in the summary. Keeps the richest version.
    """
    rank = {"experience": 0, "projects": 1, "settings": 2, "other": 3, "summary": 4, "chunk": 5}
    ordered = sorted(items, key=lambda it: (rank.get(it.section, 9), -(len(it.tools) + len(it.metrics)), -len(it.text)))
    kept: list[EvidenceItem] = []
    for it in ordered:
        dup = False
        for k in kept:
            close = it.label == k.label or "summary" in (it.section, k.section)
            if fuzz.token_set_ratio(it.text, k.text) >= (_DEDUPE_SAME_ROLE if close else _DEDUPE_ANY):
                # Keep the union of tools/metrics on the surviving item.
                k.tools = k.tools + [t for t in it.tools if t not in k.tools]
                dup = True
                break
        if not dup:
            kept.append(it)
    # Restore document order for stable, readable IDs.
    order = {id(it): i for i, it in enumerate(items)}
    return sorted(kept, key=lambda it: order[id(it)])


def _chunk_fallback(text: str, source: str) -> list[EvidenceItem]:
    paras = [re.sub(r"\s+", " ", p).strip() for p in re.split(r"\n\s*\n", text)]
    return [EvidenceItem(id="", section="chunk", text=p[:500], source=source)
            for p in paras if len(p.split()) >= 8]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
def build_evidence(profile_doc_dir: Path, profile: dict) -> EvidenceSet:
    items: list[EvidenceItem] = []
    skills_terms: list[str] = list(profile.get("skills", []))
    for path in sorted(profile_doc_dir.glob("*")) if profile_doc_dir.exists() else []:
        if not path.is_file() or path.suffix.lower() not in _DOC_SUFFIXES:
            continue
        try:
            text = _doc_text(path)
        except Exception as exc:  # unreadable doc shouldn't kill generation
            logger.warning("evidence: could not read %s: %s", path.name, exc)
            continue
        doc_items, doc_skills = segment_text(text, path.name)
        if len(doc_items) < _MIN_ITEMS:
            logger.info("evidence: %s segmented into %d items; using paragraph chunks", path.name, len(doc_items))
            doc_items = _chunk_fallback(text, path.name)
        items += doc_items
        skills_terms += doc_skills

    for ach in profile.get("achievements", []) or []:
        if isinstance(ach, str) and len(ach.split()) >= 5:
            items.append(EvidenceItem(id="", section="settings", text=ach.strip(), source="profile settings"))

    vocab = sorted({*HARD_SKILL_LEXICON, *skills_terms}, key=str.lower)
    for it in items:
        it.tools = tools_in(it.text, vocab)
        it.metrics = _metrics_in(it.text)
    items = _dedupe(items)
    for i, it in enumerate(items, 1):
        it.id = f"E{i}"
    skills = list(dict.fromkeys(t for t in skills_terms if t))
    return EvidenceSet(items=items, skills=skills)


def _fingerprint(profile_doc_dir: Path, profile: dict) -> str:
    h = hashlib.sha256()
    h.update(str(_CACHE_VERSION).encode())
    if profile_doc_dir.exists():
        for p in sorted(profile_doc_dir.glob("*")):
            if p.is_file() and p.suffix.lower() in _DOC_SUFFIXES:
                st = p.stat()
                h.update(f"{p.name}:{st.st_size}:{st.st_mtime_ns}".encode())
    h.update(json.dumps({"skills": profile.get("skills"), "achievements": profile.get("achievements")},
                        sort_keys=True).encode())
    return h.hexdigest()


def load_evidence(user_data_dir: Path, profile: dict) -> EvidenceSet:
    """Evidence for a user, cached in <user_data_dir>/evidence.json by profile fingerprint."""
    doc_dir = user_data_dir / "profile_docs"
    fp = _fingerprint(doc_dir, profile)
    cache = user_data_dir / _CACHE_FILE
    if cache.exists():
        try:
            data = json.loads(cache.read_text(encoding="utf-8"))
            if data.get("fingerprint") == fp:
                return EvidenceSet(items=[EvidenceItem(**d) for d in data["items"]], skills=data.get("skills", []))
        except Exception:
            pass
    ev = build_evidence(doc_dir, profile)
    try:
        cache.write_text(json.dumps({"fingerprint": fp, "items": [asdict(i) for i in ev.items],
                                     "skills": ev.skills}, indent=1), encoding="utf-8")
    except OSError as exc:
        logger.warning("evidence: could not write cache: %s", exc)
    logger.info("evidence: built %d items for %s", len(ev.items), user_data_dir.name)
    return ev


__all__ = ["EvidenceItem", "EvidenceSet", "build_evidence", "load_evidence", "segment_text", "tools_in"]
