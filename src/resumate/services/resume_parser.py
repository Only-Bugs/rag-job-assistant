"""Resume text extraction + LLM-based structured field parsing."""

from __future__ import annotations

import io
import logging
import re

from resumate.config.settings import task_options
from resumate.models.llm import chat_json
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


# JSON schema for Ollama structured outputs: every field optional, so the model
# can omit what the resume doesn't contain instead of inventing it.
RESUME_SCHEMA = {
    "type": "object",
    "properties": {
        "name": {"type": "string"},
        "title": {"type": "string"},
        "location": {"type": "string"},
        "email": {"type": "string"},
        "phone": {"type": "string"},
        "links": {"type": "array", "items": {"type": "string"}},
        "skills": {"type": "array", "items": {"type": "string"}},
        "achievements": {"type": "array", "items": {"type": "string"}},
        "pitch": {"type": "string"},
    },
}
_MAX_RESUME_CHARS = 8000  # ~2.2k tokens; fits num_ctx 4096 with the schema output


def _verify_against_source(parsed: dict, source: str) -> dict:
    """Drop extracted values that don't appear in the resume (small models embellish)."""
    from rapidfuzz import fuzz

    low = source.lower()
    squashed = re.sub(r"\s+", "", low)
    out: dict = {}
    for key, val in parsed.items():
        if key not in RESUME_SCHEMA["properties"] or val in (None, "", []):
            continue
        if key in ("name", "email", "phone", "location", "title"):
            v = str(val).strip()
            if re.sub(r"\s+", "", v.lower()) in squashed:
                out[key] = v
        elif key in ("skills", "links"):
            out[key] = [v.strip() for v in val if isinstance(v, str) and v.strip().lower() in low]
        elif key == "achievements":
            out[key] = [v.strip() for v in val if isinstance(v, str)
                        and fuzz.partial_ratio(v.lower(), low) >= 80]
        else:  # pitch is a summary: keep as written
            out[key] = val
    return out


def parse_resume_text(raw_text: str) -> dict:
    """Extract structured profile fields from resume text.

    Uses Ollama structured outputs (JSON schema, temperature 0), then keeps only
    values that can be found in the source text. Returns a dict with any of:
    name, title, location, email, phone, links, skills, achievements, pitch.
    """
    truncated = raw_text[:_MAX_RESUME_CHARS]
    messages = [{"role": "user", "content": SYSTEM_RESUME_PARSE + "\n\nRESUME:\n" + truncated}]
    try:
        parsed = chat_json(messages, RESUME_SCHEMA, options=task_options("resume_parse"),
                           task_name="parse_resume")
    except Exception as exc:
        logger.warning("parse_resume: structured call failed: %s", exc)
        return {"raw_text": raw_text[:2000], "parse_error": "Could not parse the resume with the local model"}
    return _verify_against_source(parsed if isinstance(parsed, dict) else {}, raw_text)
