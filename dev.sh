#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"
mkdir -p logs

# ── Colours ─────────────────────────────────────────────────────────────
RST=$'\e[0m'; BOLD=$'\e[1m'; DIM=$'\e[2m'
G=$'\e[32m'; Y=$'\e[33m'; R=$'\e[31m'
C=$'\e[36m'; M=$'\e[35m'; B=$'\e[34m'

TICK="${G}✓${RST}"
CROSS="${R}✗${RST}"
WARN="${Y}⚠${RST}"
DOT="${C}·${RST}"
ON="${G}●${RST}"
OFF="${DIM}○${RST}"

VENV="$SCRIPT_DIR/sandbox/bin/activate"
VERSION="$(git describe --tags --always 2>/dev/null || echo dev)"
DASHLOG="logs/.dashlog.buf"
DASH_LINES=12

# ── Helpers ─────────────────────────────────────────────────────────────
hr(){ printf "  ${DIM}%s${RST}\n" "──────────────────────────────────────────────────────────────"; }
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

# SIGTERM the tree, sleep grace, then SIGKILL anything still alive.
kill_tree_hard(){
    local pid=$1 grace=${2:-0.5}
    [[ -z "$pid" ]] && return
    kill_tree "$pid"
    sleep "$grace"
    local children
    children=$(pgrep -P "$pid" 2>/dev/null || true)
    for c in $children; do kill_tree_hard "$c" 0; done
    kill -KILL "$pid" 2>/dev/null || true
}

# ── State ───────────────────────────────────────────────────────────────
OLLAMA_PID=""
OLLAMA_OWNED=0   # 1 if we started it; 0 if we attached to an existing one
UVICORN_PID=""
TAIL_PID=""
WATCHDOG_PID=""
RAM_PID=""
MODEL_NAME=""

declare -A LOG_SRC=([errors]=1 [app]=1 [uvicorn]=0 [ollama]=0)

# ── Services ────────────────────────────────────────────────────────────
start_ollama(){
    if curl -s http://localhost:11434 >/dev/null 2>&1; then
        OLLAMA_OWNED=0
        step "$TICK" "ollama" "already running (attached)"
        return
    fi

    ollama serve >>logs/ollama.log 2>&1 &
    OLLAMA_PID=$!
    OLLAMA_OWNED=1

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

        watchfiles \
            --filter python \
            --ignore-paths logs \
            -- \
            uvicorn resumate.app:app --host 0.0.0.0 --port 8000
    ) >>logs/uvicorn.log 2>&1 &

    UVICORN_PID=$!

    if wait_and_spin "Starting API" "http://localhost:8000/health" 20; then
        step "$TICK" "api" "ready (http://localhost:8000)"
    else
        step "$CROSS" "api" "failed"
        echo -e "\n${R}--- uvicorn.log ---${RST}"
        tail -n 40 logs/uvicorn.log
    fi
}

shutdown_api(){
    kill_port 8000
    [[ -n "$UVICORN_PID" ]] && kill_tree_hard "$UVICORN_PID" 0.5
    pkill -f "watchfiles.*uvicorn.*resumate" 2>/dev/null || true
    pkill -f "uvicorn resumate.app" 2>/dev/null || true
    sleep 0.2
    if lsof -ti tcp:8000 >/dev/null 2>&1; then
        step "$WARN" "api" "port 8000 still held"
    else
        step "$TICK" "api" "stopped"
    fi
    UVICORN_PID=""
}

shutdown_ollama(){
    if (( OLLAMA_OWNED == 1 )); then
        [[ -n "$OLLAMA_PID" ]] && kill_tree_hard "$OLLAMA_PID" 0.5
        pkill -f "ollama serve" 2>/dev/null || true
        step "$TICK" "ollama" "stopped"
    else
        step "$DOT" "ollama" "left running (attached)"
    fi
    OLLAMA_PID=""
}

# ── Model ───────────────────────────────────────────────────────────────
detect_model(){
    MODEL_NAME="$(python3 -c \
      "import yaml;print(yaml.safe_load(open('src/resumate/config/model_config.yaml'))['llm']['model_name'])" \
      2>/dev/null || echo "qwen2.5:1.5b")"
}

warm_model(){
    detect_model
    curl -sf -X POST http://localhost:11434/api/generate \
      -H "Content-Type: application/json" \
      -d "{\"model\":\"${MODEL_NAME}\",\"prompt\":\"hi\",\"stream\":false}" \
      >/dev/null 2>&1 &
    step "$DOT" "model" "${MODEL_NAME} loading..."
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
            return
        fi

        if (( SECONDS - start > timeout )); then
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
            shutdown_ollama
            start_ollama
            warm_model
        fi
        sleep 5
    done
}

# ── Log tailer → buffer ─────────────────────────────────────────────────
build_log_pattern(){
    local parts=()
    [[ ${LOG_SRC[errors]}  -eq 1 ]] && parts+=('ERROR|CRITICAL|FATAL|Traceback|Exception|\b5[0-9]{2}\b')
    [[ ${LOG_SRC[app]}     -eq 1 ]] && parts+=('\bresumate\b|\[app\]')
    [[ ${LOG_SRC[uvicorn]} -eq 1 ]] && parts+=('\buvicorn\b|"(GET|POST|PUT|DELETE|PATCH) ')
    if [[ ${#parts[@]} -eq 0 ]]; then
        # Nothing selected — match nothing.
        echo '$^'
    else
        local IFS='|'; echo "${parts[*]}"
    fi
}

start_logs(){
    [[ -n "$TAIL_PID" ]] && kill_tree_hard "$TAIL_PID" 0.1
    TAIL_PID=""
    : > "$DASHLOG"

    local pattern; pattern="$(build_log_pattern)"
    local has_ollama=${LOG_SRC[ollama]}

    (
        # Keep DASHLOG bounded to last 400 lines.
        while true; do
            if [[ -f "$DASHLOG" ]] && (( $(wc -l < "$DASHLOG") > 400 )); then
                tail -n 200 "$DASHLOG" > "${DASHLOG}.tmp" && mv "${DASHLOG}.tmp" "$DASHLOG"
            fi
            sleep 3
        done
    ) &
    local TRIM_PID=$!

    (
        {
            tail -n 0 -f logs/uvicorn.log 2>/dev/null \
              | grep --line-buffered -iE "$pattern" \
              | sed -u 's/^/[uvi] /'
            if [[ $has_ollama -eq 1 ]]; then
                tail -n 0 -f logs/ollama.log 2>/dev/null \
                  | sed -u 's/^/[oll] /' &
            fi
            wait
        } >> "$DASHLOG"
    ) &
    TAIL_PID=$!

    # Stash trimmer PID alongside.
    disown $TRIM_PID 2>/dev/null || true
}

# ── Dashboard renderers ────────────────────────────────────────────────
_fetch_health(){
    curl -sf --max-time 1 http://localhost:8000/health 2>/dev/null \
      || echo '{}'
}

_fetch_ps(){
    curl -sf --max-time 1 http://localhost:11434/api/ps 2>/dev/null \
      || echo '{"models":[]}'
}

banner(){
    local ts; ts=$(date '+%Y-%m-%d %H:%M:%S')
    printf "  ${M}${BOLD}ResuMate${RST}  ${DIM}%s${RST}%*s${DIM}%s${RST}\n" \
      "$VERSION" $((40 - ${#VERSION})) "" "$ts"
    hr
}

service_table(){
    local health; health="$(_fetch_health)"
    local api_up=$(echo "$health" | python3 -c "import sys,json
try: d=json.load(sys.stdin); print('1' if d.get('status')=='ok' else '0')
except: print('0')" 2>/dev/null)
    local model; model=$(echo "$health" | python3 -c "import sys,json
try: print(json.load(sys.stdin).get('model',''))
except: print('')" 2>/dev/null)
    local compute; compute=$(echo "$health" | python3 -c "import sys,json
try: print(json.load(sys.stdin).get('compute',''))
except: print('')" 2>/dev/null)
    local model_ready; model_ready=$(echo "$health" | python3 -c "import sys,json
try: print('1' if json.load(sys.stdin).get('model_ready') else '0')
except: print('0')" 2>/dev/null)

    local oll_up="0"
    curl -sf --max-time 1 http://localhost:11434 >/dev/null 2>&1 && oll_up="1"

    local oll_pid="${OLLAMA_PID:-—}"
    [[ "$OLLAMA_OWNED" -eq 0 ]] && oll_pid="$(pgrep -f 'ollama serve' | head -1 || echo —)"
    local uv_pid="${UVICORN_PID:-—}"

    printf "  ${BOLD}%-9s %-24s %-8s %s${RST}\n" "SERVICE" "URL" "PID" "STATUS"
    printf "  %-9s %-24s %-8s %s\n" "ollama"  "localhost:11434"       "$oll_pid" "$([[ $oll_up -eq 1 ]] && echo "$ON ready" || echo "$OFF down")"
    printf "  %-9s %-24s %-8s %s\n" "uvicorn" "localhost:8000"        "$uv_pid"  "$([[ $api_up -eq 1 ]] && echo "$ON ready" || echo "$OFF down")"
    printf "  %-9s %-24s %-8s %s\n" "model"   "${model:-—} (${compute:-—})" "—" "$([[ $model_ready -eq 1 ]] && echo "$ON loaded" || echo "$OFF loading")"
}

resource_table(){
    local ps_json; ps_json="$(_fetch_ps)"
    local vram_gb; vram_gb=$(echo "$ps_json" | python3 -c "
import sys, json
try:
    d = json.load(sys.stdin)
    name = '${MODEL_NAME}'
    for m in d.get('models', []):
        if name in m.get('name',''):
            print(f\"{m.get('size_vram',0)/1e9:.1f}\"); break
    else:
        print('—')
except: print('—')
" 2>/dev/null)

    local oll_pid="${OLLAMA_PID:-}"
    [[ "$OLLAMA_OWNED" -eq 0 ]] && oll_pid="$(pgrep -f 'ollama serve' | head -1 || echo '')"

    local oll_stats uv_stats
    if [[ -n "$oll_pid" ]]; then
        oll_stats=$(ps -o %cpu=,rss= -p "$oll_pid" 2>/dev/null | awk '{printf "%5.1f %6.0fMB", $1, $2/1024}')
    else
        oll_stats="  —         —"
    fi
    if [[ -n "$UVICORN_PID" ]]; then
        uv_stats=$(ps -o %cpu=,rss= -p "$UVICORN_PID" 2>/dev/null | awk '{printf "%5.1f %6.0fMB", $1, $2/1024}')
    else
        uv_stats="  —         —"
    fi

    printf "  ${BOLD}%-9s %-13s %-10s %s${RST}\n" "RESOURCES" "CPU%" "RSS" "VRAM"
    printf "  %-9s %s  %sGB\n" "ollama"  "$oll_stats" "$vram_gb"
    printf "  %-9s %s  —\n"    "uvicorn" "$uv_stats"
}

log_filter_line(){
    local lbl state
    printf "  ${BOLD}Log sources:${RST}  "
    for src in errors app uvicorn ollama; do
        if [[ ${LOG_SRC[$src]} -eq 1 ]]; then
            printf "${G}[x] %s${RST}   " "$src"
        else
            printf "${DIM}[ ] %s${RST}   " "$src"
        fi
    done
    printf "\n"
}

log_window(){
    printf "  ${DIM}— last %d log lines —${RST}\n" "$DASH_LINES"
    if [[ -f "$DASHLOG" ]]; then
        tail -n "$DASH_LINES" "$DASHLOG" 2>/dev/null \
          | sed 's/^/  /' \
          | cut -c1-$(( $(tput cols 2>/dev/null || echo 120) - 2 ))
    else
        printf "  ${DIM}(no logs yet)${RST}\n"
    fi
}

controls(){
    printf "\n  ${BOLD}[q]${RST} quit   ${BOLD}[r]${RST} restart API   ${BOLD}[l]${RST} configure logs   ${BOLD}[s]${RST} refresh\n"
}

redraw(){
    printf '\e[H\e[2J'
    banner
    service_table
    echo
    resource_table
    echo
    log_filter_line
    echo
    log_window
    controls
}

# ── Log config menu ────────────────────────────────────────────────────
config_logs_menu(){
    local sources=(errors app uvicorn ollama)
    local descs=(
        "ERROR|CRITICAL|FATAL|Traceback|Exception|5xx"
        "resumate logger lines"
        "access + server lines"
        "logs/ollama.log (raw)"
    )

    while true; do
        printf '\e[H\e[2J'
        banner
        printf "  ${BOLD}Configure log sources${RST}  ${DIM}— toggle with number, ENTER to apply, q to cancel${RST}\n\n"
        local i
        for i in "${!sources[@]}"; do
            local key="${sources[$i]}"
            local mark
            [[ ${LOG_SRC[$key]} -eq 1 ]] && mark="${G}[x]${RST}" || mark="${DIM}[ ]${RST}"
            printf "    %d. %s ${BOLD}%-9s${RST} ${DIM}%s${RST}\n" $((i+1)) "$mark" "$key" "${descs[$i]}"
        done
        printf "\n  > "

        local k
        IFS= read -rsn1 k || return
        case "$k" in
            1|2|3|4)
                local idx=$((k-1))
                local key="${sources[$idx]}"
                LOG_SRC[$key]=$(( 1 - LOG_SRC[$key] ))
                ;;
            ""|$'\n'|$'\r')
                return
                ;;
            q|$'\e')
                return
                ;;
        esac
    done
}

# ── Cleanup ─────────────────────────────────────────────────────────────
cleanup(){
    printf '\e[H\e[2J'
    echo
    echo -e "  ${Y}${BOLD}Shutting down${RST}"
    hr
    [[ -n "$TAIL_PID" ]]     && kill_tree_hard "$TAIL_PID" 0.1
    [[ -n "$WATCHDOG_PID" ]] && kill_tree_hard "$WATCHDOG_PID" 0.1
    [[ -n "$RAM_PID" ]]      && kill_tree_hard "$RAM_PID" 0.1
    shutdown_api
    shutdown_ollama
    rm -f "$DASHLOG" "${DASHLOG}.tmp" 2>/dev/null || true
    echo
    echo -e "  ${DIM}Goodbye.${RST}"
    echo
    exit 0
}
trap cleanup SIGINT SIGTERM

# ── Boot ────────────────────────────────────────────────────────────────
clear
banner

[[ -f "$VENV" ]] || { step "$CROSS" "venv" "missing"; exit 1; }
# shellcheck disable=SC1090
source "$VENV"
step "$TICK" "venv" "loaded"

command -v ollama     >/dev/null || { step "$CROSS" "ollama"     "missing"; exit 1; }
command -v watchfiles >/dev/null || { step "$CROSS" "watchfiles" "missing"; exit 1; }

start_ollama
start_api
warm_model

watch_model & WATCHDOG_PID=$!
ram_guard   & RAM_PID=$!

touch logs/uvicorn.log logs/ollama.log 2>/dev/null || true
start_logs

# Give logs a moment to populate before first paint.
sleep 0.5
redraw

# ── Main loop ───────────────────────────────────────────────────────────
while true; do
    if IFS= read -rsn1 -t 2 key 2>/dev/null; then
        case "$key" in
            q) cleanup ;;
            r)
                printf '\e[H\e[2J'
                banner
                echo
                shutdown_api
                start_api
                redraw
                ;;
            l)
                config_logs_menu
                start_logs
                redraw
                ;;
            s) redraw ;;
        esac
    else
        redraw
    fi
done
