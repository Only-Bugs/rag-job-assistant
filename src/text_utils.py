"""
text_utils.py
Utility functions for text normalisation, tokenisation, and skill extraction.
"""

import re
from collections import Counter
from rapidfuzz import process, fuzz

# ----------------------------------------------------------------------
# STOPWORDS — Static list (no NLTK needed)
# ----------------------------------------------------------------------
STATIC_STOPWORDS = {
    "a","an","the","and","or","but","if","while","is","are","was","were","be","been",
    "being","to","of","in","on","for","with","as","by","that","this","it","its","at",
    "from","into","about","up","down","over","under","again","further","then","once",
    "here","there","all","any","both","each","few","more","most","other","some","such",
    "no","nor","not","only","own","same","so","than","too","very",
}

STOPWORDS = STATIC_STOPWORDS

# ----------------------------------------------------------------------
# Basic text utilities
# ----------------------------------------------------------------------
def normalize_text(text: str) -> str:
    """Collapse whitespace."""
    text = re.sub(r"[\r\n]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def simple_tokenize(text: str):
    """Simple, dependency-free tokenizer."""
    return re.findall(r"[A-Za-z0-9\-\+&/]+", text)


def tokenize_lower(text: str):
    """
    Lowercase tokens, strip punctuation, drop stopwords/digits.
    Replacement for NLTK word_tokenize().
    """
    toks = [t.lower() for t in simple_tokenize(text)]
    return [
        t for t in toks
        if t not in STOPWORDS and not t.isdigit() and len(t) > 0
    ]


# ----------------------------------------------------------------------
# Skill lexicons
# ----------------------------------------------------------------------
HARD_SKILL_LEXICON = {
    "Python","PyTorch","TensorFlow","NumPy","Pandas","scikit-learn","Jupyter",
    "Transformers","BERT","Llama","RAG","LangChain","Ollama","OpenAI",
    "Hugging Face","Vector DB","Chroma","FAISS","Pinecone","Weaviate","Milvus",
    "Docker","FastAPI","Flask","REST API","GraphQL","MLflow","Weights & Biases",
    "W&B","Ray","Dask","LLM","Prompt Engineering","Reranking","Guardrails",
    "Retrieval","Chunking","CI/CD","GCP","AWS","Azure","Kubernetes","GPU",
    "CUDA","ROS2","Gazebo","PDDL","Fast Downward","PlanSys2","OpenCV",
}

SOFT_SKILL_LEXICON = {
    "Communication","Collaboration","Leadership","Problem solving",
    "Stakeholder management","Teamwork","Time management",
    "Attention to detail","Documentation","Mentoring","Ownership",
}

# ----------------------------------------------------------------------
# Skill utilities
# ----------------------------------------------------------------------
def top_terms(tokens, topn: int = 30, min_len: int = 2):
    c = Counter([t for t in tokens if len(t) >= min_len])
    return [w for w, _ in c.most_common(topn)]


def fuzzy_match_candidates(candidates, lexicon, cutoff: int = 86):
    found = set()
    for cand in candidates:
        match, score, _ = process.extractOne(cand, lexicon, scorer=fuzz.WRatio)
        if score >= cutoff:
            found.add(match)
    return sorted(found)


def bullet_list(items):
    return "\n".join(f"- {x}" for x in items)


def fuzzy_overlap(yours, theirs, cutoff: int = 88):
    matches = []
    for y in yours:
        m = process.extractOne(y, theirs, scorer=fuzz.WRatio)
        if m and m[1] >= cutoff:
            matches.append((y, m[0], m[1]))
    return matches
