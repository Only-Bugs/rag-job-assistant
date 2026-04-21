#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"
mkdir -p logs

# ── Colours ─────────────────────────────────────────────────────────────
RST=$'\e[0m'; BOLD=$'\e[1m'; DIM=$'\e[2m'
G=$'\e[32m'; Y=$'\e[33m'; R=$'\e[31m'
C=$'\e[36m'; M=$'\e[35m'

TICK="${G}✓${RST}"
CROSS="${R}✗${RST}"
WARN="${Y}⚠${RST}"
DOT="${C}·${RST}"

VENV="$SCRIPT_DIR/sandbox/bin/activate"

# ── Helpers ─────────────────────────────────────────────────────────────
hr(){ printf "  ${DIM}%s${RST}\n" "────────────────────────────────────────────"; }
step(){ printf "  %s  ${BOLD}%-14s${RST} %s\n" "$1" "$2" "$3"; }

wait_and_spin(){
    local msg=$1 url=$2 timeout=${3:-30}
    local spin=('⣾' '⣽' '⣻' '⢿' '⡿' '⣟' '⣯' '⣷')
    local i=0 end=$((SECONDS+timeout))

    while ! curl -sf --max-time 1 "$url" >/dev/null 2>&1; do
        printf "\r  ${C}${spin[$i]}${RST} %s" "$msg"
        i=$(( (i+1)%8 ))
        (( SECONDS >= end )) && return 1
        sleep 0.1
    done
    printf "\r%60s\r" ""
}

kill_port(){
    local port=$1
    local pids
    pids=$(lsof -ti tcp:"$port" 2>/dev/null || true)
    [[ -z "$pids" ]] && return
    kill -TERM $pids 2>/dev/null || true
    sleep 0.3
    pids=$(lsof -ti tcp:"$port" 2>/dev/null || true)
    [[ -n "$pids" ]] && kill -KILL $pids 2>/dev/null || true
}

kill_tree(){
    local pid=$1
    [[ -z "$pid" ]] && return
    local children
    children=$(pgrep -P "$pid" 2>/dev/null || true)
    for c in $children; do kill_tree "$c"; done
    kill -TERM "$pid" 2>/dev/null || true
}

# ── State ───────────────────────────────────────────────────────────────
OLLAMA_PID=""
UVICORN_PID=""
TAIL_PID=""
WATCHDOG_PID=""
RAM_PID=""
VERBOSE=0

# ── Services ────────────────────────────────────────────────────────────
start_ollama(){
    if curl -s http://localhost:11434 >/dev/null 2>&1; then
        step "$TICK" "ollama" "already running"
        return
    fi

    ollama serve >>logs/ollama.log 2>&1 &
    OLLAMA_PID=$!

    wait_and_spin "Starting Ollama" "http://localhost:11434" 30 \
        && step "$TICK" "ollama" "ready" \
        || step "$WARN" "ollama" "slow start"
}

start_api(){
    kill_port 8000

    (
        export TOKENIZERS_PARALLELISM=false
        export USE_TF=0
        export USE_JAX=0
        export PYTHONPATH="$SCRIPT_DIR/src${PYTHONPATH:+:$PYTHONPATH}"

        # ✅ FIXED: removed setsid
        watchfiles \
            --filter python \
            --ignore-paths logs \
            -- \
            uvicorn resumate.app:app --host 0.0.0.0 --port 8000
    ) >>logs/uvicorn.log 2>&1 &

    UVICORN_PID=$!

    if wait_and_spin "Starting API" "http://localhost:8000/health" 20; then
        step "$TICK" "api" "ready"
    else
        step "$CROSS" "api" "failed"
        echo -e "\n${R}--- uvicorn.log ---${RST}"
        tail -n 40 logs/uvicorn.log
    fi
}

shutdown_api(){
    kill_port 8000
    [[ -n "$UVICORN_PID" ]] && kill_tree "$UVICORN_PID"
    step "$TICK" "api" "stopped"
}

shutdown_ollama(){
    [[ -n "$OLLAMA_PID" ]] && kill_tree "$OLLAMA_PID"
    step "$TICK" "ollama" "stopped"
}

# ── Model ───────────────────────────────────────────────────────────────
warm_model(){
    local model
    model="$(python3 -c \
      "import yaml;print(yaml.safe_load(open('src/resumate/config/model_config.yaml'))['llm']['model_name'])" \
      2>/dev/null || echo "qwen2.5:1.5b")"

    curl -sf -X POST http://localhost:11434/api/generate \
      -H "Content-Type: application/json" \
      -d "{\"model\":\"${model}\",\"prompt\":\"hi\",\"stream\":false}" \
      >/dev/null 2>&1 &

    step "$DOT" "model" "$model loading..."
}

watch_model(){
    local timeout=60 start=$SECONDS

    while true; do
        sleep 2

        curl -sf http://localhost:8000/health >/dev/null || continue

        ready=$(curl -sf http://localhost:8000/health 2>/dev/null \
            | python3 -c "import sys,json;print(json.load(sys.stdin).get('model_ready','false'))" \
            2>/dev/null || echo "false")

        if [[ "$ready" == "true" || "$ready" == "True" ]]; then
            step "$TICK" "model" "ready"
            return
        fi

        if (( SECONDS - start > timeout )); then
            step "$WARN" "model" "stuck → restarting ollama"
            shutdown_ollama
            start_ollama
            warm_model
            start=$SECONDS
        fi
    done
}

# ── RAM Guard ───────────────────────────────────────────────────────────
ram_guard(){
    local limit_mb=12000

    while true; do
        pid=$(pgrep -f "ollama serve" | head -1 || echo "")
        [[ -z "$pid" ]] && sleep 5 && continue

        used=$(ps -o rss= -p "$pid" 2>/dev/null || echo 0)
        used_mb=$((used / 1024))

        if (( used_mb > limit_mb )); then
            step "$WARN" "ollama" "RAM ${used_mb}MB → restarting"
            shutdown_ollama
            start_ollama
            warm_model
        fi

        sleep 5
    done
}

# ── Logs ────────────────────────────────────────────────────────────────
start_logs(){
    local pattern
    [[ $VERBOSE -eq 1 ]] && pattern='.' || pattern='ERROR|CRITICAL|FATAL|Traceback|Exception|\b5[0-9]{2}\b'

    (
        tail -n 0 -f logs/uvicorn.log 2>/dev/null | grep --line-buffered -iE "$pattern"
    ) &
    TAIL_PID=$!
}

# ── Cleanup ─────────────────────────────────────────────────────────────
cleanup(){
    echo
    hr
    echo -e "\n  ${Y}${BOLD}Shutting down${RST}\n"
    [[ -n "$TAIL_PID" ]] && kill_tree "$TAIL_PID"
    [[ -n "$WATCHDOG_PID" ]] && kill_tree "$WATCHDOG_PID"
    [[ -n "$RAM_PID" ]] && kill_tree "$RAM_PID"
    shutdown_api
    shutdown_ollama
    echo -e "\n  ${DIM}Goodbye.${RST}\n"
    exit 0
}
trap cleanup SIGINT SIGTERM

# ── Boot ────────────────────────────────────────────────────────────────
clear
echo -e "\n  ${M}${BOLD}ResuMate${RST} ${DIM}dev runner${RST}\n"

[[ -f "$VENV" ]] || { step "$CROSS" "venv" "missing"; exit 1; }
source "$VENV"
step "$TICK" "venv" "loaded"

command -v ollama >/dev/null || { step "$CROSS" "ollama" "missing"; exit 1; }
command -v watchfiles >/dev/null || { step "$CROSS" "watchfiles" "missing"; exit 1; }

start_ollama
start_api
warm_model

watch_model & WATCHDOG_PID=$!
ram_guard & RAM_PID=$!

touch logs/*.log 2>/dev/null || true
start_logs

echo -e "\n  ${BOLD}Controls:${RST} [q] quit  [r] restart  [v] verbose\n"

while read -rsn1 key; do
    case "$key" in
        q) cleanup ;;
        r)
            echo
            shutdown_api
            start_api
            ;;
        v)
            VERBOSE=$((1-VERBOSE))
            kill_tree "$TAIL_PID"
            start_logs
            ;;
    esac
done
