#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"
mkdir -p logs

# ── Colours ───────────────────────────────────────────────────────────────────
RST=$'\e[0m'
BOLD=$'\e[1m'
DIM=$'\e[2m'
G=$'\e[32m'
Y=$'\e[33m'
R=$'\e[31m'
C=$'\e[36m'
M=$'\e[35m'
W=$'\e[97m'

TICK="${G}✓${RST}"
CROSS="${R}✗${RST}"
WARN="${Y}⚠${RST}"
DOT="${C}·${RST}"

VENV="$SCRIPT_DIR/sandbox/bin/activate"

# ── Helpers ───────────────────────────────────────────────────────────────────
hr() { printf "  ${DIM}%s${RST}\n" "──────────────────────────────────────────────────────────"; }

step() {
    # step <icon> <label> <detail>
    printf "  %s  ${BOLD}%-16s${RST} %s\n" "$1" "$2" "$3"
}

wait_and_spin() {
    local msg=$1 url=$2 timeout_s=${3:-30}
    local -a f=('⣾' '⣽' '⣻' '⢿' '⡿' '⣟' '⣯' '⣷')
    local i=0 ticks=0 limit=$(( timeout_s * 10 ))
    while ! curl -sf --max-time 1 "$url" >/dev/null 2>&1; do
        printf "\r  ${C}${f[$i]}${RST}  %s " "$msg"
        i=$(( (i + 1) % 8 ))
        sleep 0.1
        ticks=$(( ticks + 1 ))
        [[ $ticks -ge $limit ]] && printf "\r%70s\r" "" && return 1
    done
    printf "\r%70s\r" ""
    return 0
}

wait_model_ready() {
    # Fire a tiny warm-up prompt so Ollama loads the model into memory.
    # Spins until /health reports model_ready=true (compute = metal|cpu).
    local model=$1 timeout_s=${2:-120}
    local -a f=('⣾' '⣽' '⣻' '⢿' '⡿' '⣟' '⣯' '⣷')
    local i=0 ticks=0 limit=$(( timeout_s * 10 ))

    # Kick off a minimal inference in the background — forces Ollama to load weights.
    curl -sf -X POST http://localhost:11434/api/generate \
        -H "Content-Type: application/json" \
        -d "{\"model\":\"${model}\",\"prompt\":\"hi\",\"stream\":false}" \
        >/dev/null 2>&1 &
    local warmup_pid=$!

    while true; do
        local ready
        ready="$(curl -sf http://localhost:8000/health 2>/dev/null \
            | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('model_ready','false'))" 2>/dev/null \
            || echo "false")"
        [[ "$ready" == "True" || "$ready" == "true" ]] && printf "\r%70s\r" "" && return 0
        printf "\r  ${C}${f[$i]}${RST}  ${DIM}Loading model into compute memory...${RST} "
        i=$(( (i + 1) % 8 ))
        sleep 0.1
        ticks=$(( ticks + 1 ))
        if [[ $ticks -ge $limit ]]; then
            printf "\r%70s\r" ""
            kill "$warmup_pid" 2>/dev/null || true
            return 1
        fi
    done
}

json_field() {
    # json_field <url> <key>
    curl -sf "$1" 2>/dev/null \
        | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('$2','unknown'))" 2>/dev/null \
        || echo "unknown"
}

# ── PIDs ──────────────────────────────────────────────────────────────────────
OLLAMA_PID=""
UVICORN_PID=""

cleanup() {
    printf "\n\n"
    hr
    printf "\n  ${Y}${BOLD}Shutting down${RST}\n\n"
    if [[ -n "$UVICORN_PID" ]] && kill -0 "$UVICORN_PID" 2>/dev/null; then
        kill "$UVICORN_PID" 2>/dev/null
        step "$TICK" "api" "stopped"
    fi
    if [[ -n "$OLLAMA_PID" ]] && kill -0 "$OLLAMA_PID" 2>/dev/null; then
        kill "$OLLAMA_PID" 2>/dev/null
        step "$TICK" "ollama" "stopped"
    fi
    printf "\n  ${DIM}Goodbye.${RST}\n\n"
    exit 0
}
trap cleanup SIGINT SIGTERM

# ═══════════════════════════════════════════════════════════════════════════════
# BANNER
# ═══════════════════════════════════════════════════════════════════════════════
clear
printf "\n"
printf "  ${M}╭──────────────────────────────────────────────────────────╮${RST}\n"
printf "  ${M}│${RST}                                                          ${M}│${RST}\n"
printf "  ${M}│${RST}   ${W}${BOLD}ResuMate${RST}   ${DIM}Resume & Job Application Assistant${RST}        ${M}│${RST}\n"
printf "  ${M}│${RST}   ${DIM}v0.2  ·  qwen2.5:1.5b  ·  FastAPI  ·  ChromaDB${RST}          ${M}│${RST}\n"
printf "  ${M}│${RST}                                                          ${M}│${RST}\n"
printf "  ${M}╰──────────────────────────────────────────────────────────╯${RST}\n"
printf "\n"
printf "  ${DIM}%s${RST}\n" "$(date '+%A, %B %d %Y  %H:%M:%S %Z')"
printf "\n"
sleep 0.2

# ═══════════════════════════════════════════════════════════════════════════════
# PRE-FLIGHT
# ═══════════════════════════════════════════════════════════════════════════════
hr
printf "\n  ${DIM}PRE-FLIGHT${RST}\n\n"
sleep 0.1

# venv
if [[ ! -f "$VENV" ]]; then
    step "$CROSS" "venv" "${R}not found${RST}  →  python -m venv sandbox && pip install -r requirements.txt"
    printf "\n"
    exit 1
fi
source "$VENV"
PYTHON_VER="$(python3 --version 2>&1)"
step "$TICK" "venv" "${DIM}sandbox/  ${PYTHON_VER}${RST}"
sleep 0.1

# Ollama binary
if ! command -v ollama &>/dev/null; then
    step "$CROSS" "ollama" "${R}not installed${RST}  →  brew install ollama"
    printf "\n"
    exit 1
fi
OLLAMA_VER="$(ollama --version 2>/dev/null | head -1 || echo 'unknown version')"
step "$TICK" "ollama" "${DIM}${OLLAMA_VER}${RST}"
sleep 0.1

# Log dirs
step "$TICK" "logs/" "${DIM}runtime.log  app.log  uvicorn.log  ollama.log${RST}"
printf "\n"

# ═══════════════════════════════════════════════════════════════════════════════
# SERVICES
# ═══════════════════════════════════════════════════════════════════════════════
hr
printf "\n  ${DIM}SERVICES${RST}\n\n"
sleep 0.1

# ── Ollama ────────────────────────────────────────────────────────────────────
OLLAMA_ALREADY_RUNNING=false
if curl -s --max-time 1 http://localhost:11434 >/dev/null 2>&1; then
    OLLAMA_ALREADY_RUNNING=true
    step "$TICK" "ollama" "${G}already running${RST}  ${DIM}http://localhost:11434${RST}"
else
    OLLAMA_KEEP_ALIVE=24h ollama serve >>"$SCRIPT_DIR/logs/ollama.log" 2>&1 &
    OLLAMA_PID=$!

    if wait_and_spin "Starting Ollama" "http://localhost:11434" 30; then
        step "$TICK" "ollama" "${G}ready${RST}  ${DIM}http://localhost:11434  PID ${OLLAMA_PID}${RST}"
    else
        step "$WARN" "ollama" "${Y}slow to start${RST}  ${DIM}check logs/ollama.log${RST}"
    fi
fi
sleep 0.1

# ── Pre-warm: fire model load into compute memory NOW, in parallel with
# uvicorn startup. FastAPI takes ~18s to start (embedding model import).
# Starting the Ollama inference simultaneously means those 18s aren't wasted
# waiting before the model even begins to load from disk.
# ─────────────────────────────────────────────────────────────────────────────
_LLM_MODEL="$(python3 -c \
  "import yaml; print(yaml.safe_load(open('src/resumate/config/model_config.yaml'))['llm']['model_name'])" \
  2>/dev/null || echo "qwen2.5:1.5b")"

_model_in_ps="$(curl -sf http://localhost:11434/api/ps 2>/dev/null \
  | python3 -c "import sys,json; ms=json.load(sys.stdin).get('models',[]); print(any('${_LLM_MODEL}' in m.get('name','') for m in ms))" \
  2>/dev/null || echo "False")"

if [[ "$_model_in_ps" != "True" ]]; then
  curl -sf -X POST http://localhost:11434/api/generate \
    -H "Content-Type: application/json" \
    -d "{\"model\":\"${_LLM_MODEL}\",\"prompt\":\"hi\",\"stream\":false}" \
    >/dev/null 2>&1 &
  step "$DOT" "model" "${DIM}${_LLM_MODEL}${RST}  ·  loading into compute (background)…"
else
  step "$TICK" "model" "${DIM}${_LLM_MODEL}${RST}  ·  already in compute memory"
fi
printf "\n"

# ── FastAPI ───────────────────────────────────────────────────────────────────
(
    export TOKENIZERS_PARALLELISM=false
    export USE_TF=0
    export USE_JAX=0
    export PYTHONPATH="$SCRIPT_DIR/src${PYTHONPATH:+:$PYTHONPATH}"
    exec uvicorn resumate.app:app --reload --reload-dir src --port 8000
) >>"$SCRIPT_DIR/logs/uvicorn.log" 2>&1 &
UVICORN_PID=$!

if wait_and_spin "Starting API server" "http://localhost:8000/health" 20; then
    step "$TICK" "api" "${G}ready${RST}  ${DIM}http://localhost:8000  PID ${UVICORN_PID}${RST}"
else
    step "$CROSS" "api" "${R}failed to start${RST}  ->  tail -f logs/uvicorn.log"
    printf "\n"
    exit 1
fi
sleep 0.1

# ── Model warm-up ─────────────────────────────────────────────────────────────
MODEL_LABEL="$(json_field http://localhost:8000/health model)"
COMPUTE="$(json_field http://localhost:8000/health compute)"

if [[ "$COMPUTE" == "not_loaded" ]]; then
    step "$DOT" "model" "${DIM}${MODEL_LABEL}${RST}  ·  loading in background  ·  ${DIM}UI will show ready state when done${RST}"
else
    step "$TICK" "model" "${DIM}${MODEL_LABEL}${RST}  ·  already loaded  ·  compute: ${COMPUTE}"
fi

case "$COMPUTE" in
    cpu) printf "  ${Y}  ⚠ CPU-only — Metal GPU offload failed. Free RAM and restart Ollama for faster inference.${RST}\n" ;;
esac
printf "\n"

# ═══════════════════════════════════════════════════════════════════════════════
# STATUS BOARD
# ═══════════════════════════════════════════════════════════════════════════════
hr
printf "\n  ${DIM}RUNNING${RST}\n\n"

# Header
printf "  ${BOLD}${DIM}%-20s  %-33s  %-10s  %s${RST}\n" "SERVICE" "URL" "PID" "LOG"
printf "  ${DIM}%-20s  %-33s  %-10s  %s${RST}\n"        "──────────────────" "───────────────────────────────" "──────────" "────────────────────"

# Rows
printf "  ${G}${BOLD}ollama${RST}               ${C}http://localhost:11434${RST}            %-10s  ${DIM}logs/ollama.log${RST}\n"  "$( [[ -n "$OLLAMA_PID" ]] && echo "$OLLAMA_PID" || echo "(external)" )"
printf "  ${G}${BOLD}api${RST}  ${DIM}(FastAPI)${RST}     ${C}http://localhost:8000${RST}             ${DIM}%-10s${RST}  ${DIM}logs/uvicorn.log${RST}\n" "$UVICORN_PID"

printf "\n"
hr
printf "\n"
printf "  ${C}→${RST}  Opening ${W}http://localhost:8000${RST} in browser\n"
printf "\n"

# ── Open browser ──────────────────────────────────────────────────────────────
sleep 0.4
open "http://localhost:8000" 2>/dev/null || true

# ═══════════════════════════════════════════════════════════════════════════════
# LIVE LOG MONITOR — tails all logs, labels & colorizes, keeps process alive
# ═══════════════════════════════════════════════════════════════════════════════
hr
printf "\n  ${DIM}LIVE LOGS${RST}  ${DIM}(errors, warnings, requests — Ctrl+C to stop)${RST}\n\n"

# Ensure log files exist so tail doesn't error
touch "$SCRIPT_DIR/logs/app.log" \
      "$SCRIPT_DIR/logs/uvicorn.log" \
      "$SCRIPT_DIR/logs/ollama.log"

# Helper: label & colorize a log stream
# Usage: label_stream <tag> <color> < stream
label_stream() {
  local tag=$1 color=$2
  while IFS= read -r line; do
    # Skip empty lines
    [[ -z "${line// /}" ]] && continue

    # Pick icon based on severity
    local icon="$DOT"
    if [[ "$line" == *ERROR* || "$line" == *Error* || "$line" == *error* || "$line" == *Traceback* ]]; then
      icon="$CROSS"
    elif [[ "$line" == *WARNING* || "$line" == *Warning* || "$line" == *warn* ]]; then
      icon="$WARN"
    fi

    # Timestamp
    local ts
    ts="$(date '+%H:%M:%S')"

    printf "  %s ${DIM}%s${RST}  ${color}${BOLD}%-8s${RST}  %s\n" "$icon" "$ts" "$tag" "$line"
  done
}

# Tail all logs in parallel, each piped through the labeler.
# We filter to only show interesting lines (errors, warnings, HTTP requests, task completions).
(
  # App log — show errors, warnings, and task completions
  tail -n 0 -f "$SCRIPT_DIR/logs/app.log" 2>/dev/null \
    | grep --line-buffered -iE 'error|warning|exception|traceback|task complete|generation|login|logout|model' \
    | label_stream "app" "$G" &

  # Uvicorn log — show HTTP requests (status codes) and errors
  tail -n 0 -f "$SCRIPT_DIR/logs/uvicorn.log" 2>/dev/null \
    | grep --line-buffered -iE 'error|warning|"(POST|GET|DELETE) |[45][0-9]{2}' \
    | label_stream "http" "$C" &

  # Ollama log — show errors, model load events
  tail -n 0 -f "$SCRIPT_DIR/logs/ollama.log" 2>/dev/null \
    | grep --line-buffered -iE 'error|warning|load|unload|metal|gpu|oom|memory' \
    | label_stream "ollama" "$Y" &

  # Keep the subshell alive — wait for any child
  wait
) &
TAIL_PID=$!

# ── Heartbeat — show the app is alive even when no logs are flowing ──────────
(
  # Wait a few seconds after startup for logs to settle, then show periodic pulse
  sleep 10
  while true; do
    # Check services are still running
    api_ok="$(curl -sf --max-time 2 http://localhost:8000/health >/dev/null 2>&1 && echo "1" || echo "0")"
    ollama_ok="$(curl -sf --max-time 2 http://localhost:11434 >/dev/null 2>&1 && echo "1" || echo "0")"

    if [[ "$api_ok" == "0" ]]; then
      printf "\r  ${CROSS} ${DIM}%s${RST}  ${R}${BOLD}%-8s${RST}  API server is down — check logs/uvicorn.log\n" "$(date '+%H:%M:%S')" "health"
    fi
    if [[ "$ollama_ok" == "0" ]]; then
      printf "\r  ${CROSS} ${DIM}%s${RST}  ${R}${BOLD}%-8s${RST}  Ollama is down — check logs/ollama.log\n" "$(date '+%H:%M:%S')" "health"
    fi

    sleep 30
  done
) &
HEARTBEAT_PID=$!

# ── Override cleanup to also kill the tail + heartbeat ────────────────────────
cleanup() {
    # Kill the tail watcher and heartbeat first (suppress errors)
    kill "$TAIL_PID" 2>/dev/null; wait "$TAIL_PID" 2>/dev/null
    kill "$HEARTBEAT_PID" 2>/dev/null; wait "$HEARTBEAT_PID" 2>/dev/null

    printf "\n\n"
    hr
    printf "\n  ${Y}${BOLD}Shutting down${RST}\n\n"
    if [[ -n "$UVICORN_PID" ]] && kill -0 "$UVICORN_PID" 2>/dev/null; then
        kill "$UVICORN_PID" 2>/dev/null
        step "$TICK" "api" "stopped"
    fi
    if [[ -n "$OLLAMA_PID" ]] && kill -0 "$OLLAMA_PID" 2>/dev/null; then
        kill "$OLLAMA_PID" 2>/dev/null
        step "$TICK" "ollama" "stopped"
    fi
    printf "\n  ${DIM}Goodbye.${RST}\n\n"
    exit 0
}
trap cleanup SIGINT SIGTERM

# ── Block forever — the trap handles Ctrl+C ───────────────────────────────────
# We can't use `wait` alone because background processes (tail, heartbeat) would
# keep it from exiting cleanly. Instead, sleep in a loop — the trap interrupts it.
while true; do
    sleep 86400 &
    wait $! 2>/dev/null || break
done
