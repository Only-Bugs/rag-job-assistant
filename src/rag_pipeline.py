"""
rag_pipeline.py
Core RAG logic for the Job Application Assistant.

This module:
- loads  profile documents
- builds / loads a Chroma vector store
- runs RAG using Ollama (Llama 3.2:3B or similar)
- builds rich context from JD + profile
- generates skills, cover letter, emails, ATS summary
"""

from __future__ import annotations

import os
import re
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any, List

import torch

import os
os.environ["ANONYMIZED_TELEMETRY"] = "false"
os.environ["CHROMA_TELEMETRY"] = "false"

# ----------------------------------------------------------------------
# Project config (public)
# ----------------------------------------------------------------------
from config import (
    PROFILE_DOC_DIR,
    RAG_DIR,
    CHROMA_DB_DIR,
    OUT_DIR,
    MODEL_NAME,
    EMBED_MODEL,
    CHUNK_SIZE,
    CHUNK_OVERLAP,
    TOP_K,
)

# Optional private profile config (NOT committed to GitHub)
try:
    from profile_config import USER_PROFILE
except ImportError:
    USER_PROFILE = None

# ----------------------------------------------------------------------
# LangChain / LLM stack
# ----------------------------------------------------------------------
from langchain_ollama import ChatOllama
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser
from langchain_community.embeddings import SentenceTransformerEmbeddings
from langchain_community.vectorstores import Chroma
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_community.document_loaders import PyPDFLoader, TextLoader

# ----------------------------------------------------------------------
# Text + skill utilities
# ----------------------------------------------------------------------
from text_utils import (
    normalize_text,
    tokenize_lower,
    top_terms,
    fuzzy_match_candidates,
    HARD_SKILL_LEXICON,
    SOFT_SKILL_LEXICON,
    bullet_list,
    fuzzy_overlap,
)

# ======================================================================
# Embeddings + splitter
# ======================================================================

device = "cuda" if torch.cuda.is_available() else "cpu"

# Make sure EMBED_MODEL in config.py is set to a sentence-transformer,
# e.g. "all-MiniLM-L6-v2"
emb = SentenceTransformerEmbeddings(
    model_name=EMBED_MODEL,
    model_kwargs={"device": device},
)

splitter = RecursiveCharacterTextSplitter(
    chunk_size=CHUNK_SIZE,
    chunk_overlap=CHUNK_OVERLAP,
    separators=["\n\n", "\n", " ", ""],
)

# ======================================================================
# Vector DB (Chroma)
# ======================================================================

# _vectordb: Optional[Chroma] = None


_vectordb = Chroma(
    embedding_function=emb,
    persist_directory=str(CHROMA_DB_DIR)
)

# _vectordb= Chroma(embedding_function=emb, persist_directory=str(CHROMA_DB_DIR))



def get_vectordb() -> Chroma:
    """
    Return a Chroma vectordb, creating it if needed.
    """
    global _vectordb
    if _vectordb is None:
        _vectordb = Chroma(
            embedding_function=emb,
            persist_directory=str(CHROMA_DB_DIR),
        )
    return _vectordb


# ======================================================================
# Document loading & indexing
# ======================================================================

def load_docs_from(folder: Path, doc_type: str):
    """
    Load PDFs / text / markdown files from a folder and tag them with metadata.
    """
    docs = []
    for p in sorted(folder.glob("*")):
        if p.suffix.lower() == ".pdf":
            docs += PyPDFLoader(str(p)).load()
        elif p.suffix.lower() in {".txt", ".md"}:
            docs += TextLoader(str(p), encoding="utf-8").load()

    for d in docs:
        d.metadata["source"] = d.metadata.get("source") or str(folder)
        d.metadata["doc_type"] = doc_type
        d.metadata["uid"] = str(uuid.uuid4())[:8]
    return docs


def index_profile_docs() -> int:
    """
    Index your long-term profile docs (CV, project summaries) into Chroma.
    """
    vectordb = get_vectordb()
    docs = load_docs_from(PROFILE_DOC_DIR, "profile")
    chunks = splitter.split_documents(docs)
    if chunks:
        vectordb.add_documents(chunks)
    return len(chunks)


def index_jd_text(jd_text: str) -> int:
    """
    Index the current job description as a temporary document.
    We write it as jd.txt under RAG_DIR.
    """
    tmp = RAG_DIR / "jd.txt"
    tmp.write_text(jd_text, encoding="utf-8")

    docs = load_docs_from(RAG_DIR, "jd")
    # only keep the jd.txt content to avoid re-adding profile docs
    docs = [d for d in docs if "jd.txt" in d.metadata.get("source", "")]
    chunks = splitter.split_documents(docs)

    vectordb = get_vectordb()
    if chunks:
        vectordb.add_documents(chunks)
    return len(chunks)


# ======================================================================
# Retrieval helpers
# ======================================================================

def retrieve(query: str, k: int = 6, doc_type: Optional[str] = None):
    """
    Retrieve top-k documents for a query, optionally filtered by doc_type.
    """
    vectordb = get_vectordb()
    docs = vectordb.similarity_search(query, k=24)
    if doc_type:
        docs = [d for d in docs if d.metadata.get("doc_type") == doc_type]
    return docs[:k]


def format_docs(docs) -> str:
    """
    Nicely numbered snippet list for prompt context.
    """
    return "\n\n".join(f"[{i+1}] {d.page_content}" for i, d in enumerate(docs, 1))


def cite_sources(docs) -> str:
    """
    Produce a simple source list for debugging or display.
    """
    lines = []
    for i, d in enumerate(docs, 1):
        lines.append(f"[{i}] {d.metadata.get('source', '')}")
    return "\n".join(lines)


# ======================================================================
# LLM + low-level prompt runner
# ======================================================================

OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434")
LLM_MODEL = os.getenv("LLM_MODEL", MODEL_NAME)

llm = ChatOllama(
    base_url=OLLAMA_HOST,
    model=LLM_MODEL,
    temperature=0.3,
)
parser = StrOutputParser()


def run_prompt(system_prompt: str, user_text: str) -> str:
    """
    Low-level helper: build a chat prompt and run it through the LLM.
    """
    prompt = ChatPromptTemplate.from_messages(
        [
            ("system", system_prompt),
            ("user", "{input}"),
        ]
    )
    chain = prompt | llm | parser
    return chain.invoke({"input": user_text})


# ======================================================================
# Simple RAG answer (optional helper)
# ======================================================================

def _build_system_prompt_basic() -> str:
    """
    Basic system prompt for a generic job-assistant RAG call.
    Uses USER_PROFILE if available.
    """
    base = (
        "You are a helpful AI/ML job application assistant. "
        "You generate CV bullet points, cover letters, and email drafts "
        "tailored for AI/ML engineer roles.\n\n"
    )

    if USER_PROFILE is None:
        return base

    skills = ", ".join(USER_PROFILE.get("skills", []))
    pitch = USER_PROFILE.get("pitch", "")

    return (
        base
        + f"My name is {USER_PROFILE.get('name', '')}. "
          f"My title is {USER_PROFILE.get('title', '')}. "
          f"I am based in {USER_PROFILE.get('location', '')}.\n"
        f"My skills include: {skills}.\n"
        f"My personal pitch: {pitch}\n\n"
        "Use this information to personalise the output."
    )


def generate_answer(query: str, k: int = TOP_K) -> str:
    """
    Simple RAG function:
    - retrieves relevant profile chunks
    - builds a prompt with context + user profile
    - calls the LLM
    """
    vectordb = get_vectordb()
    retriever = vectordb.as_retriever(search_kwargs={"k": k})

    docs = retriever.get_relevant_documents(query)
    context = "\n\n".join(d.page_content for d in docs)

    system_prompt = _build_system_prompt_basic()

    prompt_text = f"""{system_prompt}

Context from my documents:
{context}

User request:
{query}

Write a clear, professional answer tailored for AI/ML job applications.
Avoid hallucinating technologies I don't know unless the user explicitly asks to learn them.
"""

    return run_prompt("You are a helpful assistant.", prompt_text)


# ======================================================================
# Context building for job applications
# ======================================================================

def build_context(
    profile: dict,
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
    """
    Build a rich context block combining:
    - profile info
    - raw JD
    - retrieved snippets
    - extracted skills / keywords
    - alignment summary
    """
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


# ======================================================================
# System prompts for different generators
# ======================================================================

SYSTEM_SKILLS = """
You are a job-application copilot. From the context:
1) HARD skills explicitly relevant to the JD and present in candidate/profile.
2) SOFT skills tailored to the JD.
3) 15–25 SEO keywords for CV/ATS.
Rules:
- Ground items in [RETRIEVED_*] where possible. No fabrications.
- Use canonical names. Output as three sections with bullet lists.
"""

SYSTEM_COVER = """
You are an expert cover-letter writer. Using the context:
- Ground claims in [RETRIEVED_JD_SNIPPETS] and [RETRIEVED_PROFILE_SNIPPETS].
- <=350 words, 3–5 short paragraphs + a 'Relevant Highlights' bullet list (3–5).
- Quote exact JD terms where helpful. No invented experience.
- Confident and specific; clear call-to-action.
"""

SYSTEM_EMAILS = """
Write three short emails tailored to the JD and candidate:
1) Application email (80–140 words) + 2–3 subject options.
2) Cold recruiter outreach (40–80 words) + 2–3 subject options.
3) Follow-up after 7–10 days (50–90 words) + 2–3 subject options.
Ground skills in [RETRIEVED_*]. No exaggeration. Clean signature from [PROFILE].
Format:
=== Email 1 ===
Subject: ...
Body:
...
=== Email 2 ===
...
=== Email 3 ===
...
"""

SYSTEM_ATS = """
Create a compact ATS-friendly resume summary:
- 3 bullets (outcomes-focused) aligned to JD.
- One 'Core Stack' line (comma-separated tools).
Keep to 80–120 words. Ground in [RETRIEVED_*]; no fabrications.
"""


# ======================================================================
# High-level generation helpers
# ======================================================================

def gen_skills(context: str) -> str:
    return run_prompt(SYSTEM_SKILLS, context)


def gen_cover(context: str) -> str:
    return run_prompt(SYSTEM_COVER, context)


def gen_emails(context: str) -> str:
    return run_prompt(SYSTEM_EMAILS, context)


def gen_ats(context: str) -> str:
    return run_prompt(SYSTEM_ATS, context)


# ======================================================================
# Full pipeline for a single JD
# ======================================================================

def generate_all_from_jd(jd_text: str, save_to_disk: bool = False) -> Dict[str, Any]:
    """
    Full pipeline for a single job description.

    Steps:
    - index profile docs (once) and this JD
    - retrieve focused snippets
    - extract hard/soft skills + keywords
    - compute alignment (have hard/soft, gaps)
    - build context and generate: skills, cover letter, emails, ATS summary

    Returns a dict with all outputs and intermediate info.
    Optionally saves markdown files to OUT_DIR.
    """

    if USER_PROFILE is None:
        raise RuntimeError(
            "USER_PROFILE is not set. Fill in profile_config.py locally."
        )

    # 1) index JD + profile docs
    index_profile_docs()
    index_jd_text(jd_text)

    # 2) retrieve focused snippets
    jd_focus = retrieve(
        "List must-have requirements and responsibilities.",
        k=6,
        doc_type="jd",
    )
    profile_focus = retrieve(
        "Find bullets that prove impact, results, metrics.",
        k=6,
        doc_type="profile",
    )
    rag_jd = format_docs(jd_focus)
    rag_profile = format_docs(profile_focus)

    # 3) keyword / skill extraction from JD
    jd_norm = normalize_text(jd_text)
    toks = tokenize_lower(jd_norm)
    cands = top_terms(toks, topn=80, min_len=2)

    jd_hard = fuzzy_match_candidates(cands, HARD_SKILL_LEXICON, cutoff=86)
    jd_soft = fuzzy_match_candidates(cands, SOFT_SKILL_LEXICON, cutoff=86)

    # extra capitalised tokens (e.g. AWS, ROS2)
    caps = sorted(
        set(re.findall(r"\b([A-Z][a-zA-Z0-9\-\+&/]{1,})\b", jd_text))
    )
    hard_lower_map = {s.lower(): s for s in HARD_SKILL_LEXICON}
    extra = fuzzy_match_candidates(
        [c.lower() for c in caps],
        hard_lower_map.keys(),
        cutoff=90,
    )
    extra_cased = [hard_lower_map.get(e, e) for e in extra]

    # jd_hard = sorted(set(jd_hard) | set(extra_cased))

    jd_hard = sorted({s for s in (set(jd_hard) | set(extra_cased)) if s})

    known = {t.lower() for t in jd_hard + jd_soft}
    keywords = [t for t in cands if t not in known and len(t) >= 3]

    # 4) alignment summary vs your profile skills
    have_hard = sorted(
        {m[1] for m in fuzzy_overlap(USER_PROFILE["skills"], jd_hard, cutoff=88)}
    )
    have_soft = sorted(
        {m[1] for m in fuzzy_overlap(USER_PROFILE["skills"], jd_soft, cutoff=88)}
    )
    gaps = [
        s
        for s in jd_hard + jd_soft
        if s not in set(have_hard + have_soft)
    ]

    # 5) build full context and generate all outputs
    ctx = build_context(
        USER_PROFILE,
        jd_text,
        rag_jd,
        rag_profile,
        jd_hard,
        jd_soft,
        keywords,
        have_hard,
        have_soft,
        gaps,
    )

    skills_out = gen_skills(ctx)
    cover_out = gen_cover(ctx)
    emails_out = gen_emails(ctx)
    ats_out = gen_ats(ctx)

    if save_to_disk:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        (OUT_DIR / f"{ts}_skills_keywords.md").write_text(
            skills_out, encoding="utf-8"
        )
        (OUT_DIR / f"{ts}_cover_letter.md").write_text(
            cover_out, encoding="utf-8"
        )
        (OUT_DIR / f"{ts}_emails.md").write_text(
            emails_out, encoding="utf-8"
        )
        (OUT_DIR / f"{ts}_ats_summary.md").write_text(
            ats_out, encoding="utf-8"
        )

    return {
        "context": ctx,
        "skills": skills_out,
        "cover": cover_out,
        "emails": emails_out,
        "ats": ats_out,
        "jd_hard": jd_hard,
        "jd_soft": jd_soft,
        "keywords": keywords,
        "have_hard": have_hard,
        "have_soft": have_soft,
        "gaps": gaps,
    }

# Prevent ANY accidental code from running during import
if __name__ != "__main__":
    pass



