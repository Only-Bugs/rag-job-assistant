"""
keywords.py
JD keyword extraction and alignment helpers.
"""

from __future__ import annotations

import re
from typing import List, Tuple

from rag.utils.text import (
    normalize_text,
    tokenize_lower,
    top_terms,
    fuzzy_match_candidates,
    HARD_SKILL_LEXICON,
    SOFT_SKILL_LEXICON,
    fuzzy_overlap,
)


def extract_keywords(jd_text: str) -> Tuple[List[str], List[str], List[str]]:
    """Tokenise the JD and extract hard skills, soft skills, and keywords."""
    jd_norm = normalize_text(jd_text)
    toks = tokenize_lower(jd_norm)
    cands = top_terms(toks, topn=80, min_len=2)

    jd_hard = fuzzy_match_candidates(cands, HARD_SKILL_LEXICON, cutoff=86)
    jd_soft = fuzzy_match_candidates(cands, SOFT_SKILL_LEXICON, cutoff=86)

    caps = sorted(set(re.findall(r"\b([A-Z][a-zA-Z0-9\-\+&/]{1,})\b", jd_text)))
    hard_lower_map = {s.lower(): s for s in HARD_SKILL_LEXICON}
    extra = fuzzy_match_candidates([c.lower() for c in caps], hard_lower_map.keys(), cutoff=90)
    extra_cased = [hard_lower_map.get(e, e) for e in extra]

    jd_hard = sorted({s for s in (set(jd_hard) | set(extra_cased)) if s})

    known = {t.lower() for t in jd_hard + jd_soft}
    keywords = [t for t in cands if t not in known and len(t) >= 3]

    return jd_hard, jd_soft, keywords


def compute_alignment(profile_skills: List[str], jd_hard: List[str], jd_soft: List[str]):
    """Compare candidate skills vs JD demands to surface overlaps/gaps."""
    have_hard = sorted({m[1] for m in fuzzy_overlap(profile_skills, jd_hard, cutoff=88)})
    have_soft = sorted({m[1] for m in fuzzy_overlap(profile_skills, jd_soft, cutoff=88)})
    gaps = [s for s in jd_hard + jd_soft if s not in set(have_hard + have_soft)]
    return have_hard, have_soft, gaps


__all__ = ["extract_keywords", "compute_alignment"]
