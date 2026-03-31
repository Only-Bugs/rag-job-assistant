#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

mkdir -p logs

VENV_ACTIVATE="$SCRIPT_DIR/sandbox/bin/activate"
if [[ ! -f "$VENV_ACTIVATE" ]]; then
    echo "ERROR: venv not found at $SCRIPT_DIR/sandbox — run: python -m venv sandbox && pip install -r requirements.txt"
    exit 1
fi

OLLAMA_PID=""
UVICORN_PID=""
STREAMLIT_PID=""

cleanup() {
    echo ""
    echo "Shutting down services..."
    [[ -n "$OLLAMA_PID" ]] && kill "$OLLAMA_PID" 2>/dev/null && echo "  Ollama stopped"
    [[ -n "$UVICORN_PID" ]] && kill "$UVICORN_PID" 2>/dev/null && echo "  FastAPI stopped"
    [[ -n "$STREAMLIT_PID" ]] && kill "$STREAMLIT_PID" 2>/dev/null && echo "  Streamlit stopped"
    exit 0
}
trap cleanup SIGINT SIGTERM

# Check if Ollama is already running
OLLAMA_ALREADY_RUNNING=false
if curl -s --max-time 1 http://localhost:11434 > /dev/null 2>&1; then
    OLLAMA_ALREADY_RUNNING=true
else
    OLLAMA_KEEP_ALIVE=24h ollama serve >> logs/ollama.log 2>&1 &
    OLLAMA_PID=$!
fi

# Activate venv and start FastAPI
(
    source "$VENV_ACTIVATE"
    exec uvicorn src.api.main:app --reload --port 8000
) >> logs/uvicorn.log 2>&1 &
UVICORN_PID=$!

# Activate venv and start Streamlit
(
    source "$VENV_ACTIVATE"
    exec streamlit run src/ui/app.py
) >> logs/streamlit.log 2>&1 &
STREAMLIT_PID=$!

# Startup message
OLLAMA_STATUS="http://localhost:11434"
if $OLLAMA_ALREADY_RUNNING; then
    OLLAMA_STATUS="already running — skipping"
fi

echo "┌─────────────────────────────────────────┐"
echo "│  RJA Dev Environment                    │"
echo "├─────────────────────────────────────────┤"
printf  "│  Ollama     → %-27s│\n" "$OLLAMA_STATUS"
echo "│  FastAPI    → http://localhost:8000     │"
echo "│  Streamlit  → http://localhost:8501     │"
echo "│                                         │"
echo "│  Logs: logs/ollama.log                  │"
echo "│        logs/uvicorn.log                 │"
echo "│        logs/streamlit.log               │"
echo "│                                         │"
echo "│  Stop all: Ctrl+C                       │"
echo "└─────────────────────────────────────────┘"

wait
