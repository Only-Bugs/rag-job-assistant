"""
Construct the composite context block fed into generation prompts.
"""

from __future__ import annotations

from typing import Dict, List, Literal

from resumate.config.settings import JD_CHAR_LIMIT
from resumate.utils.text import bullet_list

TaskName = Literal["skills", "cover", "emails", "ats"]

# Shorter JD slice for email drafts (role + company cues) to avoid duplicating the full posting.
_EMAIL_JD_CHAR_LIMIT = 1500


def _trim(value: str, limit: int) -> str:
    if len(value) <= limit:
        return value
    return value[:limit] + "\n...[truncated for runtime]"


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


def jd_for_prompt(jd_text: str, jd_snips: str) -> str:
    """Fallback JD view when no sections are found: raw if it fits, else intro + retrieved chunks."""
    jd_text = jd_text.strip()
    if len(jd_text) <= JD_CHAR_LIMIT:
        return jd_text
    intro = jd_text[:_JD_INTRO_CHARS].rstrip()
    return (
        f"{intro}\n...\n\nKey requirements (retrieved):\n"
        f"{_trim(jd_snips, max(JD_CHAR_LIMIT - _JD_INTRO_CHARS, 400))}"
    )


def build_shared_context(profile: Dict, jd_prompt_text: str, evidence: List) -> str:
    """
    Deterministic context block shared by every generation task.

    Placed first in every request so all calls in a run start with the same
    tokens and Ollama only prefills it once. `evidence` is a list of
    EvidenceItem (services/evidence.py), each rendered with its [E#] ID,
    tools and metrics so outputs can be traced and checked.
    """
    skills = ", ".join(profile.get("skills", []))
    evidence_block = "\n".join(it.render() for it in evidence) or "none"
    return f"""
[CANDIDATE PROFILE]
{_profile_header(profile)}
Pitch: {profile.get('pitch', '')}
Skills: {skills}

[PROFILE EVIDENCE]
{evidence_block}

[JOB DESCRIPTION]
{jd_prompt_text}
"""


__all__ = ["build_shared_context", "jd_for_prompt", "TaskName"]
