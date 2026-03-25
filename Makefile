# ==============================================================
# Latexy — Root Makefile
# Backend: 8030  |  Frontend: 5180
#
# Quick start (everything):
#   make run          ← builds + starts the full dev stack
#   make run-prod     ← production stack (nginx + prod images)
# ==============================================================

.PHONY: help run run-prod run-stop run-logs infra down logs \
        logs-backend logs-celery logs-flower clean \
        backend frontend dev \
        test test-backend test-frontend lint lint-backend lint-frontend \
        migrate db-backup db-restore redis-backup \
        build build-backend build-frontend \
        k8s-deploy k8s-status k8s-migrate k8s-clean k8s-logs \
        health-check logs-all

# Root compose = full dev stack (postgres, redis, minio, backend, worker, beat, frontend, flower)
ROOT_COMPOSE      := docker-compose.yml
ROOT_COMPOSE_PROD := docker-compose.prod.yml
# Infra-only compose (Redis + Postgres + workers, no frontend dev server)
COMPOSE_FILE      := backend/docker-compose.yml
BACKEND_DIR       := backend
FRONTEND_DIR      := frontend
K8S_DIR           := k8s

# ── Default ────────────────────────────────────────────────────────────────
help:
	@echo ""
	@echo "  Latexy — available make targets"
	@echo ""
	@echo "  ── Full stack ───────────────────────────────────────────────"
	@echo "    run              Build + start everything (dev stack)"
	@echo "                       postgres, redis, minio, backend, worker,"
	@echo "                       beat, frontend, flower  — one command"
	@echo "    run-prod         Build + start production stack (nginx, prod images)"
	@echo "    run-stop         Stop whichever stack is running"
	@echo "    run-logs         Tail all logs from the full stack"
	@echo ""
	@echo "  ── Development (infra-only) ──────────────────────────────"
	@echo "    infra            Start Docker infra only (Redis, Postgres, workers)"
	@echo "    down             Stop infra services"
	@echo "    logs             Tail infra service logs"
	@echo "    logs-backend     Tail backend container logs"
	@echo "    logs-celery      Tail celery-worker logs"
	@echo "    backend          Run FastAPI dev server  (port 8030)"
	@echo "    frontend         Run Next.js dev server  (port 5180)"
	@echo "    dev              Alias for frontend"
	@echo "    clean            Remove containers, volumes, caches"
	@echo ""
	@echo "  ── Testing & Linting ────────────────────────────────────────"
	@echo "    test             Run backend + frontend tests"
	@echo "    test-backend     pytest backend/test/"
	@echo "    test-frontend    npm test (frontend)"
	@echo "    lint             ruff + eslint"
	@echo "    lint-backend     ruff check app/ test/"
	@echo "    lint-frontend    eslint frontend/src"
	@echo ""
	@echo "  ── Database ─────────────────────────────────────────────────"
	@echo "    migrate          alembic upgrade head"
	@echo "    db-backup        Dump PostgreSQL to /opt/backups/database/"
	@echo "    db-restore       Restore PostgreSQL (interactive)"
	@echo "    redis-backup     Backup Redis RDB to /opt/backups/redis/"
	@echo ""
	@echo "  ── Build ────────────────────────────────────────────────────"
	@echo "    build            Build backend + frontend Docker images"
	@echo "    build-backend    docker build latexy-backend:latest"
	@echo "    build-frontend   docker build latexy-frontend:latest"
	@echo ""
	@echo "  ── Kubernetes ───────────────────────────────────────────────"
	@echo "    k8s-deploy       Full K8s deployment via k8s/deploy.sh"
	@echo "    k8s-status       kubectl get pods/services/pvc -n latexy"
	@echo "    k8s-migrate      Run alembic in the running backend pod"
	@echo "    k8s-clean        Delete entire latexy namespace (with confirmation)"
	@echo "    k8s-logs         Follow backend pod logs"
	@echo ""
	@echo "  ── Monitoring ───────────────────────────────────────────────"
	@echo "    health-check     Run scripts/monitoring/health-check.sh"
	@echo "    logs-all         Collect + analyse service logs"
	@echo ""

# ── Full stack (one-command start) ─────────────────────────────────────────
# Builds all images and starts every service in the root docker-compose.yml:
#   postgres · redis · minio · backend (auto-migrates) · worker · beat · frontend · flower
run:
	docker compose -f $(ROOT_COMPOSE) up --build

# Same but detached (background)
run-detach:
	docker compose -f $(ROOT_COMPOSE) up --build -d

# Production stack: nginx + prod-built images + monitoring
run-prod:
	docker compose -f $(ROOT_COMPOSE_PROD) up --build

run-stop:
	docker compose -f $(ROOT_COMPOSE) down 2>/dev/null; \
	docker compose -f $(ROOT_COMPOSE_PROD) down 2>/dev/null; true

run-logs:
	docker compose -f $(ROOT_COMPOSE) logs -f

# ── Infrastructure (infra-only, no frontend dev server) ────────────────────
infra:
	docker compose -f $(COMPOSE_FILE) up -d

down:
	docker compose -f $(COMPOSE_FILE) down

logs:
	docker compose -f $(COMPOSE_FILE) logs -f

logs-backend:
	docker compose -f $(COMPOSE_FILE) logs -f backend

logs-celery:
	docker compose -f $(COMPOSE_FILE) logs -f celery-worker

logs-flower:
	docker compose -f $(COMPOSE_FILE) logs -f flower

clean:
	docker compose -f $(COMPOSE_FILE) down -v --remove-orphans
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -name "*.pyc" -delete 2>/dev/null || true
	rm -rf $(FRONTEND_DIR)/.next $(FRONTEND_DIR)/node_modules/.cache

# ── Development servers ────────────────────────────────────────────────────
# Requires infra to be running first (make infra)
backend:
	cd $(BACKEND_DIR) && uvicorn app.main:app --host 0.0.0.0 --port 8030 --reload

frontend:
	cd $(FRONTEND_DIR) && npm run dev

dev: frontend

# ── Testing ────────────────────────────────────────────────────────────────
test: test-backend test-frontend

test-backend:
	cd $(BACKEND_DIR) && pytest test/ -v --tb=short

test-frontend:
	cd $(FRONTEND_DIR) && pnpm run test:unit

# ── Linting ────────────────────────────────────────────────────────────────
lint: lint-backend lint-frontend

lint-backend:
	cd $(BACKEND_DIR) && venv/bin/ruff check app/ test/ \
	  || python -m ruff check app/ test/

lint-frontend:
	cd $(FRONTEND_DIR) && npm run lint

# ── Database ───────────────────────────────────────────────────────────────
migrate:
	cd $(BACKEND_DIR) && alembic upgrade head

db-backup:
	bash scripts/backup/database-backup.sh

db-restore:
	bash scripts/backup/restore-database.sh

redis-backup:
	bash scripts/backup/redis-backup.sh

# ── Build ──────────────────────────────────────────────────────────────────
build: build-backend build-frontend

build-backend:
	docker build -t ghcr.io/your-org/latexy-backend:latest \
	  -f $(BACKEND_DIR)/Dockerfile $(BACKEND_DIR)

build-frontend:
	docker build -t ghcr.io/your-org/latexy-frontend:latest \
	  -f $(FRONTEND_DIR)/Dockerfile $(FRONTEND_DIR)

# ── Kubernetes ─────────────────────────────────────────────────────────────
k8s-deploy:
	bash $(K8S_DIR)/deploy.sh

k8s-status:
	kubectl get pods,services,deployments,pvc -n latexy

k8s-migrate:
	kubectl exec -n latexy deploy/latexy-backend -- alembic upgrade head

k8s-clean:
	@echo "WARNING: This will delete the entire latexy namespace!"
	@read -p "Type 'yes' to confirm: " confirm && \
	  [ "$$confirm" = "yes" ] && kubectl delete namespace latexy || echo "Aborted."

k8s-logs:
	kubectl logs -n latexy -l app=latexy-backend -f

# ── Monitoring ─────────────────────────────────────────────────────────────
health-check:
	bash scripts/monitoring/health-check.sh

logs-all:
	bash scripts/monitoring/log-aggregator.sh
