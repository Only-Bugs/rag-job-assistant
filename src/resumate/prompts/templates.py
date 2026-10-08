"""
templates.py
Prompts for the ResuMate Job Application Assistant.

Design:
- Every generation call is one user turn: SHARED_SYSTEM + shared context
  (byte-identical across calls, so Ollama reuses its KV cache) followed by one
  small task block built here.
- Each task block asks for ONE thing with ONE output shape. Decisions (which
  evidence, which requirement, match band, keywords, gap, sign-offs) are made
  in code (services/analysis.py) and passed in as facts.
- Length is stated in sentences/lines, not words. Format is enforced with
  prefill + stop sequences + post-processing rather than lists of rules.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Shared prefix — byte-identical for every call in a run.
# Keep task-specific wording OUT of this string: any difference breaks
# Ollama's prompt-prefix cache and every call re-prefills the full context.
# ---------------------------------------------------------------------------
SHARED_SYSTEM = """You are ResuMate, an expert career writer who produces concise, business-ready job application material.
Ground every claim in the CANDIDATE PROFILE, PROFILE EVIDENCE and JOB DESCRIPTION below. Evidence items are labelled [E#].
Never invent employers, projects, tools, dates or numbers.
Follow the TASK at the end exactly. No preamble."""

# Phrases the model uses to sign off; used as stop sequences so code can
# append a consistent sign-off instead.
SIGN_OFF_STOPS = ["Sincerely", "Best regards", "Kind regards", "Warm regards", "Regards,", "Thank you,\n", "Best,\n"]


def _evidence_ref(item) -> str:
    return f"[{item.id}] ({item.label})"


# ---------------------------------------------------------------------------
# Cover letter — 1 call, prefilled with the greeting, stopped at the sign-off.
# ---------------------------------------------------------------------------
def cover_task(role: str, company: str, jd_term: str, items: list) -> str:
    at = f" at {company}" if company else ""
    proof = " and ".join(_evidence_ref(it) for it in items) or "the strongest PROFILE EVIDENCE"
    return f"""TASK: Write the body of a cover letter from the candidate for the {role} role{at}.
Write exactly 3 short paragraphs of 2-3 sentences each, in the first person:
1. Why this role{at} appeals, using the exact phrase "{jd_term}".
2. What the candidate achieved in {proof}, including their real results.
3. A confident closing that asks for a conversation.
Plain sentences only. Stop after the third paragraph."""


# ---------------------------------------------------------------------------
# Emails — 3 calls, each prefilled with "Subject: ".
# ---------------------------------------------------------------------------
EMAIL_KINDS = {
    1: ("Application", "an application email to the hiring manager",
        "3-4 sentences: say you are applying, give one result from {ref}, say why you fit, and mention your resume is attached."),
    2: ("Cold Outreach", "a short cold email to a recruiter",
        "2-3 sentences: who you are, one result from {ref}, and ask for a 15-minute call."),
    3: ("Follow-up", "a polite follow-up email sent 7-10 days after applying",
        "2-3 sentences: check in on your application, restate one fit point from {ref}, and thank them."),
}


def email_task(kind: int, role: str, company: str, item) -> str:
    _, what, shape = EMAIL_KINDS[kind]
    at = f" at {company}" if company else ""
    ref = _evidence_ref(item) if item is not None else "the PROFILE EVIDENCE"
    return f"""TASK: Write {what} about the {role} role{at}.
First line: a specific subject line. Then a blank line. Then the email body: {shape.format(ref=ref)}
Write as the candidate, in plain sentences. Do not add a sign-off."""


# ---------------------------------------------------------------------------
# Skills — code writes headings + keyword lists; the model writes 1 snapshot
# sentence, 1 line per bullet, and 1-2 gap sentences.
# ---------------------------------------------------------------------------
def snapshot_task(band: str, role: str, strengths: list[str]) -> str:
    return (f'TASK: Write one sentence to the candidate (use "you") saying they are a {band.lower()} match '
            f'for the {role} role, naming these strengths: {", ".join(strengths) or "their most relevant experience"}.')


def bullet_task(item, requirement: str | None) -> str:
    aim = (f'aimed at this job requirement: "{requirement}"' if requirement
           else "that best shows transferable impact for this role")
    return f"""TASK: Rewrite evidence {_evidence_ref(item)} as one resume bullet {aim}.
Shape: past-tense action verb + what was built or done + tools used + the result.
Use only facts and tools that [{item.id}] itself mentions. One line, no pronouns, no quotation marks.
Shape example from a different field: Reduced warehouse picking errors by redesigning bin labels with Excel, cutting returns by a third."""


def retry_suffix(previous: str, problems: list[str]) -> str:
    return f"""
Your previous answer was: {previous}
Problems: {"; ".join(problems)}.
Write it again, fixing these problems."""


def gap_task(gap: str, gap_terms: list[str], related: list[str]) -> str:
    near = f" They already have: {', '.join(related)}." if related else ""
    if gap_terms:
        what = f'no evidence of {", ".join(gap_terms)}, which the job asks for in: "{gap}"'
    else:
        what = f'the weakest-covered requirement: "{gap}"'
    return f"""TASK: The candidate's biggest gap for this role is {what}.{near}
In 1-2 sentences to the candidate (use "you"), suggest one concrete, realistic way to close that specific gap before applying."""


# ---------------------------------------------------------------------------
# ATS summary — code writes the Core Stack line; the model continues a
# prefilled "<title> with" summary and writes one outcome line per item.
# ---------------------------------------------------------------------------
def ats_summary_task(role: str, strengths: list[str]) -> str:
    return (f'TASK: Continue this 2-sentence resume summary for the {role} role in resume voice '
            f'(no "I", no name), mentioning {", ".join(strengths) or "the candidate core skills"}. '
            f'Plain text, stop after two sentences.')


def ats_outcome_task(item) -> str:
    return f"""TASK: Write one resume outcome line from evidence {_evidence_ref(item)}.
A past-tense verb, then what was done and the result. One line, only facts from [{item.id}], no pronouns."""


# ---------------------------------------------------------------------------
# Resume parse (tools route) — sent through Ollama structured outputs with a
# JSON schema (services/resume_parser.RESUME_SCHEMA), so no inline JSON example.
# ---------------------------------------------------------------------------
SYSTEM_RESUME_PARSE = """TASK: Extract the candidate's details from the resume below.
- name, title (current or most recent job title), location, email, phone: copy exactly as written.
- links: URLs or profile handles as written.
- skills: individual tools and technologies listed in the resume.
- achievements: up to 6 of the strongest accomplishment bullets, copied word for word.
- pitch: a 2-sentence professional summary based only on the resume.
Leave out any field the resume does not contain."""


__all__ = [
    "SHARED_SYSTEM",
    "SIGN_OFF_STOPS",
    "EMAIL_KINDS",
    "cover_task",
    "email_task",
    "snapshot_task",
    "bullet_task",
    "retry_suffix",
    "gap_task",
    "ats_summary_task",
    "ats_outcome_task",
    "SYSTEM_RESUME_PARSE",
]
