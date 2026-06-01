#!/bin/zsh
# Load .env and start the FastAPI server
set -a
source "$(dirname "$0")/.env"
set +a
exec "$(dirname "$0")/.venv/bin/python" -m uvicorn api.main:app --reload
