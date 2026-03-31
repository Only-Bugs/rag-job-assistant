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

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

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

from api.routes.generate import router as generate_router  # noqa: E402
from api.routes.health import router as health_router  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(name)s  %(message)s")
logger = logging.getLogger("api")


# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("RJA API ready  |  model=%s", MODEL_NAME)
    yield
    logger.info("RJA API shutting down")


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------
app = FastAPI(title="RJA API", lifespan=lifespan)

# CORS — open for Phase 1; lock down to specific origins in Phase 3
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health_router)
app.include_router(generate_router)
