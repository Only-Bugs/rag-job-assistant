"""
Deterministic job analysis — everything a small model shouldn't be asked to do.

Given the trimmed JD and the candidate's evidence, compute once per run:
- which JD tools/keywords the candidate has vs is missing (set intersection),
- how well the evidence covers the JD requirements (embedding similarity),
- a match band, the top gap, the domain verdict (guard),
- requirement -> evidence pairs that each prompt is asked to write about,
- the ATS "Core Stack" line.

The model only turns these decisions into sentences.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

import numpy as np

from resumate.services.evidence import EvidenceItem, EvidenceSet, tools_in
from resumate.services.jd_sections import JDSections
from resumate.utils.text import HARD_SKILL_LEXICON, SOFT_SKILL_LEXICON

logger = logging.getLogger("resumate")

# Cosine similarity (all-MiniLM-L6-v2) at which an evidence item counts as
# covering a requirement. Calibrated on tests/fixtures/eval (see DEVLOG in PR).
COVER_SIM = 0.40
# Domain guard: block only when BOTH signals say "unrelated". In-domain JDs share
# tools with the profile; an unrelated JD (e.g. nursing) shares none and has low
# whole-document similarity.
DOMAIN_MIN_SHARED_TERMS = 2
DOMAIN_MIN_SIM = 0.30
MAX_REQUIREMENTS = 10
N_PAIRS = 4

# Requirement lines that are about eligibility, not skills — no evidence bullet
# can "prove" them, so they're never paired or reported as the gap.
_ELIGIBILITY_RE = re.compile(
    r"\b(degree|bachelor|master'?s|phd|working rights|visa|citizen|police check|"
    r"registration|licen[cs]e|clearance|years? of|\d\+?\s*years?)\b", re.I)
# Soft-skill lines ("Strong communication and ownership") are never paired with a
# bullet: embedding similarity on them is noise.
_SOFT_RE = re.compile(r"\b(" + "|".join(re.escape(s.split()[0].lower()) for s in SOFT_SKILL_LEXICON)
                      + r"|stakeholder|ownership|team|mentor|passion|self-starter|curious)\w*", re.I)
# Bonus per requirement tool also listed on the evidence item.
TOOL_BONUS = 0.08


@dataclass
class Pair:
    requirement: str
    item: EvidenceItem
    similarity: float


@dataclass
class JobAnalysis:
    role_title: str
    company: str
    jd_terms: list[str]                      # tools/keywords the JD asks for, in JD order
    have: list[str]                          # jd_terms the candidate can claim
    missing: list[str]                       # jd_terms the candidate can't
    requirements: list[str]                  # ranked skill requirements considered
    coverage: dict[str, float]               # requirement -> best evidence similarity
    match_score: float
    band: str                                # Strong | Moderate | Stretch
    top_gap: str | None                      # requirement (or term) least covered
    gap_terms: list[str]                     # missing tools named in top_gap (may be empty)
    pairs: list[Pair]
    selected: list[EvidenceItem]             # evidence placed in the shared prompt
    core_stack: list[str]
    domain_ok: bool
    domain_similarity: float
    notes: list[str] = field(default_factory=list)

    def to_meta(self) -> dict:
        return {
            "role_title": self.role_title, "company": self.company,
            "jd_terms": self.jd_terms, "have": self.have, "missing": self.missing,
            "match_score": round(self.match_score, 3), "band": self.band, "top_gap": self.top_gap,
            "gap_terms": self.gap_terms,
            "pairs": [{"requirement": p.requirement, "evidence_id": p.item.id, "similarity": round(p.similarity, 3)}
                      for p in self.pairs],
            "evidence_ids": [it.id for it in self.selected], "core_stack": self.core_stack,
            "domain_ok": self.domain_ok, "domain_similarity": round(self.domain_similarity, 3),
            "coverage": {k: round(v, 3) for k, v in self.coverage.items()},
        }


def _norm(v: np.ndarray) -> np.ndarray:
    n = np.linalg.norm(v, axis=-1, keepdims=True)
    return v / np.where(n == 0, 1, n)


def _embed(texts: list[str]) -> np.ndarray:
    from resumate.models.embeddings import get_embeddings
    if not texts:
        return np.zeros((0, 384))
    return _norm(np.asarray(get_embeddings().embed_documents(texts), dtype=np.float32))


def _matches(term: str, pool_lower: set[str]) -> bool:
    t = term.lower()
    if t in pool_lower:
        return True
    # "AWS (Lambda, API Gateway)" style pool entries, or "Node" vs "Node.js".
    return any(t in p or p in t for p in pool_lower if min(len(p), len(t)) >= 3)


def _terms_in_line(line: str, terms: list[str]) -> list[str]:
    low = line.lower()
    return [t for t in terms if t.lower() in low]


def _rank_requirements(jd: JDSections, jd_terms: list[str]) -> list[str]:
    """Lines naming JD tools first; requirements before responsibilities; eligibility lines dropped."""
    lines = [l for l in jd.requirements + jd.responsibilities + jd.nice_to_have if len(l.split()) >= 3]
    scored = []
    for i, line in enumerate(lines):
        hits = len(_terms_in_line(line, jd_terms))
        if _ELIGIBILITY_RE.search(line) and not hits:
            continue
        section_bias = 0 if line in jd.requirements else 1 if line in jd.responsibilities else 2
        scored.append((0 if hits else 1, section_bias, -hits, i, line))
    scored.sort()
    return [s[-1] for s in scored][:MAX_REQUIREMENTS]


def _is_soft(line: str, jd_terms: list[str]) -> bool:
    return bool(_SOFT_RE.search(line)) and not _terms_in_line(line, jd_terms)


def analyse(jd: JDSections, jd_text: str, profile: dict, evidence: EvidenceSet, k_selected: int = 5) -> JobAnalysis:
    items = evidence.items
    # ---- keywords: exact vocabulary matching (more reliable than fuzzy for tool names)
    candidate_terms = [*profile.get("skills", []), *evidence.skills, *(t for it in items for t in it.tools)]
    vocab = sorted({*HARD_SKILL_LEXICON, *candidate_terms}, key=str.lower)
    jd_terms = tools_in(jd_text, vocab)
    low = jd_text.lower()
    jd_terms.sort(key=lambda t: low.find(t.lower()))
    pool = {t.lower() for t in candidate_terms}
    have = [t for t in jd_terms if _matches(t, pool)]
    missing = [t for t in jd_terms if t not in have]

    # ---- requirement coverage by evidence similarity
    requirements = _rank_requirements(jd, jd_terms)
    req_vecs = _embed(requirements)
    item_vecs = _embed([it.text for it in items])
    sims = req_vecs @ item_vecs.T if len(requirements) and len(items) else np.zeros((len(requirements), len(items)))
    # Pair score = similarity + bonus for each requirement tool the item names.
    req_terms = [_terms_in_line(r, jd_terms) for r in requirements]
    bonus = np.array([[TOOL_BONUS * len({t.lower() for t in rt} & {t.lower() for t in it.tools})
                       for it in items] for rt in req_terms], dtype=np.float32).reshape(sims.shape)
    scores = sims + bonus
    coverage = {r: float(scores[i].max()) if scores.shape[1] else 0.0 for i, r in enumerate(requirements)}
    have_lower = {t.lower() for t in have}

    def _covered(i: int, r: str) -> bool:
        return coverage[r] >= COVER_SIM or any(t.lower() in have_lower for t in req_terms[i])

    covered = sum(1 for i, r in enumerate(requirements) if _covered(i, r))
    cov_ratio = covered / len(requirements) if requirements else 0.0
    term_ratio = len(have) / len(jd_terms) if jd_terms else 0.0
    match_score = 0.6 * cov_ratio + 0.4 * term_ratio
    band = "Strong" if match_score >= 0.6 else "Moderate" if match_score >= 0.4 else "Stretch"

    # ---- domain guard (whole-document similarity + shared tools)
    profile_doc = " ".join([profile.get("title", ""), profile.get("pitch", ""),
                            *(it.text for it in items[:12])])
    jd_doc = " ".join([jd.role_title, *requirements[:8]]) or jd_text[:1500]
    dv = _embed([profile_doc, jd_doc])
    domain_similarity = float(dv[0] @ dv[1]) if len(dv) == 2 else 0.0
    domain_ok = len(have) >= DOMAIN_MIN_SHARED_TERMS or domain_similarity >= DOMAIN_MIN_SIM

    # ---- pairs: top requirements, each with a distinct best evidence item
    pairs: list[Pair] = []
    used: set[str] = set()
    for i, req in enumerate(requirements):
        if len(pairs) == N_PAIRS or not items:
            break
        if _is_soft(req, jd_terms):
            continue
        for j in np.argsort(-scores[i]):
            it = items[int(j)]
            if it.id in used or it.section == "summary":
                continue
            if float(scores[i][j]) < COVER_SIM * 0.8:
                break
            pairs.append(Pair(requirement=req, item=it, similarity=float(scores[i][j])))
            used.add(it.id)
            break

    # ---- the gap: first requirement naming a missing tool, else the least-covered
    # hard-skill requirement (there is always something to strengthen).
    missing_lower = {t.lower() for t in missing}
    top_gap = next((r for i, r in enumerate(requirements)
                    if any(t.lower() in missing_lower for t in req_terms[i])), None)
    if top_gap is None:
        hard = [(coverage[r], r) for r in requirements if not _is_soft(r, jd_terms)]
        top_gap = min(hard)[1] if hard else (missing[0] if missing else None)
    gap_terms = [t for t in missing if top_gap and t.lower() in top_gap.lower()]

    # ---- evidence for the shared prompt: paired items first, then best remaining
    selected = [p.item for p in pairs]
    if len(selected) < k_selected and len(items):
        best_per_item = scores.max(axis=0) if scores.size else np.zeros(len(items))
        for j in np.argsort(-best_per_item):
            it = items[int(j)]
            if it not in selected and it.section != "summary":
                selected.append(it)
            if len(selected) == k_selected:
                break
    order = {it.id: n for n, it in enumerate(items)}
    selected.sort(key=lambda it: order[it.id])

    result = JobAnalysis(
        role_title=jd.role_title, company=jd.company, jd_terms=jd_terms, have=have, missing=missing,
        requirements=requirements, coverage=coverage, match_score=match_score, band=band,
        top_gap=top_gap, gap_terms=gap_terms, pairs=pairs, selected=selected, core_stack=have[:8],
        domain_ok=domain_ok, domain_similarity=domain_similarity,
    )
    logger.info("analysis: band=%s score=%.2f domain_ok=%s (sim=%.2f, shared=%d) pairs=%s",
                band, match_score, domain_ok, domain_similarity, len(have), [p.item.id for p in pairs])
    return result


__all__ = ["JobAnalysis", "Pair", "analyse", "COVER_SIM"]
