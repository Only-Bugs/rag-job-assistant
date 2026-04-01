# RJA — Session Handover

**Branch:** `HK_Check_Performance_Bottlenecks`
**Last updated:** 2026-04-01
**Last commits:**
```
bbd489c feat: model readiness gate — warm-up on boot, block UI until model loaded
2c7623c feat: Google OAuth + JWT session auth (Phase 3b)
556d1dd feat: per-user data layer, upload/ingest API routes, dev_user migration (Phase 3a)
```

---

## What Was Done This Session

### Phase 3a — Per-User Data Layer

All hardcoded `data/job_rag/` paths replaced with per-user paths. A `DEV_USER_ID = "dev_user"` constant stands in for real auth during local development. The old `data/job_rag/` directory is left untouched — it is the read-only migration source.

**Target directory layout:**
```
data/
  job_rag/                  ← legacy, never modified
  users/
    dev_user/               ← Phase 3a target (gitignored)
      profile_docs/
      chroma_db/
      profile_settings.json
    <google_sub>/           ← Phase 3b+ real users
```

**Files changed:**

| File | What changed |
|------|-------------|
| `src/rag/config/settings.py` | Added `DATA_USERS_DIR`, `DEV_USER_ID`, `get_user_data_dir(user_id)` |
| `src/rag/vectorstore/chroma_instance.py` | Replaced single `_vectordb` global with `_vectordb_cache: dict[str, Chroma]`; `get_vectordb(db_path=None)` |
| `src/rag/ingestion/ingest.py` | `index_profile_docs(user_data_dir=None)`, `index_jd_text(jd, user_data_dir=None)` — uses local vars instead of module globals |
| `src/rag/retrieval/retriever.py` | `retrieve(..., db_path=None)` passes `db_path` to `get_vectordb` |
| `src/rag/profile/service.py` | `load_profile(user_data_dir=None)`, `save_profile(p, user_data_dir=None)`, `reset_profile(user_data_dir=None)` |
| `src/rag/generation/generator.py` | `generate_application_package(..., user_data_dir=None)` threads param through body |
| `src/api/routes/generate.py` | Module-level `_USER_DATA_DIR` constant replaced by per-request `get_user_data_dir(user["user_id"])` |
| `src/api/routes/profile.py` | Same — per-request user dir |
| `src/api/routes/upload.py` | **NEW** — `POST /upload`, `POST /ingest`, `GET /documents` |
| `src/api/main.py` | Register upload router; `_migrate_dev_user()` runs at lifespan startup |
| `.gitignore` | Added `data/users/` |

**Migration logic** (`main.py` lifespan startup):
- Copies `data/job_rag/profile_settings.json` → `data/users/dev_user/profile_settings.json` if not already present
- Copies `data/job_rag/profile_docs/*.{pdf,txt,md}` → `data/users/dev_user/profile_docs/` (never deletes source)
- Safe to run on every startup — skips files that already exist

**Backward compatibility:** All `user_data_dir` params default to `None`, which falls back to the original global constants. `src/rag/retrieval/query_pipeline.py` (debug utility, not in API path) was deliberately left untouched.

---

### Phase 3b — Google OAuth + JWT Session Auth

**File:** `src/api/auth.py` (new)

**Flow:**
```
GET /auth/login    → redirect to Google OAuth consent screen
GET /auth/callback → exchange code → fetch userinfo → set rja_session JWT cookie → redirect /
GET /auth/logout   → delete cookie → redirect /auth/login
GET /auth/me       → return {user_id, email, name} from cookie
```

**Dev mode (no credentials configured):**
When `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` are absent from `.env`, every request returns `{"user_id": "dev_user", "email": "dev@local", "name": "Dev User"}` with no redirect. The app is fully functional locally without any Google setup.

**Auth flow details:**
- `SessionMiddleware` (Starlette) stores OAuth `state` in a signed cookie for CSRF protection
- After callback: fetches user profile from `https://www.googleapis.com/oauth2/v3/userinfo` using the access token
- Creates a 30-day HS256 JWT (`python-jose`) stored in an HTTP-only, SameSite=Lax cookie named `rja_session`
- `user_id` = Google's `sub` field (stable unique identifier)

**Dependency injection:**
All protected routes use `Depends(get_current_user)` which returns `{"user_id", "email", "name"}`. Routes resolve `user_data_dir = get_user_data_dir(user["user_id"])` per-request.

**Protected routes:** `/generate`, `/profile` (GET+POST), `/upload`, `/ingest`, `/documents`

**Not protected:** `/health`, `/auth/*`, `/export/*` (export works on client-supplied content)

**Frontend:**
- `GET /auth/me` called on page load in both `index.html` and `settings.html`
- If `name != "Dev User"`: user name + "Sign out" link appear in header
- In dev mode: pill stays hidden, no visual noise

**New packages added to `requirements.txt`:**
- `python-jose[cryptography]>=3.3.0` — JWT encode/decode
- `python-multipart>=0.0.9` — FastAPI file upload dependency
- `itsdangerous>=2.1.2` — Starlette SessionMiddleware dependency

**New env vars (add to `.env`, see `.env.example`):**
```bash
GOOGLE_CLIENT_ID=
GOOGLE_CLIENT_SECRET=
AUTH_REDIRECT_URI=http://localhost:8000/auth/callback
JWT_SECRET=          # openssl rand -hex 32
SESSION_SECRET=      # defaults to JWT_SECRET if unset
```

**Google Cloud setup (one-time):**
1. Google Cloud Console → APIs & Services → Credentials → Create OAuth 2.0 Client ID
2. Application type: Web application
3. Authorised redirect URIs: `http://localhost:8000/auth/callback`
4. Copy client ID + secret into `.env`

---

### Log Routing Fix

**Problem:** `[OK]` timing lines from `rag/utils/logging.py` were appearing in `uvicorn.log` because `_emit()` called `print()` unconditionally and uvicorn captures stdout.

**Fix in `src/rag/utils/logging.py`:**
- Added `import sys`
- `_emit()` now calls `print()` only when `sys.stdout.isatty()` (interactive terminal)
- `_live_timer()` short-circuits immediately when not in a TTY
- All `rag`/`api`/`httpx` loggers get a `FileHandler → logs/app.log` with `propagate=False` in `main.py`, so Python logger output no longer bubbles to uvicorn's captured stdout

**Log files and their purpose:**
| File | Content |
|------|---------|
| `logs/app.log` | Python logger output (`rag.*`, `api.*`) — structured, timestamped |
| `logs/uvicorn.log` | HTTP access log only — clean, no model output |
| `logs/ollama.log` | Ollama server + model runner output |
| `logs/runtime.log` | Pipeline stage timings (`[OK]` table rows) |
| `logs/performance.json` | JSONL per-task TTFT + latency metrics |

---

### dev.sh Rewrite

Streamlit completely removed. New features:
- Animated braille spinner (`⣾⣽⣻⢿⡿⣟⣯⣷`) during service startup
- Pre-flight checks: venv, ollama binary, logs/
- Services section: Ollama + FastAPI with PID and URL
- **Model warm-up step** (see next section)
- Status board table: SERVICE / URL / PID / LOG columns
- CPU warning if `compute == "cpu"`
- `open http://localhost:8000` after everything is confirmed ready
- Ctrl+C only kills processes this script started (external Ollama is left alone)

---

### Model Readiness Gate

**Problem:** Ollama loads model weights lazily — first inference request triggers a 30–120s cold load. Users who clicked Generate immediately after `dev.sh` finished would silently wait with no feedback.

**Three-layer solution:**

**1. `/health` response — new field:**
```json
{ "model_ready": true }   // true when compute = "metal" | "cpu"
```

**2. `dev.sh` — model warm-up before browser opens:**
```
API ready → compute == "not_loaded"?
  YES → fire tiny curl /api/generate in background (forces weight load)
        spinner: "Loading model into compute memory..."
        poll /health every 100ms until model_ready=true
        print: "warmed in Xs · compute: metal"
        open browser
  NO  → print: "already loaded · compute: metal"
        open browser immediately
```

**3. Frontend — generate button states:**

| State | Button appearance | Trigger |
|-------|------------------|---------|
| Model loading | Amber pulse dot · "Loading model — not ready yet" · disabled | On page load, `model_ready=false` |
| Ready | Purple · "Generate Application" · enabled | `model_ready=true` |
| Generating | "Generating..." · disabled | During SSE stream |

- Polls `/health` every 3s independently of dev.sh (works even when server is started manually)
- `_modelReady` flag guards the click handler as a second safety net

---

## Current Architecture

```
src/
  api/
    auth.py           ← NEW — Google OAuth flow, get_current_user() dependency
    main.py           ← lifespan: migration + logging setup; SessionMiddleware
    sse.py            ← format_sse() helper
    routes/
      health.py       ← GET /health  {status, model, ollama_reachable, compute, model_ready}
      generate.py     ← POST /generate  SSE stream (Depends(get_current_user))
      profile.py      ← GET/POST /profile  (Depends(get_current_user))
      upload.py       ← POST /upload, POST /ingest, GET /documents
      export.py       ← POST /export/pdf, POST /export/docx  (no auth — content in body)
  rag/
    config/
      settings.py     ← get_user_data_dir(), DEV_USER_ID, all Path constants
    vectorstore/
      chroma_instance.py  ← _vectordb_cache dict, get_vectordb(db_path=None)
    ingestion/
      ingest.py       ← index_profile_docs(user_data_dir=None), index_jd_text(jd, user_data_dir=None)
    retrieval/
      retriever.py    ← retrieve(..., db_path=None)
    profile/
      service.py      ← load/save/reset_profile(user_data_dir=None)
    generation/
      generator.py    ← generate_application_package(..., user_data_dir=None)
  frontend/
    index.html        ← main UI: model readiness polling, user pill
    settings.html     ← profile editor: user pill
```

**API endpoints (full list):**
```
GET  /health            liveness + compute + model_ready
GET  /auth/login        → Google consent redirect
GET  /auth/callback     exchange code, set JWT cookie
GET  /auth/logout       clear cookie
GET  /auth/me           {user_id, email, name}
POST /generate          SSE stream  (protected)
GET  /profile           load profile JSON  (protected)
POST /profile           save profile JSON  (protected)
POST /upload            upload resume file  (protected)
POST /ingest            re-index profile docs  (protected)
GET  /documents         list profile docs  (protected)
POST /export/pdf        generate PDF from content
POST /export/docx       generate DOCX from content
GET  /                  serve index.html
GET  /settings          serve settings.html
```

---

## What Still Needs Doing

### Phase 3c — Frontend Auth Integration
- Login page (`/login.html`) with Google Sign-In button — currently users hit `/auth/login` directly
- Handle 401 responses from API in JS (redirect to `/auth/login`)
- Show email in the user pill (currently shows `name` which may be a Google display name)

### Phase 4 — Docker
- `Dockerfile` for the FastAPI app
- `docker-compose.yml`: `api` service + Ollama sidecar
- `.dockerignore`
- Multi-stage build: install deps → copy src → expose 8000
- Mount `data/users/` as a volume (user data must persist across container restarts)
- `OLLAMA_HOST` env var already used — just point it at the Ollama container

### Phase 5 — GitHub Actions + ECR
- Build + push Docker image to AWS ECR on push to `main`
- Run `pytest tests/` as CI gate (tests are currently empty stubs)

### Phase 6 — Terraform
- ECS Fargate task definition
- ALB + HTTPS listener
- EFS mount for `data/users/` (persistent user data)
- Secrets Manager for `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `JWT_SECRET`
- Lock down CORS to the ALB origin (currently `allow_origins=["*"]`)

### Outstanding Tech Debt
- `tests/` — completely empty. Minimum needed before Phase 5: smoke test for `POST /health`, `POST /generate` with a fixture JD, profile CRUD round-trip.
- `src/rag/evaluation/` — reserved empty package; no metrics implemented.
- `.env` was accidentally git-tracked in an earlier commit — verify it is now fully excluded.
- `query_pipeline.py` — debug utility, not wired into the API. Fine to leave as-is.
- `OLLAMA_KEEP_ALIVE=24h` is set in `dev.sh` but not in the Docker/production path — add it to the compose file.

---

## Running the Project

```bash
# One-time setup
python -m venv sandbox
source sandbox/bin/activate
pip install -r requirements.txt
ollama pull qwen2.5:1.5b

# Start everything (recommended)
./dev.sh
# Opens http://localhost:8000 after Ollama + API are ready and model is warmed

# Manual start (if you need separate terminals)
OLLAMA_KEEP_ALIVE=24h ollama serve
uvicorn src.api.main:app --reload --port 8000

# Enable Google auth (optional — app works without it)
cp .env.example .env
# Fill in GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, JWT_SECRET in .env
```

---

## Key Decisions & Rules

- **No external LLM APIs** — Ollama only. Never add OpenAI/Anthropic calls.
- **Sequential generation** — `gen_skills → gen_cover → gen_emails → gen_ats` in one thread. `ThreadPoolExecutor` was removed after profiling showed severe queue contention against a single Ollama instance. Do not reintroduce without benchmarking.
- **`data/job_rag/profile_docs/`** — user resume files. Read-only. Never delete or overwrite.
- **`data/users/`** — gitignored. Runtime-generated. Must be a persistent volume in production.
- **Chroma telemetry** — must stay disabled (`anonymized_telemetry=False` in `chroma_instance.py`).
- **CORS** — currently `allow_origins=["*"]`. Lock to specific origin before any public deploy.
- **JWT_SECRET** — must be stable across restarts in production. Set it explicitly in `.env` / Secrets Manager. The current fallback (`secrets.token_hex(32)` per process) invalidates all sessions on restart.
- **Python 3.10 minimum** — uses `X | None` union syntax throughout.
