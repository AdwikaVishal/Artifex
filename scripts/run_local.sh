#!/usr/bin/env bash
# run_local.sh – start the full Artifex stack locally via Docker Compose
set -euo pipefail

echo "🚀 Starting Artifex locally..."

# Ensure .env exists
if [ ! -f .env ]; then
  echo "⚠️  .env not found – copying from .env.example"
  cp .env.example .env
  echo "✏️  Edit .env and set OPENAI_API_KEY, then re-run."
  exit 1
fi

# Build images
docker compose build --parallel

# Start infrastructure first
docker compose up -d nats temporal qdrant redis otel-collector prometheus grafana

echo "⏳ Waiting for infrastructure to be healthy..."
sleep 15

# Start agents
docker compose up -d planner retriever executor validator supervisor recovery temporal-worker api

echo ""
echo "✅ Artifex is running!"
echo "   API:      http://localhost:8000"
echo "   Grafana:  http://localhost:3000  (admin / artifex)"
echo "   Prometheus: http://localhost:9090"
echo ""
echo "Test with:"
echo "  curl -X POST http://localhost:8000/swarm/run \\"
echo "    -H 'Content-Type: application/json' \\"
echo "    -d '{\"goal\": \"What is the capital of France?\"}'"
