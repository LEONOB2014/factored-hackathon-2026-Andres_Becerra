# ==============================================================================
# Factored AI & Data Hackathon 2026 - Makefile
# AI-First Banking Customer Service System
# ==============================================================================

.PHONY: help setup up down clean test lint format check db-init db-migrate \
        dbt-run dbt-test ml-train ml-serve evals docker-build deploy \
        eda-setup eda-test eda-test-data eda-test-notebooks

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

dbt-docs: ## Generate and serve dbt documentation
	cd data_engineering/dbt && dbt docs generate && dbt docs serve --port 8081

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
# eda/data/ or LATAM_EDA_DATA pointing at a copy; they skip when it is absent.
eda-setup: ## Install the EDA environment
	cd eda && uv sync

eda-test: ## Run the EDA tests that need no dataset (as CI does)
	cd eda && uv run pytest -m "not data and not notebooks"

eda-test-data: ## Run the EDA tests against the real dataset
	cd eda && uv run pytest -m "data and not notebooks"

eda-test-notebooks: ## Execute every EDA notebook and check its tables reproduce (long)
	cd eda && uv run pytest -m notebooks

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
