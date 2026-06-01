#!/bin/zsh
# Load .env and start the Temporal worker
set -a
source "$(dirname "$0")/.env"
set +a
exec "$(dirname "$0")/.venv/bin/python" -m workflows.temporal_worker
