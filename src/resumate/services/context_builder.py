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


# Leading slice of the raw JD kept when the posting is too long to send whole —
# usually carries the role title, company and team intro.
_JD_INTRO_CHARS = 600


def _jd_for_prompt(jd_text: str, jd_snips: str) -> str:
    """One JD representation: the raw posting if it fits, else intro + retrieved requirements."""
    jd_text = jd_text.strip()
    if len(jd_text) <= JD_CHAR_LIMIT:
        return jd_text
    intro = jd_text[:_JD_INTRO_CHARS].rstrip()
    return (
        f"{intro}\n...\n\nKey requirements (retrieved):\n"
        f"{_trim(jd_snips, max(JD_CHAR_LIMIT - _JD_INTRO_CHARS, 400))}"
    )


def build_shared_context(
    profile: Dict,
    jd_text: str,
    jd_snips: str,
    prof_snips: str,
) -> str:
    """
    Deterministic context block shared by every generation task.

    It is appended to SHARED_SYSTEM as the system turn, so all four requests in a
    run start with the same tokens and Ollama only prefills it once.
    """
    skills = ", ".join(profile.get("skills", []))
    return f"""
[CANDIDATE PROFILE]
{_profile_header(profile)}
Pitch: {profile.get('pitch', '')}
Skills: {skills}
Achievements:
{bullet_list(profile.get('achievements', []))}

[PROFILE EVIDENCE]
{_trim(prof_snips, RETRIEVED_PROFILE_CHAR_LIMIT)}

[JOB DESCRIPTION]
{_jd_for_prompt(jd_text, jd_snips)}
"""


def build_task_tail(
    task: TaskName,
    instructions: str,
    jd_hard: List[str],
    jd_soft: List[str],
    keywords: List[str],
    have_hard: List[str],
    have_soft: List[str],
    gaps: List[str],
) -> str:
    """Build the per-task user turn: small task-only data followed by the instructions."""
    extracted = (
        f"JD hard skills: {', '.join(jd_hard)}\n"
        f"JD soft skills: {', '.join(jd_soft)}\n"
        f"Other JD keywords: {', '.join(keywords[:20])}"
    )
    if task == "skills":
        data = (
            f"[KEYWORD SIGNALS]\n{extracted}\n"
            f"Candidate already has: {', '.join(have_hard + have_soft)}\n"
            f"Gaps: {', '.join(gaps)}\n\n"
        )
    elif task == "ats":
        data = f"[KEYWORD SIGNALS]\n{extracted}\n\n"
    else:
        data = ""
    return data + instructions


__all__ = ["build_context", "build_shared_context", "build_task_tail", "TaskName"]
