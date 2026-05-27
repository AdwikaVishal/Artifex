.PHONY: install test dev down deploy observe lint fmt clean

# ── Setup ─────────────────────────────────────────────────────────────────────
install:
	pip install -e ".[dev]"

# ── Testing ───────────────────────────────────────────────────────────────────
test:
	pytest tests/ -v --cov=. --cov-report=term-missing

test-fast:
	pytest tests/ -v -x

# ── Local development ─────────────────────────────────────────────────────────
dev:
	docker compose up --build

dev-infra:
	docker compose up -d nats temporal qdrant redis otel-collector prometheus grafana

dev-agents:
	docker compose up -d planner retriever executor validator supervisor recovery temporal-worker api

down:
	docker compose down -v

logs:
	docker compose logs -f --tail=100

# ── Kubernetes ────────────────────────────────────────────────────────────────
deploy:
	bash scripts/deploy_k8s.sh

undeploy:
	kubectl delete namespace artifex --ignore-not-found

# ── Observability ─────────────────────────────────────────────────────────────
observe:
	@echo "Port-forwarding Grafana to http://localhost:3000 ..."
	kubectl port-forward -n artifex svc/grafana 3000:3000

observe-prometheus:
	kubectl port-forward -n artifex svc/prometheus 9090:9090

# ── Code quality ──────────────────────────────────────────────────────────────
lint:
	ruff check .
	mypy agents/ workflows/ api/ nats_client/ tools/

fmt:
	ruff format .

# ── Cleanup ───────────────────────────────────────────────────────────────────
clean:
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -name "*.pyc" -delete
	rm -rf .pytest_cache htmlcov .coverage dist build *.egg-info
