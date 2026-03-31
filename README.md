# RJA — Resume & Job Application Assistant

> Local-first. Fully offline. No cloud. No subscriptions.
> Paste a job description, get a tailored skills matrix, cover letter,
> email variants, and ATS summary — generated entirely on your machine.

---

## What it does

RJA takes your resume documents and a job description, runs them through
a local RAG pipeline, and produces a complete application package:

| Output         | Description                                              |
| -------------- | -------------------------------------------------------- |
| Skills Matrix  | Hard and soft skills mapped directly to the JD           |
| Cover Letter   | Tailored narrative built from your actual experience     |
| Email Variants | Application email + follow-up template                   |
| ATS Summary    | Keyword-optimised summary for applicant tracking systems |

Everything runs on-device. Your documents never leave your machine.

---

## Tech stack

| Component                      | What it does                              |
| ------------------------------ | ----------------------------------------- |
| FastAPI                        | REST API + SSE streaming backend          |
| Ollama (qwen2.5:1.5b)          | Local LLM runner                          |
| LangChain                      | RAG pipeline and prompt orchestration     |
| ChromaDB                       | Local vector store for semantic retrieval |
| HuggingFace (all-MiniLM-L6-v2) | Embedding model                           |
| Python 3.10+                   | Core logic                                |

---

## Quick start

### Prerequisites

- Python 3.10+
- Ollama installed — https://ollama.ai/download

### 1. Clone and set up

```bash
git clone https://github.com/sheikhmunim/rja.git
cd rja
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 2. Pull the model

```bash
ollama pull qwen2.5:1.5b
```

### 3. Start Ollama (separate terminal)

```bash
OLLAMA_KEEP_ALIVE=24h ollama serve
```

### 4. Start the API

```bash
uvicorn src.api.main:app --reload --port 8000
```

### 5. Open the app

```
http://localhost:8000
```

---

## Add your documents

Drop your resume, portfolio, or project summaries into:

```
data/job_rag/profile_docs/
```

Supported: `.pdf` `.txt` `.md`

The pipeline indexes them on first run automatically.

---

## Configuration

Copy `.env.example` to `.env` to override defaults:

```bash
cp .env.example .env
```

Environment variables:

| Variable      | Default                  | Description            |
| ------------- | ------------------------ | ---------------------- |
| `OLLAMA_HOST` | `http://localhost:11434` | Ollama server endpoint |
| `LLM_MODEL`   | `qwen2.5:1.5b`           | Active model           |
| `LOG_LEVEL`   | `INFO`                   | Logging verbosity      |

Config files:

- `src/rag/config/model_config.yaml` — model name, token limits, Ollama host
- `src/rag/config/settings.yaml` — data paths, chunking parameters
- `data/job_rag/profile_settings.json` — your profile (name, skills, experience)

---

## API reference

### GET /health

Returns API and Ollama status.

```json
{
  "status": "ok",
  "model": "qwen2.5:1.5b",
  "ollama_reachable": true
}
```

### POST /generate

Streams the application package as server-sent events.

Request body:

```json
{
  "job_description": "string"
}
```

SSE event stream:

```
event: status  data: starting
event: task    data: {"task": "skills", "content": "..."}
event: task    data: {"task": "cover",  "content": "..."}
event: task    data: {"task": "emails", "content": "..."}
event: task    data: {"task": "ats",    "content": "..."}
event: status  data: done
```

Test with curl:

```bash
curl -s http://localhost:8000/health | python -m json.tool
```

```bash
curl -N -X POST http://localhost:8000/generate \
  -H "Content-Type: application/json" \
  -d '{"job_description": "Python engineer with RAG experience"}'
```

---

## Project structure

```
project_root/
├── src/
│   ├── api/                  # FastAPI app (main.py, routes/, sse.py)
│   ├── rag/                  # Pipeline (ingestion, retrieval, generation)
│   │   ├── config/           # settings.yaml, model_config.yaml
│   │   ├── ingestion/        # PDF/TXT/MD loaders, chunking, Chroma writes
│   │   ├── vectorstore/      # Chroma singleton
│   │   ├── models/           # Embedding + Ollama LLM clients
│   │   ├── retrieval/        # Retriever + query pipeline
│   │   ├── generation/       # Prompts + sequential generator
│   │   └── utils/            # Logging, text helpers, exceptions
│   ├── frontend/             # Static UI (index.html)
│   └── ui/                   # Legacy Streamlit app (being retired)
├── data/
│   └── job_rag/
│       └── profile_docs/     # Your resume files — read-only, never deleted
├── scripts/                  # Benchmarking tools
├── docs/                     # Architecture and performance notes
├── old.backup/               # Archived dead files
├── requirements.txt
└── .env.example
```

---

## Roadmap

### In progress

- [ ] Custom frontend (replacing Streamlit) — Phase 2
- [ ] Docker setup with Ollama sidecar — Phase 3
- [ ] GitHub Actions: build → ECR push → Discord notify — Phase 4
- [ ] Terraform deployment to AWS EC2 — Phase 5

### Planned

- [ ] Profile management UI (currently JSON file only)
- [ ] Multi-profile support
- [ ] Real test coverage (`tests/` is currently empty)
- [ ] Streaming token-level output (currently streams per task)
- [ ] Support for more document formats (DOCX, HTML)

### Completed

- [x] Sequential generation (replaced ThreadPoolExecutor — 54% faster)
- [x] Model swap llama3.2:3b → qwen2.5:1.5b (2x faster per task)
- [x] SSE streaming backend via FastAPI
- [x] Performance benchmarking scripts
- [x] Sub-stage timing instrumentation

---

## Hard rules (for contributors)

- No external LLM API calls — fully local and offline
- Chroma telemetry must stay disabled (`anonymized_telemetry=False`)
- Python 3.10 minimum

## License

MIT — free to use and modify with attribution.
