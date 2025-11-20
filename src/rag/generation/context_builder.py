"""
context_builder.py
Construct the composite context block fed into generation prompts.
"""

from __future__ import annotations

from typing import List, Dict

from rag.utils.text import bullet_list


def build_context(
    profile: Dict,
    jd_text: str,
    jd_snips: str,
    prof_snips: str,
    jd_hard: List[str],
    jd_soft: List[str],
    keywords: List[str],
    have_hard: List[str],
    have_soft: List[str],
    gaps: List[str],
) -> str:
    """Combine profile, JD, snippets, keywords, and alignment summary."""
    return f"""
[PROFILE]
Name: {profile['name']} | Title: {profile['title']} | Location: {profile['location']}
Email: {profile['email']} | Phone: {profile['phone']} | Links: {", ".join(profile['links'])}

Pitch:
{profile['pitch']}

Skills:
{bullet_list(profile['skills'])}

Achievements:
{bullet_list(profile['achievements'])}

[JOB_DESCRIPTION_RAW]
{jd_text}

[RETRIEVED_JD_SNIPPETS]
{jd_snips}

[RETRIEVED_PROFILE_SNIPPETS]
{prof_snips}

[EXTRACTED_FROM_JD]
Hard skills: {", ".join(jd_hard)}
Soft skills: {", ".join(jd_soft)}
Extra keywords: {", ".join(keywords[:30])}

[ALIGNMENT_SUMMARY]
You already have (hard): {", ".join(have_hard)}
You already have (soft): {", ".join(have_soft)}
Gaps to phrase carefully: {", ".join(gaps)}
"""


__all__ = ["build_context"]
