"""ResuMate FastAPI application.

Run from the project root:
    uvicorn src.resumate.app:app --reload --port 8000
"""

from __future__ import annotations

import os

# Must be set before any transformers/sentence-transformers import.
os.environ.setdefault("USE_TF", "0")
os.environ.setdefault("USE_JAX", "0")

import logging
import threading
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

# ---------------------------------------------------------------------------
# File-based log handler
# ---------------------------------------------------------------------------
_LOG_DIR = Path(__file__).resolve().parents[2] / "logs"
_LOG_DIR.mkdir(parents=True, exist_ok=True)
_app_log_handler = logging.FileHandler(_LOG_DIR / "app.log", encoding="utf-8")
_app_log_handler.setFormatter(
    logging.Formatter("%(asctime)s  %(levelname)-8s  %(name)s  %(message)s")
)
for _name in ("resumate", "httpx"):
    _lg = logging.getLogger(_name)
    _lg.addHandler(_app_log_handler)
    _lg.propagate = False

# ---------------------------------------------------------------------------
# Project imports
# ---------------------------------------------------------------------------
from resumate.config.settings import MODEL_NAME, DEV_USER_ID, get_user_data_dir  # noqa: E402

from resumate.routes.auth import router as auth_router  # noqa: E402
from resumate.routes.drive import router as drive_router  # noqa: E402
from resumate.routes.export import router as export_router  # noqa: E402
from resumate.routes.generate import router as generate_router  # noqa: E402
from resumate.routes.gmail import router as gmail_router  # noqa: E402
from resumate.routes.health import router as health_router  # noqa: E402
from resumate.routes.profile import router as profile_router  # noqa: E402
from resumate.routes.documents import router as documents_router  # noqa: E402
from resumate.routes.pages import router as pages_router  # noqa: E402
from resumate.routes.tools import router as tools_router  # noqa: E402
from resumate.routes.models import router as models_router  # noqa: E402
from resumate.routes.applications import router as applications_router  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(name)s  %(message)s")
logger = logging.getLogger("resumate")


# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------
async def _migrate_dev_user() -> None:
    """One-time migration: copy legacy data/job_rag/ files into data/users/dev_user/."""
    import shutil
    from resumate.config.settings import PROFILE_DOC_DIR, RAG_DIR

    user_dir = get_user_data_dir(DEV_USER_ID)

    src_json = RAG_DIR / "profile_settings.json"
    dst_json = user_dir / "profile_settings.json"
    if src_json.exists() and not dst_json.exists():
        shutil.copy2(src_json, dst_json)
        logger.info("migration: profile_settings.json -> %s", dst_json)

    if PROFILE_DOC_DIR.exists():
        for f in PROFILE_DOC_DIR.iterdir():
            if f.is_file() and f.suffix.lower() in {".pdf", ".txt", ".md"}:
                dest = user_dir / "profile_docs" / f.name
                if not dest.exists():
                    shutil.copy2(f, dest)
                    logger.info("migration: %s -> %s", f.name, dest)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await _migrate_dev_user()

    # Phase E: Warm up embedding model in background thread
    def _warmup():
        try:
            from resumate.models.embeddings import get_embeddings
            get_embeddings()
        except Exception as exc:
            logger.warning("embedding warm-up failed: %s", exc)

    threading.Thread(target=_warmup, daemon=True).start()

    # Load the LLM now so the first Generate never pays a cold model load.
    def _llm_warmup():
        try:
            from resumate.models.llm import warm_up
            warm_up()
        except Exception as exc:
            logger.warning("LLM warm-up failed (is Ollama running?): %s", exc)

    threading.Thread(target=_llm_warmup, daemon=True).start()

    logger.info("ResuMate API ready  |  model=%s", MODEL_NAME)
    yield
    logger.info("ResuMate API shutting down")


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------
app = FastAPI(title="ResuMate API", lifespan=lifespan)

# Session middleware (required for OAuth state storage)
_SESSION_SECRET = os.getenv("SESSION_SECRET", os.getenv("JWT_SECRET", "dev-session-secret"))
app.add_middleware(SessionMiddleware, secret_key=_SESSION_SECRET)

# CORS
_cors_origins = [o.strip() for o in os.getenv("CORS_ORIGINS", "*").split(",")]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Always revalidate frontend assets and pages. StaticFiles sends ETag /
# Last-Modified, so this costs a 304 locally but means edited JS/CSS is never
# served stale from the browser cache.
@app.middleware("http")
async def _no_cache_frontend(request: Request, call_next):
    response = await call_next(request)
    ctype = response.headers.get("content-type", "")
    if request.url.path.startswith("/static/") or ctype.startswith("text/html"):
        response.headers["Cache-Control"] = "no-cache"
    return response


# API routes (before pages to ensure API paths take priority)
app.include_router(auth_router)
app.include_router(health_router)
app.include_router(generate_router)
app.include_router(profile_router)
app.include_router(export_router)
app.include_router(documents_router)
app.include_router(tools_router)
app.include_router(gmail_router)
app.include_router(drive_router)
app.include_router(models_router)
app.include_router(applications_router)

# Frontend static files
_FRONTEND_DIR = Path(__file__).resolve().parents[1] / "frontend"
app.mount("/static", StaticFiles(directory=str(_FRONTEND_DIR)), name="static")

# Page routes (after static mount)
app.include_router(pages_router)


# Catch-all 404 for unmatched paths
@app.api_route("/{path:path}", methods=["GET"], include_in_schema=False)
async def catch_all(request: Request, path: str):
    _404_page = _FRONTEND_DIR / "pages" / "404.html"
    if _404_page.exists():
        return HTMLResponse(_404_page.read_text(encoding="utf-8"), status_code=404)
    return HTMLResponse("<h1>404 — Page not found</h1>", status_code=404)
