"""
config.py
Public configuration for the RAG job assistant.
Safe to push to GitHub.
"""

from pathlib import Path

# ----------------------------------------------------------------------
# PROJECT ROOT
# ----------------------------------------------------------------------
# This file lives in: project_root/src/config.py
# So ROOT = project_root
ROOT = Path(__file__).resolve().parents[1]

# ----------------------------------------------------------------------
# DATA DIRECTORIES
# ----------------------------------------------------------------------
DATA_DIR = ROOT / "data"
DATA_DIR.mkdir(exist_ok=True)

OUT_DIR = DATA_DIR / "outputs"
OUT_DIR.mkdir(parents=True, exist_ok=True)

RAG_DIR = DATA_DIR / "job_rag"
RAG_DIR.mkdir(parents=True, exist_ok=True)

PROFILE_DOC_DIR = RAG_DIR / "profile_docs"
PROFILE_DOC_DIR.mkdir(parents=True, exist_ok=True)

# where Chroma DB will be persisted
CHROMA_DB_DIR = RAG_DIR / "chroma_db"
CHROMA_DB_DIR.mkdir(parents=True, exist_ok=True)

# ----------------------------------------------------------------------
# MODEL SETTINGS
# ----------------------------------------------------------------------
MODEL_NAME = "llama3.2:3b"     # ollama model
EMBED_MODEL = "all-MiniLM-L6-v2"     # embedding model

# ----------------------------------------------------------------------
# RAG SETTINGS
# ----------------------------------------------------------------------
CHUNK_SIZE = 800
CHUNK_OVERLAP = 200
TOP_K = 5  # number of retrieved documents

