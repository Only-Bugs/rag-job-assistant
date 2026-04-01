"""RJA FastAPI application — Phase 1 backend.

Run from the project root:
    uvicorn src.api.main:app --reload --port 8000

The src/ directory is added to sys.path at import time so that all
``rag.*`` imports resolve the same way they do in src/ui/app.py.
"""

from __future__ import annotations

import logging
import sys
from contextlib import asynccontextmanager
from pathlib import Path

import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

# ---------------------------------------------------------------------------
# File-based log handler — routes rag/api Python logger output to logs/app.log
# so it stays out of uvicorn's captured stdout.
# ---------------------------------------------------------------------------
_LOG_DIR = Path(__file__).resolve().parents[2] / "logs"
_LOG_DIR.mkdir(parents=True, exist_ok=True)
_app_log_handler = logging.FileHandler(_LOG_DIR / "app.log", encoding="utf-8")
_app_log_handler.setFormatter(
    logging.Formatter("%(asctime)s  %(levelname)-8s  %(name)s  %(message)s")
)
for _name in ("rag", "api", "httpx"):
    _lg = logging.getLogger(_name)
    _lg.addHandler(_app_log_handler)
    _lg.propagate = False  # don't bubble up to root → stdout

# ---------------------------------------------------------------------------
# Path bootstrap — mirror src/ui/app.py so rag.* imports resolve correctly
# ---------------------------------------------------------------------------
_SRC_DIR = Path(__file__).resolve().parents[1]   # src/api/main.py → src/
if str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))

# ---------------------------------------------------------------------------
# Project imports (after sys.path is set)
# ---------------------------------------------------------------------------
from rag.config.settings import MODEL_NAME  # noqa: E402

from api.auth import router as auth_router  # noqa: E402
from api.routes.export import router as export_router  # noqa: E402
from api.routes.generate import router as generate_router  # noqa: E402
from api.routes.health import router as health_router  # noqa: E402
from api.routes.profile import router as profile_router  # noqa: E402
from api.routes.upload import router as upload_router  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(name)s  %(message)s")
logger = logging.getLogger("api")


# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------
async def _migrate_dev_user() -> None:
    """One-time migration: copy legacy data/job_rag/ files into data/users/dev_user/.

    Safe to run on every startup — skips files that already exist.
    Never deletes or modifies the legacy source directory.
    """
    import shutil
    from rag.config.settings import DEV_USER_ID, PROFILE_DOC_DIR, RAG_DIR, get_user_data_dir

    user_dir = get_user_data_dir(DEV_USER_ID)

    # profile_settings.json
    src_json = RAG_DIR / "profile_settings.json"
    dst_json = user_dir / "profile_settings.json"
    if src_json.exists() and not dst_json.exists():
        shutil.copy2(src_json, dst_json)
        logger.info("migration: profile_settings.json → %s", dst_json)

    # profile_docs — read-only source, copy individual files
    if PROFILE_DOC_DIR.exists():
        for f in PROFILE_DOC_DIR.iterdir():
            if f.is_file() and f.suffix.lower() in {".pdf", ".txt", ".md"}:
                dest = user_dir / "profile_docs" / f.name
                if not dest.exists():
                    shutil.copy2(f, dest)
                    logger.info("migration: %s → %s", f.name, dest)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await _migrate_dev_user()
    logger.info("RJA API ready  |  model=%s", MODEL_NAME)
    yield
    logger.info("RJA API shutting down")


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------
app = FastAPI(title="RJA API", lifespan=lifespan)

# Session middleware (required for OAuth state storage)
_SESSION_SECRET = os.getenv("SESSION_SECRET", os.getenv("JWT_SECRET", "dev-session-secret"))
app.add_middleware(SessionMiddleware, secret_key=_SESSION_SECRET)

# CORS — open for local dev; lock down to specific origins before public deploy
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router)
app.include_router(health_router)
app.include_router(generate_router)
app.include_router(profile_router)
app.include_router(export_router)
app.include_router(upload_router)

# Frontend — serve Phase 2 static UI
_FRONTEND_DIR = _SRC_DIR / "frontend"
app.mount("/static", StaticFiles(directory=str(_FRONTEND_DIR)), name="static")


@app.get("/")
async def serve_frontend() -> FileResponse:
    return FileResponse(str(_FRONTEND_DIR / "index.html"))


@app.get("/settings")
async def serve_settings() -> FileResponse:
    return FileResponse(str(_FRONTEND_DIR / "settings.html"))
