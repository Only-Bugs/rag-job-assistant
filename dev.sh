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
printf "  ${M}│${RST}   ${W}${BOLD}R J A${RST}   ${DIM}Resume & Job Application Assistant${RST}           ${M}│${RST}\n"
printf "  ${M}│${RST}   ${DIM}v0.1  ·  qwen2.5:1.5b  ·  FastAPI  ·  ChromaDB${RST}       ${M}│${RST}\n"
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

# ── FastAPI ───────────────────────────────────────────────────────────────────
(
    export TOKENIZERS_PARALLELISM=false
    exec uvicorn src.api.main:app --reload --port 8000
) >>"$SCRIPT_DIR/logs/uvicorn.log" 2>&1 &
UVICORN_PID=$!

if wait_and_spin "Starting API server" "http://localhost:8000/health" 20; then
    step "$TICK" "api" "${G}ready${RST}  ${DIM}http://localhost:8000  PID ${UVICORN_PID}${RST}"
else
    step "$CROSS" "api" "${R}failed to start${RST}  →  tail -f logs/uvicorn.log"
    printf "\n"
    exit 1
fi
sleep 0.1

# ── Model / compute ───────────────────────────────────────────────────────────
COMPUTE="$(json_field http://localhost:8000/health compute)"
MODEL_LABEL="$(json_field http://localhost:8000/health model)"

case "$COMPUTE" in
    metal)       COMPUTE_TAG="${G}Metal GPU${RST}" ;;
    cpu)         COMPUTE_TAG="${Y}CPU only  ⚠ slow inference — free RAM and restart Ollama${RST}" ;;
    not_loaded)  COMPUTE_TAG="${DIM}model not yet loaded into Ollama${RST}" ;;
    *)           COMPUTE_TAG="${DIM}${COMPUTE}${RST}" ;;
esac

step "$DOT" "model" "${DIM}${MODEL_LABEL}${RST}  ·  compute: ${COMPUTE_TAG}"
printf "\n"

# ═══════════════════════════════════════════════════════════════════════════════
# STATUS BOARD
# ═══════════════════════════════════════════════════════════════════════════════
hr
printf "\n  ${DIM}RUNNING${RST}\n\n"

OLLAMA_PID_COL="${DIM}(external)${RST}"
[[ -n "$OLLAMA_PID" ]] && OLLAMA_PID_COL="${DIM}${OLLAMA_PID}${RST}"

# Header
printf "  ${BOLD}${DIM}%-20s  %-33s  %-10s  %s${RST}\n" "SERVICE" "URL" "PID" "LOG"
printf "  ${DIM}%-20s  %-33s  %-10s  %s${RST}\n"        "──────────────────" "───────────────────────────────" "──────────" "────────────────────"

# Rows  (no %-Ns on colored strings — pad manually)
printf "  ${G}${BOLD}ollama${RST}               ${C}http://localhost:11434${RST}            %-10s  ${DIM}logs/ollama.log${RST}\n"  "$( [[ -n "$OLLAMA_PID" ]] && echo "$OLLAMA_PID" || echo "(external)" )"
printf "  ${G}${BOLD}api${RST}  ${DIM}(FastAPI)${RST}     ${C}http://localhost:8000${RST}             ${DIM}%-10s${RST}  ${DIM}logs/uvicorn.log${RST}\n" "$UVICORN_PID"

printf "\n"
printf "  ${DIM}%-20s  %s${RST}\n"  "logs/runtime.log"    "pipeline stage timings  (all [OK] rows)"
printf "  ${DIM}%-20s  %s${RST}\n"  "logs/app.log"        "rag / api Python logger"
printf "  ${DIM}%-20s  %s${RST}\n"  "logs/uvicorn.log"    "HTTP access log"
printf "  ${DIM}%-20s  %s${RST}\n"  "logs/ollama.log"     "Ollama server + model runner"

printf "\n"
hr
printf "\n"
printf "  ${C}→${RST}  Opening ${W}http://localhost:8000${RST} in browser\n"
printf "  ${DIM}   Press Ctrl+C to stop all services${RST}\n"
printf "\n"

# ── Open browser ──────────────────────────────────────────────────────────────
sleep 0.4
open "http://localhost:8000" 2>/dev/null || true

# ── Wait (keep services alive) ────────────────────────────────────────────────
wait
