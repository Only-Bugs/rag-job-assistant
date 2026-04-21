"""
settings.py
Loads configuration for ResuMate from YAML files.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict

import yaml
from dotenv import load_dotenv

from resumate.utils.helpers import ensure_dir


def _load_yaml(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    with path.open(encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


# ----------------------------------------------------------------------
# PROJECT ROOT
# ----------------------------------------------------------------------
# This file lives in project_root/src/resumate/config/settings.py
# So ROOT = project_root
ROOT = Path(__file__).resolve().parents[3]
ENV_PATH = ROOT / ".env"
load_dotenv(dotenv_path=ENV_PATH, override=False)
CONFIG_DIR = Path(__file__).resolve().parent

SETTINGS_FILE = CONFIG_DIR / "settings.yaml"
MODEL_CONFIG_FILE = CONFIG_DIR / "model_config.yaml"

SETTINGS_DATA = _load_yaml(SETTINGS_FILE)
MODEL_DATA = _load_yaml(MODEL_CONFIG_FILE)

# ----------------------------------------------------------------------
# DATA DIRECTORIES
# ----------------------------------------------------------------------
data_cfg = SETTINGS_DATA.get("data", {})

DATA_DIR = ROOT / data_cfg.get("base_dir", "data")
ensure_dir(DATA_DIR)

OUT_DIR = DATA_DIR / data_cfg.get("outputs_dir", "outputs")
ensure_dir(OUT_DIR)

RAG_DIR = DATA_DIR / data_cfg.get("rag_dir", "job_rag")
ensure_dir(RAG_DIR)

PROFILE_DOC_DIR = RAG_DIR / data_cfg.get("profile_subdir", "profile_docs")
ensure_dir(PROFILE_DOC_DIR)

CHROMA_DB_DIR = RAG_DIR / data_cfg.get("chroma_dir", "chroma_db")
ensure_dir(CHROMA_DB_DIR)

# ----------------------------------------------------------------------
# PER-USER DATA DIRECTORIES  (multi-user support)
# ----------------------------------------------------------------------
DATA_USERS_DIR = DATA_DIR / "users"
ensure_dir(DATA_USERS_DIR)

DEV_USER_ID = "dev_user"


def get_user_data_dir(user_id: str = DEV_USER_ID) -> Path:
    """Return (and create) the per-user data directory tree.

    Structure:
        data/users/{user_id}/
            profile_docs/   -- uploaded resume files
            chroma_db/      -- user-scoped vector store
            profile_settings.json  -- written on first profile save
    """
    d = DATA_USERS_DIR / user_id
    ensure_dir(d / "profile_docs")
    ensure_dir(d / "chroma_db")
    return d


# ----------------------------------------------------------------------
# RAG SETTINGS
# ----------------------------------------------------------------------
rag_cfg = SETTINGS_DATA.get("rag", {})
CHUNK_SIZE = rag_cfg.get("chunk_size", 800)
CHUNK_OVERLAP = rag_cfg.get("chunk_overlap", 200)
TOP_K = rag_cfg.get("top_k", 5)

# ----------------------------------------------------------------------
# MODEL SETTINGS
# ----------------------------------------------------------------------
embedding_cfg = MODEL_DATA.get("embeddings", {})
EMBED_MODEL = embedding_cfg.get("model_name", "all-MiniLM-L6-v2")

llm_cfg = MODEL_DATA.get("llm", {})
MODEL_NAME = llm_cfg.get("model_name", "llama3.2:3b")
OLLAMA_HOST_DEFAULT = llm_cfg.get("host", "http://localhost:11434")
OLLAMA_HOST = os.getenv("OLLAMA_HOST", OLLAMA_HOST_DEFAULT)
LLM_TEMPERATURE = float(llm_cfg.get("temperature", 0.2))
LLM_PARALLEL_WORKERS = int(llm_cfg.get("parallel_workers", 4))
LLM_MAX_TOKENS = llm_cfg.get(
    "max_tokens",
    {"skills": 450, "cover": 650, "emails": 700, "ats": 280, "default": 512},
)

runtime_cfg = MODEL_DATA.get("runtime", {})
context_limits_cfg = runtime_cfg.get("context_limits", {})
JD_CHAR_LIMIT = int(context_limits_cfg.get("jd_chars", 3500))
RETRIEVED_JD_CHAR_LIMIT = int(context_limits_cfg.get("retrieved_jd_chars", 2200))
RETRIEVED_PROFILE_CHAR_LIMIT = int(context_limits_cfg.get("retrieved_profile_chars", 2200))


__all__ = [
    "ROOT",
    "DATA_DIR",
    "OUT_DIR",
    "RAG_DIR",
    "PROFILE_DOC_DIR",
    "CHROMA_DB_DIR",
    "DATA_USERS_DIR",
    "DEV_USER_ID",
    "get_user_data_dir",
    "CHUNK_SIZE",
    "CHUNK_OVERLAP",
    "TOP_K",
    "EMBED_MODEL",
    "MODEL_NAME",
    "OLLAMA_HOST_DEFAULT",
    "OLLAMA_HOST",
    "LLM_TEMPERATURE",
    "LLM_PARALLEL_WORKERS",
    "LLM_MAX_TOKENS",
    "JD_CHAR_LIMIT",
    "RETRIEVED_JD_CHAR_LIMIT",
    "RETRIEVED_PROFILE_CHAR_LIMIT",
]
