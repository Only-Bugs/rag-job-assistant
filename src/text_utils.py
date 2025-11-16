"""
text_utils.py
Utility functions for text normalisation, tokenisation, and skill extraction.
"""

import re
from collections import Counter

# NLTK
import nltk
from nltk.corpus import stopwords
from nltk.tokenize import word_tokenize

# RapidFuzz
from rapidfuzz import process, fuzz


# ----------------------------------------------------------------------
# NLTK setup
# ----------------------------------------------------------------------
# We assume NLTK + data are already installed.
# If stopwords are missing, give a clear error.
try:
    STOPWORDS = set(stopwords.words("english"))
except LookupError:
    # You can either:
    # - run nltk.download("stopwords") once manually in a setup script/notebook
    # OR
    # - uncomment the lines below to auto-download (not recommended for pure library code)
    #
    # nltk.download("stopwords")
    # STOPWORDS = set(stopwords.words("english"))
    #
    raise RuntimeError(
        "NLTK stopwords not found. Run this once in a Python shell or notebook:\n"
        '    import nltk\n'
        '    nltk.download("punkt")\n'
        '    nltk.download("stopwords")\n'
    )


# ----------------------------------------------------------------------
# Basic text utilities
# ----------------------------------------------------------------------
def normalize_text(text: str) -> str:
    """
    Collapse whitespace and newlines into single spaces.
    """
    text = re.sub(r"[\r\n]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def tokenize_lower(text: str):
    """
    Lowercase tokens, strip punctuation at edges,
    drop stopwords and pure digits.
    """
    toks = [t.lower() for t in word_tokenize(text)]
    toks = [re.sub(r"^\W+|\W+$", "", t) for t in toks]
    return [t for t in toks if t and t not in STOPWORDS and not t.isdigit()]


# ----------------------------------------------------------------------
# Skill lexicons
# ----------------------------------------------------------------------
HARD_SKILL_LEXICON = {
    "Python","PyTorch","TensorFlow","NumPy","Pandas","scikit-learn","Jupyter",
    "Transformers","BERT","Llama","RAG","LangChain","Ollama","OpenAI","Hugging Face",
    "Vector DB","Chroma","FAISS","Pinecone","Weaviate","Milvus",
    "Docker","FastAPI","Flask","REST API","GraphQL",
    "MLflow","Weights & Biases","W&B","Ray","Dask",
    "LLM","Prompt Engineering","Reranking","Guardrails","Retrieval","Chunking",
    "CI/CD","GCP","AWS","Azure","Kubernetes","GPU","CUDA",
    "ROS2","Gazebo","PDDL","Fast Downward","PlanSys2","OpenCV",
}

SOFT_SKILL_LEXICON = {
    "Communication","Collaboration","Leadership","Problem solving","Stakeholder management",
    "Teamwork","Time management","Attention to detail","Documentation","Mentoring","Ownership",
}


# ----------------------------------------------------------------------
# Skill / term utilities
# ----------------------------------------------------------------------
def top_terms(tokens, topn: int = 30, min_len: int = 2):
    """
    Return the top-N most frequent tokens (length >= min_len).
    """
    c = Counter([t for t in tokens if len(t) >= min_len])
    return [w for w, _ in c.most_common(topn)]


def fuzzy_match_candidates(candidates, lexicon, cutoff: int = 86):
    """
    Fuzzy match candidate terms against a lexicon using RapidFuzz.

    Returns a sorted list of matched lexicon entries with score >= cutoff.
    """
    found = set()
    for cand in candidates:
        match, score, _ = process.extractOne(cand, lexicon, scorer=fuzz.WRatio)
        if score >= cutoff:
            found.add(match)
    return sorted(found)


def bullet_list(items):
    """
    Turn a list of strings into a simple bullet list.
    """
    return "\n".join([f"- {x}" for x in items])


def fuzzy_overlap(yours, theirs, cutoff: int = 88):
    """
    Fuzzy match elements of 'yours' against 'theirs' using RapidFuzz.

    Returns a list of (y, matched, score) triples.
    """
    matches = []
    for y in yours:
        m = process.extractOne(y, theirs, scorer=fuzz.WRatio)
        if m and m[1] >= cutoff:
            matches.append((y, m[0], m[1]))
    return matches
