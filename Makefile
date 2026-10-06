# ==============================================================================
# Factored AI & Data Hackathon 2026 - Makefile
# BETA AID: Banking Evolutionary Transformation and AI Deployment
# ==============================================================================

.PHONY: help setup up down clean test lint format check db-init db-migrate \
        dbt-run dbt-test dbt-docs dbt-docs-static ml-train ml-serve evals docker-build deploy \
        eda-setup eda-test eda-test-data eda-test-notebooks \
        stack-env stack-copilot stack-data stack-dev stack-stream stack-obs stack-ps stack-down \
        data-api-dev \
        copilot-setup copilot-test copilot-snapshot copilot-kb copilot-tune copilot-eval copilot-dev copilot-deploy copilot-deploy-gcp

# Default target
help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}'

# ==============================================================================
# Setup & Environment
# ==============================================================================
setup: ## Initial project setup (install deps, pre-commit, create .env)
	@echo "🔧 Setting up project..."
	pip install -e ".[dev]"
	pre-commit install --hook-type pre-commit --hook-type commit-msg
	@if [ ! -f .env ]; then cp .env.example .env; echo "📝 Created .env from template"; fi
	@echo "✅ Setup complete!"

venv: ## Create virtual environment with uv
	uv venv .venv --python 3.11
	@echo "Activate with: source .venv/bin/activate"

# ==============================================================================
# Docker Compose
# ==============================================================================
up: ## Start core services (postgres, redis, neo4j, mlflow)
	docker compose --profile core up -d
	@echo "🚀 Core services started"
	@echo "  PostgreSQL: localhost:5432"
	@echo "  Redis:      localhost:6379"
	@echo "  Neo4j:      localhost:7474"
	@echo "  MLflow:     localhost:5000"

up-full: ## Start all services
	docker compose --profile full up -d

up-monitoring: ## Start monitoring services (prometheus, grafana)
	docker compose --profile core --profile monitoring up -d

up-streaming: ## Start streaming services (kafka, zookeeper)
	docker compose --profile core --profile streaming up -d

down: ## Stop all services
	docker compose --profile full down

down-clean: ## Stop all services and remove volumes
	docker compose --profile full down -v

logs: ## Tail logs from all running services
	docker compose --profile full logs -f --tail=50

# ==============================================================================
# Database
# ==============================================================================
db-init: ## Initialize database schemas
	docker compose exec postgres psql -U factored -d bankingdb -f /docker-entrypoint-initdb.d/01_init.sql

db-migrate: ## Run Alembic migrations
	cd backend && alembic upgrade head

db-seed: ## Seed database with sample data
	python scripts/seed_data.py

# ==============================================================================
# Data Engineering
# ==============================================================================
dbt-run: ## Run all dbt models
	cd data_engineering/dbt && dbt run

dbt-test: ## Run dbt tests
	cd data_engineering/dbt && dbt test

dbt-docs: ## Generate and serve the platform dbt docs on :8081 (needs the built lakehouse for the catalog)
	cd platform/dbt && DBT_PROFILES_DIR=. uv run --project .. dbt docs generate && \
		DBT_PROFILES_DIR=. uv run --project .. dbt docs serve --port 8081

dbt-docs-static: ## Build the single-file docs site platform/dbt/target/static_index.html (what gets published)
	cd platform/dbt && DBT_PROFILES_DIR=. uv run --project .. dbt docs generate --static

spark-bronze: ## Run Bronze → Silver Spark ETL
	cd data_engineering/spark && python jobs/bronze_to_silver.py

spark-gold: ## Run Silver → Gold Spark ETL
	cd data_engineering/spark && python jobs/silver_to_gold.py

# ==============================================================================
# Machine Learning
# ==============================================================================
ml-train: ## Train all ML models
	@echo "🤖 Training ML models..."
	python ml/training/intent_classifier/train.py
	python ml/training/fraud_model/train.py
	python ml/training/sentiment_model/train.py
	python ml/training/dispute_classifier/train.py

ml-serve: ## Start ML model serving
	python ml/serving/model_server.py

ml-track: ## Open MLflow UI
	@echo "📊 MLflow UI at http://localhost:5000"

# ==============================================================================
# Agent System
# ==============================================================================
evals: ## Run agent evaluation suite
	python agents/evals/evaluator.py --suite=all

evals-ci: ## Run lightweight CI evaluation suite
	python agents/evals/evaluator.py --suite=ci

baseline: ## Run baseline comparison
	python agents/evals/baseline_comparison.py

# ==============================================================================
# Code Quality
# ==============================================================================
lint: ## Run linting
	ruff check backend/ agents/ ml/ data_engineering/

format: ## Format code
	ruff format backend/ agents/ ml/ data_engineering/

typecheck: ## Run type checking
	mypy backend/ agents/

check: lint typecheck ## Run all code quality checks
	@echo "✅ All checks passed"

# ==============================================================================
# Testing
# ==============================================================================
test: ## Run unit tests
	pytest backend/tests/unit agents/evals -m "unit" -v

test-integration: ## Run integration tests (requires Docker)
	pytest backend/tests/integration -m "integration" -v

test-all: ## Run all tests
	pytest --cov=backend --cov=agents --cov-report=html -v

# EDA workspace: its own uv environment (Python 3.12). Data tests need the dataset under
# the repository-level data/ or LATAM_EDA_DATA pointing at a copy; they skip when it is absent.
eda-setup: ## Install the EDA environment
	cd eda && uv sync

eda-test: ## Run the EDA tests that need no dataset (as CI does)
	cd eda && uv run pytest -m "not data and not notebooks"

eda-test-data: ## Run the EDA tests against the real dataset
	cd eda && uv run pytest -m "data and not notebooks"

eda-test-notebooks: ## Execute every EDA notebook and check its tables reproduce (long)
	cd eda && uv run pytest -m notebooks

# ==============================================================================
# Platform stack by stage (platform/docker/compose.yml profiles)
# ==============================================================================
# Start only what a stage needs; naming services starts their dependencies too. The compose project
# is fixed (latam-platform) and its bind mounts are relative to the checkout: run these from the
# checkout that hosts the stack (see docs/development/git-workflow.md), or every container is
# recreated against this one. Deployment uses none of them: the copilot ships to Modal.
STACK = docker compose -f platform/docker/compose.yml

stack-env: ## Generate the stack's random secrets into platform/docker/.env (once)
	cd platform/docker && python3 bootstrap_env.py

stack-copilot: ## Copilot development: pgvector, Neo4j and MLflow only
	$(STACK) --profile core --profile graph --profile ml up -d pg-core neo4j mlflow

stack-data: ## Data pipelines: Postgres x2, MinIO (WORM), Airflow 3
	$(STACK) --profile core up -d

stack-dev: ## Full development stack: pipelines + graph + MLflow
	$(STACK) --profile core --profile graph --profile ml up -d

stack-stream: ## Add streaming: Redpanda, Flink, fraud scorer, Kong
	$(STACK) --profile stream up -d

stack-obs: ## Add observability: Marquez, Prometheus, Grafana
	$(STACK) --profile obs up -d

stack-ps: ## Show the stack's containers
	$(STACK) --profile core --profile graph --profile ml --profile stream --profile obs ps

stack-down: ## Stop the stack (volumes kept)
	$(STACK) --profile core --profile graph --profile ml --profile stream --profile obs down

# ==============================================================================
# BETA AID Data API (platform/services/data_api, its own uv project)
# ==============================================================================
data-api-dev: ## Run the read-only Data API on http://127.0.0.1:8090
	cd platform/services/data_api && uv run uvicorn data_api.app:app --host 127.0.0.1 --port 8090 --reload

# ==============================================================================
# Card copilot (copilot/, its own uv project)
# ==============================================================================
copilot-setup: ## Install the copilot (with tuning, retrieval and store extras)
	cd copilot && uv sync --extra tune --extra rag --extra stores

copilot-test: ## Run the copilot tests (synthetic snapshot, as CI does)
	cd copilot && uv run pytest -q

copilot-snapshot: ## Export the demo snapshot from the local lakehouse to data/copilot/
	cd copilot && uv run python scripts/export_snapshot.py

copilot-kb: ## Build the bundled knowledge-base index and verify it against pgvector and Neo4j
	cd copilot && uv run python scripts/build_kb_index.py --verify

copilot-tune: ## Tune the intent model with Optuna, tracked in MLflow (needs stack-copilot)
	cd copilot && MLFLOW_TRACKING_URI=http://127.0.0.1:5001 uv run python scripts/tune_intent.py --trials 40

copilot-eval: ## Score the frozen challenge set and the retrievers (adds Claude when a key is set)
	cd copilot && uv run python eval/run.py && uv run python eval/kb_retrieval.py --stack

copilot-dev: ## Run the copilot locally on http://127.0.0.1:8000
	cd copilot && uv run uvicorn copilot.app:app --reload

copilot-deploy: ## Deploy the copilot to Modal (needs modal setup and the copilot-data volume)
	cd copilot && COPILOT_MODAL_SECRET=$${COPILOT_MODAL_SECRET:-} modal deploy deploy/modal_app.py

copilot-deploy-gcp: ## Deploy the copilot to Cloud Run per residency region (MX Querétaro; CO and AR São Paulo)
	copilot/deploy/cloudrun/deploy.sh mx northamerica-south1 MX
	copilot/deploy/cloudrun/deploy.sh sa southamerica-east1 CO AR

# ==============================================================================
# Backend
# ==============================================================================
dev: ## Start FastAPI dev server
	uvicorn backend.app.main:app --reload --host 0.0.0.0 --port 8000

# ==============================================================================
# Docker Build
# ==============================================================================
docker-build: ## Build all Docker images
	docker compose --profile full build

# ==============================================================================
# Deployment
# ==============================================================================
deploy: ## Deploy to GCP (Cloud Run)
	@echo "🚀 Deploying to GCP..."
	cd infrastructure/terraform && terraform apply -auto-approve

# ==============================================================================
# Cleanup
# ==============================================================================
clean: ## Clean generated files
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .pytest_cache -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .ruff_cache -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .mypy_cache -exec rm -rf {} + 2>/dev/null || true
	rm -rf htmlcov/ .coverage
