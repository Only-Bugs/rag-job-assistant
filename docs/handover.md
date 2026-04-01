# RJA — Session Handover

**Branch:** `HK_Check_Performance_Bottlenecks`
**Repo:** `https://github.com/sheikhmunim/rja`
**Last updated:** 2026-04-01
**Runtime baseline:** ~32s total · SSE streams first task at ~9s

**Last commits:**
```
878aafc docs: add session handover
bbd489c feat: model readiness gate — warm-up on boot, block UI until model loaded
2c7623c feat: Google OAuth + JWT session auth (Phase 3b)
556d1dd feat: per-user data layer, upload/ingest API routes, dev_user migration (Phase 3a)
```

---

## What This Project Is

Local-first RAG pipeline. Takes user resume docs + a job description, generates a full
application package: skills matrix, cover letter, email variants, ATS summary. Fully offline.
No cloud LLMs. Ever.

```
Stack
  Python 3.10
  FastAPI + uvicorn          serving layer
  Ollama  qwen2.5:1.5b       local LLM (fully offline)
  LangChain 0.3.2
  ChromaDB 0.4.22            vector store
  HuggingFace all-MiniLM-L6-v2  embeddings
  PyTorch 2.4.1
```

---

## Phase Status

```
Phase 1   FastAPI backend                          ✓ DONE
Phase 2   Basic frontend                           ✓ DONE
Phase 2b  Editable output, export, profile, settings  ✓ DONE
Phase 3a  Per-user data layer                      ✓ DONE  (this session)
Phase 3b  Google OAuth + JWT auth                  ✓ DONE  (this session)
Phase 3c  Frontend auth integration                ← NEXT
Phase 4   Docker (api + ollama sidecar)            planned
Phase 5   GitHub Actions + ECR                     planned
Phase 6   Terraform (AWS EC2)                      planned
```

---

## First Thing To Do Next Session

Phase 3c — Frontend auth integration. Three pieces:

1. **`src/frontend/login.html`** — new page served at `/login`
   - "Sign in with Google" button that navigates to `/auth/login`
   - Same dark theme as index.html
   - Shown automatically when a 401 is received from any API call

2. **Handle 401s in index.html and settings.html**
   - Wrap all `fetch()` calls in a helper that redirects to `/login` on 401
   - Currently unauthenticated API calls just silently fail

3. **Replace Settings link in header with profile menu**
   - Show Google avatar + display name
   - Dropdown on click:
     - App Settings → `/settings`
     - Account Settings → `/account`
     - Sign out → `/auth/logout`
     - Version string (greyed, bottom)

4. **`src/frontend/account.html`** — new page served at `/account`
   - Connected account section: Google email + avatar
   - Danger zone:
     - "Delete my account and all data" (deletes `data/users/{user_id}/`)
     - "Export my data" (zip of profile_docs + profile JSON)

Note: no password management — Google handles credentials entirely.

---

## What Was Done This Session

### Phase 3a — Per-User Data Layer

All hardcoded `data/job_rag/` paths replaced with per-user paths.
`DEV_USER_ID = "dev_user"` stands in for real auth during local dev.
The old `data/job_rag/` directory is never touched — read-only migration source.

**Target directory layout:**
```
data/
  job_rag/                  ← legacy, never modified
  users/                    ← gitignored
    dev_user/               ← Phase 3a / dev mode
      profile_docs/
      chroma_db/
      profile_settings.json
    <google_sub>/           ← Phase 3b+ real users, one dir per Google sub
```

**Files changed:**

| File | What changed |
|------|-------------|
| `src/rag/config/settings.py` | Added `DATA_USERS_DIR`, `DEV_USER_ID`, `get_user_data_dir(user_id)` |
| `src/rag/vectorstore/chroma_instance.py` | Single `_vectordb` → `_vectordb_cache: dict[str, Chroma]`; `get_vectordb(db_path=None)` |
| `src/rag/ingestion/ingest.py` | `index_profile_docs(user_data_dir=None)`, `index_jd_text(jd, user_data_dir=None)` |
| `src/rag/retrieval/retriever.py` | `retrieve(..., db_path=None)` |
| `src/rag/profile/service.py` | `load/save/reset_profile(user_data_dir=None)` |
| `src/rag/generation/generator.py` | `generate_application_package(..., user_data_dir=None)` |
| `src/api/routes/generate.py` | Per-request `get_user_data_dir(user["user_id"])` via Depends |
| `src/api/routes/profile.py` | Same |
| `src/api/routes/upload.py` | **NEW** — `POST /upload`, `POST /ingest`, `GET /documents` |
| `src/api/main.py` | Register upload router; `_migrate_dev_user()` at lifespan startup |
| `.gitignore` | Added `data/users/` |

**Migration** (runs every startup, idempotent):
- `data/job_rag/profile_settings.json` → `data/users/dev_user/profile_settings.json`
- `data/job_rag/profile_docs/*.{pdf,txt,md}` → `data/users/dev_user/profile_docs/`
- Skips files that already exist. Never deletes source.

**Backward compat:** All `user_data_dir` params default to `None` → falls back to original global constants. `query_pipeline.py` (debug utility) deliberately left untouched.

---

### Phase 3b — Google OAuth + JWT Session Auth

**File:** `src/api/auth.py` (new)

**Flow:**
```
GET /auth/login    → redirect to Google OAuth consent screen
GET /auth/callback → exchange code → fetch userinfo → set JWT cookie → redirect /
GET /auth/logout   → clear cookie → redirect /auth/login
GET /auth/me       → {user_id, email, name} from cookie
```

**Dev mode:** When `GOOGLE_CLIENT_ID`/`GOOGLE_CLIENT_SECRET` are absent, every request returns
`{"user_id": "dev_user", "email": "dev@local", "name": "Dev User"}` with no redirect.
App fully works without any Google setup.

**Auth details:**
- `SessionMiddleware` stores OAuth `state` in a signed cookie (CSRF protection)
- Fetches user info from `https://www.googleapis.com/oauth2/v3/userinfo` via access token
- Creates 30-day HS256 JWT (`python-jose`) in HTTP-only SameSite=Lax cookie `rja_session`
- `user_id` = Google's `sub` (stable, never changes)

**Protected routes:** `/generate`, `/profile` (GET+POST), `/upload`, `/ingest`, `/documents`

**Unprotected:** `/health`, `/auth/*`, `/export/*`

**Frontend:** `GET /auth/me` on page load in index.html + settings.html. User name + "Sign out"
pill appears in header when `name != "Dev User"`. Hidden in dev mode.

**New packages:**
```
python-jose[cryptography]>=3.3.0
python-multipart>=0.0.9
itsdangerous>=2.1.2
```

**New env vars** (see `.env.example`):
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
3. Authorised redirect URI: `http://localhost:8000/auth/callback`
4. Copy client ID + secret into `.env`

---

### Log Routing Fix

**Root cause:** `_emit()` in `src/rag/utils/logging.py` called `print()` unconditionally;
uvicorn captures stdout → `[OK]` timing lines ended up in `uvicorn.log`.

**Fix:**
- `_emit()` calls `print()` only when `sys.stdout.isatty()`
- `_live_timer()` short-circuits when not in a TTY
- `rag`/`api`/`httpx` loggers get `FileHandler → logs/app.log` with `propagate=False` in `main.py`

**Log files:**
| File | Content |
|------|---------|
| `logs/app.log` | Python logger output (`rag.*`, `api.*`) — structured, timestamped |
| `logs/uvicorn.log` | HTTP access log only |
| `logs/ollama.log` | Ollama server + model runner |
| `logs/runtime.log` | Pipeline stage timings (`[OK]` rows) |
| `logs/performance.json` | JSONL per-task TTFT + latency metrics |

---

### dev.sh Rewrite

Streamlit removed entirely. Features:
- Animated braille spinner during startup
- Pre-flight: venv, ollama binary, logs/
- Services: Ollama + FastAPI with PID and URL
- Model warm-up step (see below)
- Status board: SERVICE / URL / PID / LOG
- CPU warning when `compute == "cpu"`
- `open http://localhost:8000` after model is confirmed ready
- Ctrl+C only kills processes this script started (external Ollama left alone)

---

### Model Readiness Gate

**Problem:** Ollama loads weights lazily — cold start takes 30–120s. Users clicking Generate
immediately after `dev.sh` finished would silently wait.

**Three-layer solution:**

**1. `/health` — new field:**
```json
{ "model_ready": true }   // true when compute = "metal" | "cpu"
```

**2. dev.sh — warm-up before browser opens:**
```
API ready → compute == "not_loaded"?
  YES → fire curl POST /api/generate (tiny prompt) in background
        spinner: "Loading model into compute memory..."
        poll /health every 100ms until model_ready=true
        print: "warmed in Xs · compute: metal"
  NO  → print: "already loaded · compute: metal"
→ open browser
```

**3. Frontend — generate button states:**
| State | Appearance | Trigger |
|-------|-----------|---------|
| Model loading | Amber pulse dot · "Loading model — not ready yet" · disabled | page load, `model_ready=false` |
| Ready | Purple · "Generate Application" · enabled | `model_ready=true` |
| Generating | "Generating..." · disabled | SSE stream active |

Frontend polls `/health` every 3s independently. Works even when server is started manually.

---

## Current Architecture

```
src/
  api/
    auth.py           Google OAuth flow, get_current_user() dependency
    main.py           lifespan: migration + log routing; SessionMiddleware
    sse.py            format_sse() helper
    routes/
      health.py       GET /health  → {status, model, compute, model_ready}
      generate.py     POST /generate  SSE stream  (protected)
      profile.py      GET/POST /profile  (protected)
      upload.py       POST /upload · POST /ingest · GET /documents  (protected)
      export.py       POST /export/pdf · POST /export/docx  (unprotected)
  rag/
    config/
      settings.py         get_user_data_dir(), DEV_USER_ID, all Path constants
      model_config.yaml   model name, temperature, token limits, Ollama host
      settings.yaml       data dirs, chunking params
    vectorstore/
      chroma_instance.py  _vectordb_cache, get_vectordb(db_path=None)
    ingestion/
      ingest.py           index_profile_docs/index_jd_text (user_data_dir=None)
    retrieval/
      retriever.py        retrieve(..., db_path=None)
    profile/
      service.py          load/save/reset_profile(user_data_dir=None)
    generation/
      generator.py        generate_application_package(..., user_data_dir=None)
      context_builder.py  per-task minimal prompt assembly
      prompts/templates.py  SYSTEM_SKILLS/COVER/EMAILS/ATS
  frontend/
    index.html        main UI: model readiness polling, user pill, SSE tabs
    settings.html     profile editor: user pill
```

**All API endpoints:**
```
GET  /health            {status, model, ollama_reachable, compute, model_ready}
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
POST /export/pdf        generate PDF from client-supplied content
POST /export/docx       generate DOCX from client-supplied content
GET  /                  serve index.html
GET  /settings          serve settings.html
```

---

## Roadmap Detail

### Phase 3c — Frontend Auth Integration (NEXT)

See "First Thing To Do Next Session" above for full spec.

Key files to create/modify:
- `src/frontend/login.html` (new) — served at `/login`
- `src/frontend/account.html` (new) — served at `/account`
- `src/api/main.py` — add `/login` and `/account` static routes
- `src/frontend/index.html` — replace header Settings link with avatar+dropdown, handle 401s
- `src/frontend/settings.html` — handle 401s

---

### Phase 4 — Docker

**Design: sidecar — two compose services:**
```yaml
services:
  api:
    build: .
    ports: ["8000:8000"]
    environment:
      OLLAMA_HOST: http://ollama:11434
    volumes:
      - user_data:/app/data/users
    depends_on: [ollama]

  ollama:
    image: ollama/ollama
    volumes:
      - ollama_models:/root/.ollama  # weights on named volume, not baked into image
    entrypoint: |
      sh -c "ollama serve & sleep 5 && ollama pull qwen2.5:1.5b && wait"
```

- `Dockerfile`: multi-stage — install deps → copy src → expose 8000
- `.dockerignore`: exclude `data/`, `logs/`, `sandbox/`, `*.pyc`
- `data/users/` mounted as a named volume so user data survives container restarts
- `OLLAMA_KEEP_ALIVE=24h` must be set in compose env (currently only in dev.sh)
- Registry: **Amazon ECR** (not GHCR)

---

### Phase 5 — GitHub Actions + ECR

Trigger: push to `main`

Steps:
1. Build Docker image
2. Push to Amazon ECR
3. Deploy to EC2 via SSM (pull new image, `docker compose up -d`)
4. Discord webhook notification (success or failure)

Prerequisite: `tests/` must have real tests as CI gate before this runs.

---

### Phase 6 — Terraform (AWS EC2)

**Target:** EC2 `g4dn.xlarge` — NVIDIA T4, ~$0.526/hr (GPU-accelerated Ollama)

**Files:**
```
infrastructure/
  ec2.tf        instance, security groups, IAM role
  ebs.tf        persistent EBS volume for Ollama model weights + user data
  userdata.sh   installs Docker, nvidia-container-toolkit,
                pulls ECR image, runs docker compose up
```

**Goal:** `terraform init && terraform apply` → EC2 up, Docker running, model pulled, API live at HTTPS.

**Secrets in AWS Secrets Manager:** `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `JWT_SECRET`

**CORS must be locked down** from `allow_origins=["*"]` to the EC2/ALB origin before this goes live.

---

## Outstanding Tech Debt

- **`tests/`** — completely empty. Minimum before Phase 5 CI gate:
  - `GET /health` smoke test
  - `POST /generate` with a fixture JD (mock Ollama)
  - Profile CRUD round-trip (`GET /profile` → `POST /profile` → `GET /profile`)
- **`src/rag/evaluation/`** — reserved empty package; no metrics implemented
- **`.env` git history** — was accidentally tracked in an early commit; verify fully excluded now
- **`query_pipeline.py`** — debug utility, not in API path; fine to leave as-is
- **`OLLAMA_KEEP_ALIVE=24h`** — set in dev.sh but must be added to docker-compose.yml in Phase 4
- **JWT_SECRET fallback** — current fallback is `secrets.token_hex(32)` per process startup;
  this invalidates all sessions on restart. Must be set explicitly in `.env` / Secrets Manager for prod.

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
# Runs pre-flight checks, starts Ollama + API, warms model, opens http://localhost:8000

# Manual start (separate terminals)
OLLAMA_KEEP_ALIVE=24h ollama serve
source sandbox/bin/activate
uvicorn src.api.main:app --reload --port 8000

# Enable Google auth (optional — app works fully without it)
cp .env.example .env
# Fill in GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, JWT_SECRET
```

---

## Key Rules — Never Break These

- **No external LLM APIs** — Ollama only. No OpenAI/Anthropic/cloud calls ever.
- **Sequential generation** — `gen_skills → gen_cover → gen_emails → gen_ats` in one thread. `ThreadPoolExecutor` was removed after profiling showed severe queue contention against a single Ollama instance. Do not reintroduce without benchmarking first.
- **`data/job_rag/profile_docs/`** — read-only. Never delete or overwrite.
- **`data/users/`** — gitignored. Runtime-generated. Must be a persistent volume in production (EBS/named Docker volume).
- **Chroma telemetry** — `anonymized_telemetry=False` in `chroma_instance.py`. Must stay disabled.
- **CORS** — `allow_origins=["*"]` for local dev. Lock to specific origin before any public deploy.
- **JWT_SECRET** — must be stable across restarts. Falling back to a per-process random value is fine locally, not in production.
- **Python 3.10 minimum** — `X | None` union syntax used throughout.
- **ECR for image registry** — not GHCR.
- **`src/rag/`** — treat as read-only unless explicitly changing pipeline logic.

---

## Working Style

- Planning and architecture → Claude chat (this interface)
- Implementation → Claude Code terminal (`claude` CLI)
- Loop: describe what to do in Claude Code → review diff → diagnose → next step
- Handover doc (`docs/handover.md`) updated at every session end and committed
- `CLAUDE.md` in repo root is read automatically by Claude Code on every session
