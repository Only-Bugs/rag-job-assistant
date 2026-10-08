"""Shared fixtures for ResuMate API tests.

All tests run in dev mode (no Google OAuth creds) so get_current_user
always returns dev_user. A tmp_path-based data dir isolates every test
from the real data/ directory.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

# Ensure src/ is on the path so resumate.* imports resolve.
_SRC_DIR = Path(__file__).resolve().parents[1] / "src"
if str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))

# Suppress TF/Keras side-effects before any transformers import.
os.environ.setdefault("USE_TF", "0")
os.environ.setdefault("USE_JAX", "0")
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
# Force dev mode: auth.AUTH_ENABLED is computed at import from these vars, and a
# developer .env with real Google creds would otherwise turn auth on (401s).
# load_dotenv() never overrides variables that are already set.
os.environ["GOOGLE_CLIENT_ID"] = ""
os.environ["GOOGLE_CLIENT_SECRET"] = ""


@pytest.fixture()
def tmp_data_dir(tmp_path: Path) -> Path:
    """Create a temporary per-user data directory tree."""
    (tmp_path / "profile_docs").mkdir()
    (tmp_path / "chroma_db").mkdir()
    return tmp_path


@pytest.fixture()
def client(tmp_data_dir: Path):
    """Synchronous TestClient wired to the ResuMate FastAPI app.

    - Overrides get_user_data_dir to point at the temp dir.
    - Patches the lifespan migration so it doesn't touch real data/.
    """
    from starlette.testclient import TestClient

    from resumate.app import app
    from resumate.config import settings

    def _fake_user_data_dir(user_id: str = "dev_user") -> Path:
        (tmp_data_dir / "profile_docs").mkdir(exist_ok=True)
        (tmp_data_dir / "chroma_db").mkdir(exist_ok=True)
        return tmp_data_dir

    with patch.object(settings, "get_user_data_dir", side_effect=_fake_user_data_dir):
        with TestClient(app, raise_server_exceptions=False) as c:
            yield c
