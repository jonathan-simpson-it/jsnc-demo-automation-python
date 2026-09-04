#!/bin/bash
set -e

# ─────────────────────────────────────────────────────────────
# PE AI Engineering Portfolio -- App Launcher
#
# Starts FastAPI (API server) on port 8000
# and Next.js (frontend) on port 3000.
# ─────────────────────────────────────────────────────────────

# Resolve this script's own directory so run.sh works from anywhere
# (relative paths below depend on cwd = project root)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

print_banner() {
    echo -e "${CYAN}"
    echo "╔══════════════════════════════════════════════════╗"
    echo "║     PE AI Engineering Portfolio                  ║"
    echo "║     RAG + Multi-Agent System for Private Equity  ║"
    echo "╚══════════════════════════════════════════════════╝"
    echo -e "${NC}"
}

# ─── Resolve a working Python interpreter ──────────────────
# The bare `python`/`uvicorn` on PATH may point at an environment whose
# deps are broken (e.g. a macOS Framework Python with a patched
# openai/httpx2), which silently kills every LLM call. Probe candidates
# in priority order and pick the first that can import the project stack.
resolve_python() {
    local candidates=() c
    [ -n "$VIRTUAL_ENV" ] && candidates+=("$VIRTUAL_ENV/bin/python")
    [ -n "$CONDA_PREFIX" ] && candidates+=("$CONDA_PREFIX/bin/python")
    if command -v conda >/dev/null 2>&1; then
        # conda at <base>/bin/conda -> <base>/bin/python
        candidates+=("$(dirname "$(dirname "$(command -v conda)")")/bin/python")
    fi
    candidates+=(python python3)

    for c in "${candidates[@]}"; do
        if [[ "$c" == /* ]]; then
            [ -x "$c" ] || continue
        else
            command -v "$c" >/dev/null 2>&1 || continue
        fi
        if "$c" -c "import uvicorn, fastapi, langchain_deepseek, chromadb" >/dev/null 2>&1; then
            PY="$c"
            return 0
        fi
    done
    return 1
}

# ─── Check .env ──────────────────────────────────────────────
check_env() {
    if [ ! -f .env ]; then
        echo -e "${YELLOW}WARNING: No .env file found. Creating from .env.example...${NC}"
        cp .env.example .env
        echo -e "${YELLOW}   API keys are optional: users can add their own in the frontend.${NC}"
    fi

    source .env

    # Hermetic key state: the backend's key must come ONLY from .env. A
    # leftover DEEPSEEK_API_KEY exported in the shell would silently flip
    # the server into server-key mode and make behavior differ from a
    # clean terminal / CI run (keyless BYOK mode is the tested default).
    DEEPSEEK_API_KEY="$(grep -E '^[[:space:]]*DEEPSEEK_API_KEY=' .env 2>/dev/null | tail -1 | sed -E 's/^[^=]*=[[:space:]]*//' | tr -d '\r' || true)"
    case "$DEEPSEEK_API_KEY" in
        ""|"your-deepseek-api-key-here") unset DEEPSEEK_API_KEY ;;
    esac
    export DEEPSEEK_API_KEY

    if [ -z "${DEEPSEEK_API_KEY:-}" ]; then
        echo -e "${YELLOW}WARNING: DEEPSEEK_API_KEY is not set in .env${NC}"
        echo -e "${YELLOW}   Users will be asked to add their key in the frontend instead.${NC}"
        echo -e "${YELLOW}   Get your key at https://platform.deepseek.com${NC}"
    else
        echo -e "${GREEN}OK: DEEPSEEK_API_KEY is configured (server fallback)${NC}"
    fi
}

# ─── Ingest documents ───────────────────────────────────────
ingest_docs() {
    echo -e "\n${CYAN}Ingesting documents into vector store...${NC}"
    "$PY" scripts/ingest.py
}

# ─── Process helpers ────────────────────────────────────────
# Recursively kill a process and all of its descendants.
# uvicorn --reload and `npx next dev` spawn child processes; killing
# only the parent would orphan them and leave the port occupied.
kill_tree() {
    local pid="$1"
    for child in $(pgrep -P "$pid" 2>/dev/null || true); do
        kill_tree "$child" || true
    done
    kill -TERM "$pid" 2>/dev/null || true
}

# Kill whatever is holding a port and wait until it is actually free.
free_port() {
    local port="$1"
    local pid tries=0
    # Match only processes LISTENING on the port. Plain `lsof -ti:$port` also
    # matches client-side connections (e.g. a browser tab that once visited
    # localhost:$port and still holds CLOSE_WAIT sockets) and would kill the
    # browser helper instead of the server.
    while pid=$(lsof -nP -iTCP:"$port" -sTCP:LISTEN -t 2>/dev/null); do
        for p in $pid; do
            echo -e "${YELLOW}Port $port still in use — stopping leftover PID $p${NC}"
            kill_tree "$p"
        done
        tries=$((tries + 1))
        if [ "$tries" -ge 15 ]; then
            echo -e "${RED}ERROR: Port $port is still in use. Is another instance running?${NC}"
            return 1
        fi
        sleep 1
    done
}

# Single-instance lock: refuse to run while another instance is active.
# Two concurrent run.sh executions race for the same ports and produce
# confusing "Address already in use" failures — this prevents that.
acquire_lock() {
    if ! mkdir "$LOCK_DIR" 2>/dev/null; then
        local other
        other=$(cat "$LOCK_DIR/pid" 2>/dev/null || true)
        if [ -n "$other" ] && kill -0 "$other" 2>/dev/null; then
            echo -e "${RED}ERROR: Another instance of run.sh is already running (PID $other).${NC}"
            echo -e "${RED}   Wait for it to finish, or stop it with: kill $other${NC}"
            exit 1
        fi
        rm -rf "$LOCK_DIR"
        mkdir "$LOCK_DIR" 2>/dev/null || {
            echo -e "${RED}ERROR: Could not acquire lock directory.${NC}"
            exit 1
        }
    fi
    echo $$ > "$LOCK_DIR/pid"
    # Release the lock on every normal exit path
    trap 'rm -rf "$LOCK_DIR"' EXIT
}

# ─── Smart-skip helpers ─────────────────────────────────────
# Dependency installs and ingestion only re-run when their inputs
# changed since the last successful run, so restarts are fast.
STAMP_DIR="$SCRIPT_DIR/.run-stamps"

hash_of() {
    cat "$@" 2>/dev/null | shasum -a 256 | awk '{print $1}'
}

# stamp_matches <name> <files...> -> 0 when inputs unchanged
stamp_matches() {
    local name="$1"; shift
    [ -f "$STAMP_DIR/$name" ] || return 1
    [ "$(cat "$STAMP_DIR/$name" 2>/dev/null)" = "$(hash_of "$@")" ]
}

write_stamp() {
    local name="$1"; shift
    mkdir -p "$STAMP_DIR"
    hash_of "$@" > "$STAMP_DIR/$name"
}

# ─── Parse arguments ────────────────────────────────────────
API_PORT="${API_PORT:-8000}"
FRONTEND_PORT="${FRONTEND_PORT:-3000}"
SKIP_INSTALL=false
SKIP_INGEST=false
FORCE_INSTALL=false
FORCE_INGEST=false
API_ONLY=false

for arg in "$@"; do
    case $arg in
        --skip-install)       SKIP_INSTALL=true ;;
        --skip-ingest)        SKIP_INGEST=true ;;
        --force-install)      FORCE_INSTALL=true ;;
        --force-ingest)       FORCE_INGEST=true ;;
        --api-only)           API_ONLY=true ;;
        --api-port=*)         API_PORT="${arg#*=}" ;;
        --frontend-port=*)    FRONTEND_PORT="${arg#*=}" ;;
        --help|-h)
            echo "Usage: ./run.sh [OPTIONS]"
            echo ""
            echo "Starts FastAPI (port 8000) and Next.js (port 3000)."
            echo ""
            echo "Install/ingest steps are skipped automatically when"
            echo "nothing changed since the last run (for fast restarts)."
            echo ""
            echo "Options:"
            echo "  --skip-install        Skip pip + npm install steps"
            echo "  --skip-ingest         Skip document ingestion step"
            echo "  --force-install       Re-run pip + npm install"
            echo "  --force-ingest        Re-run document ingestion"
            echo "  --api-only            Start only the FastAPI backend"
            echo "  --api-port=PORT       FastAPI port (default: 8000)"
            echo "  --frontend-port=PORT  Next.js port (default: 3000)"
            echo "  -h, --help            Show this help message"
            exit 0
            ;;
        *)
            echo -e "${RED}Unknown option: $arg${NC}"
            echo "Run ./run.sh --help for usage"
            exit 1
            ;;
    esac
done

# Frontend lives at ../nextjs/frontend in the combined dev workspace; when this
# directory is the standalone Python repo (no sibling), run API-only by default.
if [ -d "$(cd "$(dirname "$0")/.." && pwd)/nextjs/frontend" ]; then
    FE_DIR="$(cd "$(dirname "$0")/../nextjs" && pwd)/frontend"
else
    FE_DIR=""
    API_ONLY=true
    echo -e "${YELLOW}No ../nextjs/frontend found — starting API only.${NC}"
    echo -e "${YELLOW}   Run the Next.js app from its own repo (cd frontend && npm run dev).${NC}"
fi

LOCK_DIR="$SCRIPT_DIR/.run.lock.d"

# ─── Main ───────────────────────────────────────────────────
print_banner
acquire_lock

cleanup() {
    local code="${1:-0}"
    echo -e "\n${YELLOW}Shutting down...${NC}"
    local pids p
    pids=$(jobs -p)
    for p in $pids; do
        kill_tree "$p" || true
    done
    sleep 1
    # Mop up any orphaned children (uvicorn --reload worker, next-server)
    for p in $(lsof -nP -iTCP:"$API_PORT" -sTCP:LISTEN -t 2>/dev/null; lsof -nP -iTCP:"$FRONTEND_PORT" -sTCP:LISTEN -t 2>/dev/null || true); do
        kill -TERM "$p" 2>/dev/null || true
    done
    rm -rf "$LOCK_DIR"
    wait 2>/dev/null || true
    echo -e "${GREEN}OK: All services stopped${NC}"
    exit "$code"
}
trap cleanup INT TERM HUP

# Kill leftover services from a previous run (they may hold the ports
# after a wrapper shell died without running its cleanup)
pkill -TERM -f "uvicorn src.api.main" 2>/dev/null || true
free_port "$API_PORT"
if [ "$API_ONLY" = false ] && [ -n "$FE_DIR" ]; then
    free_port "$FRONTEND_PORT"
fi

# Step 1: Environment
echo -e "\n${CYAN}Step 1/4: Checking environment${NC}"
check_env
if ! resolve_python; then
    echo -e "${RED}ERROR: No Python interpreter with the project dependencies found.${NC}"
    echo -e "${RED}       Activate your environment (conda activate / source venv) and run: pip install -e \".[dev]\"${NC}"
    exit 1
fi
echo -e "${GREEN}OK: Using Python: $PY${NC}"

# Step 2: Install (skipped when unchanged since last run)
if [ "$SKIP_INSTALL" = true ]; then
    echo -e "\n${YELLOW}Step 2/4: Skipping install (--skip-install)${NC}"
else
    PY_STALE=false
    FE_STALE=false
    if [ "$FORCE_INSTALL" = true ] || ! stamp_matches py pyproject.toml; then
        PY_STALE=true
    fi
    if [ -n "$FE_DIR" ] && { [ "$FORCE_INSTALL" = true ] || [ ! -d "$FE_DIR/node_modules" ] || ! stamp_matches fe "$FE_DIR/package.json" "$FE_DIR/package-lock.json"; }; then
        FE_STALE=true
    fi

    if [ "$PY_STALE" = true ] || [ "$FE_STALE" = true ]; then
        echo -e "\n${CYAN}Step 2/4: Installing dependencies${NC}"
        if [ "$PY_STALE" = true ]; then
            echo -e "\n${CYAN}Installing Python dependencies...${NC}"
            "$PY" -m pip install -e ".[dev]" -q 2>/dev/null
            echo -e "${GREEN}OK: Python dependencies installed${NC}"
            write_stamp py pyproject.toml
        fi
        if [ "$FE_STALE" = true ]; then
            echo -e "\n${CYAN}Installing frontend dependencies...${NC}"
            (cd "$FE_DIR" && npm install --silent 2>/dev/null)
            echo -e "${GREEN}OK: Frontend dependencies installed${NC}"
            write_stamp fe "$FE_DIR/package.json" "$FE_DIR/package-lock.json"
        fi
    else
        echo -e "\n${YELLOW}Step 2/4: Dependencies unchanged — skipping install${NC}"
    fi
fi

# Step 3: Ingest (skipped when sample docs unchanged since last run)
if [ "$SKIP_INGEST" = true ]; then
    echo -e "\n${YELLOW}Step 3/4: Skipping ingestion (--skip-ingest)${NC}"
elif [ "$FORCE_INGEST" = true ] || [ ! -d data/chroma ] || ! stamp_matches ingest $(find data/sample -type f 2>/dev/null | sort); then
    echo -e "\n${CYAN}Step 3/4: Ingesting documents${NC}"
    ingest_docs
    write_stamp ingest $(find data/sample -type f 2>/dev/null | sort)
else
    echo -e "\n${YELLOW}Step 3/4: Documents unchanged — skipping ingestion${NC}"
fi

# Step 4: Launch
echo -e "\n${CYAN}Step 4/4: Starting services${NC}"
echo ""

# Re-free the ports right before launching. A long install/ingest step
# gives other (stray) instances time to grab the ports in between.
free_port "$API_PORT"
if [ "$API_ONLY" = false ] && [ -n "$FE_DIR" ]; then
    free_port "$FRONTEND_PORT"
fi

# Start FastAPI backend
echo -e "${GREEN}FastAPI starting on http://localhost:${API_PORT}${NC}"
echo -e "${CYAN}   API docs: http://localhost:${API_PORT}/docs${NC}"
"$PY" -m uvicorn src.api.main:app --host 0.0.0.0 --port "$API_PORT" --reload &
API_PID=$!

# Start Next.js frontend (unless --api-only or no sibling frontend found)
if [ "$API_ONLY" = false ] && [ -n "$FE_DIR" ]; then
    echo -e "${GREEN}Next.js starting on http://localhost:${FRONTEND_PORT}${NC}"
    echo -e "${CYAN}   App:       http://localhost:${FRONTEND_PORT}${NC}"
    (cd "$FE_DIR" && exec npx next dev --port "$FRONTEND_PORT") &
    FRONTEND_PID=$!
fi

# Wait until both services are actually listening. If a service exits
# before binding, its port is blocked or it failed — report it clearly.
backend_up=false
frontend_up=false
for _ in $(seq 1 60); do
    if [ "$backend_up" = false ] && lsof -nP -iTCP:"$API_PORT" -sTCP:LISTEN -t >/dev/null 2>&1; then
        backend_up=true
    fi
    if [ "$API_ONLY" = true ] || [ -z "$FE_DIR" ]; then
        frontend_up=true
    elif [ "$frontend_up" = false ] && lsof -nP -iTCP:"$FRONTEND_PORT" -sTCP:LISTEN -t >/dev/null 2>&1; then
        frontend_up=true
    fi
    if [ "$backend_up" = true ] && [ "$frontend_up" = true ]; then
        break
    fi
    if ! kill -0 "$API_PID" 2>/dev/null && [ "$backend_up" = false ]; then
        echo -e "${RED}ERROR: Backend exited before listening on port $API_PORT (see output above).${NC}"
        echo -e "${RED}       Another process may hold the port — try: ./run.sh again${NC}"
        cleanup 1
    fi
    if [ "$API_ONLY" = false ] && [ -n "$FE_DIR" ] && ! kill -0 "$FRONTEND_PID" 2>/dev/null && [ "$frontend_up" = false ]; then
        echo -e "${RED}ERROR: Frontend exited before listening on port $FRONTEND_PORT (see output above).${NC}"
        echo -e "${RED}       Another process may hold the port — try: ./run.sh again${NC}"
        cleanup 1
    fi
    sleep 1
done

if [ "$backend_up" = false ] || [ "$frontend_up" = false ]; then
    echo -e "${RED}ERROR: Services did not come up on ports $API_PORT / $FRONTEND_PORT within 60s.${NC}"
    echo -e "${RED}       Another process may hold the ports — run ./run.sh again to force-free them.${NC}"
    cleanup 1
fi

echo ""
echo -e "${GREEN}All services running.${NC}"
[ "$API_ONLY" = false ] && echo -e "${GREEN}   Backend:  PID $API_PID  |  Frontend: PID $FRONTEND_PID${NC}"
[ "$API_ONLY" = true ] && echo -e "${GREEN}   Backend:  PID $API_PID${NC}"
echo -e "${YELLOW}Press Ctrl+C to stop${NC}\n"

wait
