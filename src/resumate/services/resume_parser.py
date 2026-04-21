"""Resume text extraction + LLM-based structured field parsing."""

from __future__ import annotations

import io
import json
import logging

from resumate.models.llm import run_prompt
from resumate.prompts.templates import SYSTEM_RESUME_PARSE

logger = logging.getLogger("resumate")


def extract_text(file_bytes: bytes, filename: str) -> str:
    """Extract raw text from PDF, DOCX, or TXT file bytes."""
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""

    if ext == "pdf":
        return _extract_pdf(file_bytes)
    elif ext == "docx":
        return _extract_docx(file_bytes)
    elif ext in ("txt", "md"):
        return file_bytes.decode("utf-8", errors="replace")
    else:
        return file_bytes.decode("utf-8", errors="replace")


def _extract_pdf(data: bytes) -> str:
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(data))
    pages = []
    for page in reader.pages:
        text = page.extract_text()
        if text:
            pages.append(text)
    return "\n\n".join(pages)


def _extract_docx(data: bytes) -> str:
    from docx import Document

    doc = Document(io.BytesIO(data))
    return "\n".join(p.text for p in doc.paragraphs if p.text.strip())


def parse_resume_text(raw_text: str) -> dict:
    """Send resume text to Ollama for structured JSON extraction.

    Returns a dict with fields: name, title, location, email, phone,
    links, skills, achievements, pitch.
    """
    # Truncate very long resumes to keep prompt manageable
    truncated = raw_text[:8000] if len(raw_text) > 8000 else raw_text

    result = run_prompt(
        SYSTEM_RESUME_PARSE,
        truncated,
        max_tokens=1024,
        task_name="parse_resume",
        stage="tools",
    )

    # Try to extract JSON from the LLM response
    try:
        return json.loads(result)
    except json.JSONDecodeError:
        # Try to find JSON object in the response
        start = result.find("{")
        end = result.rfind("}") + 1
        if start >= 0 and end > start:
            try:
                return json.loads(result[start:end])
            except json.JSONDecodeError:
                pass
        logger.warning("parse_resume: LLM returned non-JSON: %s", result[:200])
        return {"raw_text": raw_text[:2000], "parse_error": "Could not parse LLM output as JSON"}
