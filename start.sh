#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# start.sh  –  Start the full Artifex stack locally WITHOUT Docker
#
# Services started (in order):
#   1. NATS server          (brew service, already managed by launchd)
#   2. PostgreSQL           (brew service, already managed by launchd)
#   3. Temporal dev server  (background process)
#   4. FastAPI / Uvicorn    (background process)
#   5. Temporal worker      (background process)
#   6. Vite frontend        (background process)
#
# Usage:
#   ./start.sh          # start everything
#   ./start.sh --stop   # kill all background processes started by this script
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV="$REPO_ROOT/.venv/bin"
FRONTEND_DIR="$REPO_ROOT/artx"
LOG_DIR="$REPO_ROOT/logs"
PID_FILE="$REPO_ROOT/.artifex_pids"

# ── Colours ───────────────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
CYAN='\033[0;36m'; BOLD='\033[1m'; RESET='\033[0m'

info()    { echo -e "${CYAN}[artifex]${RESET} $*"; }
success() { echo -e "${GREEN}[artifex]${RESET} $*"; }
warn()    { echo -e "${YELLOW}[artifex]${RESET} $*"; }
error()   { echo -e "${RED}[artifex]${RESET} $*" >&2; }

# ── Stop mode ─────────────────────────────────────────────────────────────────
if [[ "${1:-}" == "--stop" ]]; then
  info "Stopping Artifex background processes..."
  if [[ -f "$PID_FILE" ]]; then
    while IFS= read -r pid; do
      if kill -0 "$pid" 2>/dev/null; then
        kill "$pid" && info "  killed PID $pid"
      fi
    done < "$PID_FILE"
    rm -f "$PID_FILE"
  else
    warn "No PID file found – nothing to stop."
  fi
  # Also kill by name as a safety net
  pkill -f "temporal server start-dev"  2>/dev/null || true
  pkill -f "uvicorn api.main:app"        2>/dev/null || true
  pkill -f "workflows.temporal_worker"   2>/dev/null || true
  pkill -f "vite"                        2>/dev/null || true
  success "Done."
  exit 0
fi

# ── Preflight checks ──────────────────────────────────────────────────────────
info "Running preflight checks..."

[[ -f "$REPO_ROOT/.env" ]] || { error ".env not found in $REPO_ROOT"; exit 1; }
[[ -x "$VENV/python" ]]    || { error ".venv not found – run: python3 -m venv .venv && .venv/bin/pip install -e '.[dev]'"; exit 1; }
command -v temporal   &>/dev/null || { error "'temporal' not found – run: brew install temporal"; exit 1; }
command -v node       &>/dev/null || { error "'node' not found – run: brew install node"; exit 1; }

mkdir -p "$LOG_DIR"
> "$PID_FILE"   # reset PID file

# ── Helper: wait for a TCP port ───────────────────────────────────────────────
wait_for_port() {
  local name="$1" port="$2" retries="${3:-30}"
  local i=0
  while ! nc -z 127.0.0.1 "$port" 2>/dev/null; do
    i=$((i+1))
    [[ $i -ge $retries ]] && { error "$name did not come up on port $port after ${retries}s"; exit 1; }
    sleep 1
  done
  success "$name is up on port $port"
}

# ── 1. NATS ───────────────────────────────────────────────────────────────────
info "Step 1/6 – NATS server..."
if nc -z 127.0.0.1 4222 2>/dev/null; then
  success "NATS already running on port 4222"
else
  warn "NATS not detected – starting via brew services..."
  brew services start nats-server
  wait_for_port "NATS" 4222 20
fi

# ── 2. PostgreSQL ─────────────────────────────────────────────────────────────
info "Step 2/6 – PostgreSQL..."
if nc -z 127.0.0.1 5432 2>/dev/null; then
  success "PostgreSQL already running on port 5432"
else
  warn "PostgreSQL not detected – starting via brew services..."
  brew services start postgresql@18 2>/dev/null || brew services start postgresql 2>/dev/null
  wait_for_port "PostgreSQL" 5432 20
fi

# Ensure the DB and user exist (idempotent)
info "  Ensuring database 'placements' and user 'artifex' exist..."
psql postgres -tc "SELECT 1 FROM pg_roles WHERE rolname='artifex'" 2>/dev/null \
  | grep -q 1 \
  || psql postgres -c "CREATE USER artifex WITH PASSWORD 'artifex123';" 2>/dev/null || true
psql postgres -tc "SELECT 1 FROM pg_database WHERE datname='placements'" 2>/dev/null \
  | grep -q 1 \
  || psql postgres -c "CREATE DATABASE placements OWNER artifex;" 2>/dev/null || true

# ── 3. Temporal dev server ────────────────────────────────────────────────────
info "Step 3/6 – Temporal dev server..."
if nc -z 127.0.0.1 7233 2>/dev/null; then
  success "Temporal already running on port 7233"
else
  temporal server start-dev \
    > "$LOG_DIR/temporal.log" 2>&1 &
  echo $! >> "$PID_FILE"
  wait_for_port "Temporal" 7233 40
fi

# ── 4. FastAPI / Uvicorn ──────────────────────────────────────────────────────
info "Step 4/6 – FastAPI (uvicorn)..."
if nc -z 127.0.0.1 8000 2>/dev/null; then
  warn "Port 8000 already in use – skipping uvicorn start"
else
  cd "$REPO_ROOT"
  "$VENV/python" -m uvicorn api.main:app --reload \
    > "$LOG_DIR/api.log" 2>&1 &
  echo $! >> "$PID_FILE"
  wait_for_port "FastAPI" 8000 30
fi

# ── 5. Temporal worker ────────────────────────────────────────────────────────
info "Step 5/6 – Temporal worker..."
cd "$REPO_ROOT"
"$VENV/python" -m workflows.temporal_worker \
  > "$LOG_DIR/worker.log" 2>&1 &
echo $! >> "$PID_FILE"
sleep 3
if kill -0 "$(tail -1 "$PID_FILE")" 2>/dev/null; then
  success "Temporal worker started (PID $(tail -1 "$PID_FILE"))"
else
  error "Temporal worker failed to start – check $LOG_DIR/worker.log"
  exit 1
fi

# ── 6. Vite frontend ──────────────────────────────────────────────────────────
info "Step 6/6 – Vite frontend..."
if nc -z 127.0.0.1 5173 2>/dev/null; then
  warn "Port 5173 already in use – skipping Vite start"
else
  cd "$FRONTEND_DIR"
  if [[ -x "$FRONTEND_DIR/node_modules/.bin/vite" ]]; then
    "$FRONTEND_DIR/node_modules/.bin/vite" > "$LOG_DIR/frontend.log" 2>&1 &
  elif command -v npx >/dev/null 2>&1; then
    npx vite > "$LOG_DIR/frontend.log" 2>&1 &
  else
    error "No Vite binary found in node_modules or npx – run 'npm install' in artx/"
    exit 1
  fi
  echo $! >> "$PID_FILE"
  wait_for_port "Vite" 5173 30
fi

# ── Summary ───────────────────────────────────────────────────────────────────
echo ""
echo -e "${BOLD}${GREEN}✅  Artifex is running!${RESET}"
echo ""
echo -e "  ${CYAN}Frontend${RESET}   →  http://localhost:5173"
echo -e "  ${CYAN}API${RESET}        →  http://localhost:8000"
echo -e "  ${CYAN}API docs${RESET}   →  http://localhost:8000/docs"
echo -e "  ${CYAN}Temporal UI${RESET}→  http://localhost:8233"
echo ""
echo -e "  Logs in:   ${LOG_DIR}/"
echo -e "  PIDs in:   ${PID_FILE}"
echo ""
echo -e "  To stop:   ${YELLOW}./start.sh --stop${RESET}"
echo ""
