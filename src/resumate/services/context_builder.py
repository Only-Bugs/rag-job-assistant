"""
Construct the composite context block fed into generation prompts.
"""

from __future__ import annotations

from typing import Dict, List, Literal

from resumate.config.settings import JD_CHAR_LIMIT, RETRIEVED_JD_CHAR_LIMIT, RETRIEVED_PROFILE_CHAR_LIMIT
from resumate.utils.text import bullet_list

TaskName = Literal["skills", "cover", "emails", "ats"]

# Shorter JD slice for email drafts (role + company cues) to avoid duplicating the full posting.
_EMAIL_JD_CHAR_LIMIT = 1500


def _trim(value: str, limit: int) -> str:
    if len(value) <= limit:
        return value
    return value[:limit] + "\n...[truncated for runtime]"


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
    jd_text_trimmed = _trim(jd_text, JD_CHAR_LIMIT)
    jd_snips_trimmed = _trim(jd_snips, RETRIEVED_JD_CHAR_LIMIT)
    prof_snips_trimmed = _trim(prof_snips, RETRIEVED_PROFILE_CHAR_LIMIT)
    return f"""
[PROFILE]
Name: {profile.get('name', '')} | Title: {profile.get('title', '')} | Location: {profile.get('location', '')}
Email: {profile.get('email', '')} | Phone: {profile.get('phone', '')} | Links: {", ".join(profile.get('links', []))}

Pitch:
{profile.get('pitch', '')}

Skills:
{bullet_list(profile.get('skills', []))}

Achievements:
{bullet_list(profile.get('achievements', []))}

[JOB_DESCRIPTION_RAW]
{jd_text_trimmed}

[RETRIEVED_JD_SNIPPETS]
{jd_snips_trimmed}

[RETRIEVED_PROFILE_SNIPPETS]
{prof_snips_trimmed}

[EXTRACTED_FROM_JD]
Hard skills: {", ".join(jd_hard)}
Soft skills: {", ".join(jd_soft)}
Extra keywords: {", ".join(keywords[:30])}

[ALIGNMENT_SUMMARY]
You already have (hard): {", ".join(have_hard)}
You already have (soft): {", ".join(have_soft)}
Gaps to phrase carefully: {", ".join(gaps)}
"""


def _profile_header(profile: Dict) -> str:
    return (
        f"Name: {profile.get('name', '')} | Title: {profile.get('title', '')} | Location: {profile.get('location', '')}\n"
        f"Email: {profile.get('email', '')} | Phone: {profile.get('phone', '')} | "
        f"Links: {', '.join(profile.get('links', []))}"
    )


def _profile_skills_block(profile: Dict) -> str:
    return (
        f"Skills:\n{bullet_list(profile.get('skills', []))}\n\n"
        f"Achievements:\n{bullet_list(profile.get('achievements', []))}"
    )


def build_task_context(
    task: TaskName,
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
    """Build a minimal user context string for a single generation task."""
    jd_text_trimmed = _trim(jd_text, JD_CHAR_LIMIT)
    jd_snips_trimmed = _trim(jd_snips, RETRIEVED_JD_CHAR_LIMIT)
    prof_snips_trimmed = _trim(prof_snips, RETRIEVED_PROFILE_CHAR_LIMIT)
    jd_for_email = _trim(jd_text, _EMAIL_JD_CHAR_LIMIT)
    extracted = (
        f"Hard skills: {', '.join(jd_hard)}\n"
        f"Soft skills: {', '.join(jd_soft)}\n"
        f"Extra keywords: {', '.join(keywords[:30])}"
    )
    alignment = (
        f"You already have (hard): {', '.join(have_hard)}\n"
        f"You already have (soft): {', '.join(have_soft)}\n"
        f"Gaps to phrase carefully: {', '.join(gaps)}"
    )

    if task == "skills":
        return f"""
[PROFILE_SKILLS]
{_profile_skills_block(profile)}

[RETRIEVED_JD_SNIPPETS]
{jd_snips_trimmed}

[EXTRACTED_FROM_JD]
{extracted}

[ALIGNMENT_SUMMARY]
{alignment}
"""

    if task == "cover":
        return f"""
[PROFILE]
{_profile_header(profile)}

Pitch:
{profile.get('pitch', '')}

Skills:
{bullet_list(profile.get('skills', []))}

Achievements:
{bullet_list(profile.get('achievements', []))}

[JOB_DESCRIPTION_RAW]
{jd_text_trimmed}

[RETRIEVED_JD_SNIPPETS]
{jd_snips_trimmed}

[RETRIEVED_PROFILE_SNIPPETS]
{prof_snips_trimmed}
"""

    if task == "emails":
        return f"""
[PROFILE]
{_profile_header(profile)}

[KEY_SELLING_POINTS]
Pitch:
{profile.get('pitch', '')}

Achievements:
{bullet_list(profile.get('achievements', []))}

[ROLE_AND_JD_CONTEXT]
Target title: {profile.get('title', '')}
{jd_for_email}

[RETRIEVED_JD_SNIPPETS]
{jd_snips_trimmed}

[RETRIEVED_PROFILE_SNIPPETS]
{prof_snips_trimmed}
"""

    # task == "ats"
    return f"""
[PROFILE_BULLETS]
{_profile_skills_block(profile)}

[EXTRACTED_FROM_JD]
{extracted}

[RETRIEVED_PROFILE_SNIPPETS]
{prof_snips_trimmed}
"""


__all__ = ["build_context", "build_task_context", "TaskName"]
