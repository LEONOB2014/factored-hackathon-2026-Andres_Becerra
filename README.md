# 🏦 AI-First Banking Customer Service System

### Factored AI & Data Hackathon 2026

> An intelligent, multilingual customer service system for LATAM banking operations. Handles transaction disputes, card support, and account inquiries with AI-powered decision making, human escalation, and full observability.

[![CI](https://github.com/LEONOB2014/factored-hackathon-2026-Andres_Becerra/actions/workflows/ci.yml/badge.svg)](https://github.com/LEONOB2014/factored-hackathon-2026-Andres_Becerra/actions/workflows/ci.yml)

---

## 🎯 Problem Statement

Build an AI-first banking customer service system that can **understand** complex customer interactions, **decide** on appropriate actions, **act** using secure tools, **verify** outcomes, and **escalate** to human agents when needed — serving customers across Mexico, Colombia, and Argentina in Spanish and Portuguese.

**Focused Workflow**: Transaction Disputes & Card Support

## 📍 Project Status

| Area | Path | Status |
|---|---|---|
| Exploratory data analysis | [`eda/`](eda/) | ✅ Done — 11-notebook study, reports, dashboards, 188 tests |
| Dataset docs & ERD | [`docs/dataset/`](docs/dataset/) | ✅ Done — ERD generated from the data dictionary |
| Backend API | `backend/` | 🧱 Scaffold — FastAPI app and routers; `/health` works, chat, analytics and model endpoints return placeholders |
| Agent orchestrator | `agents/` | 🧱 Scaffold — LangGraph graph and state wired; every node is a TODO |
| Data engineering | `data_engineering/` | 🧱 Scaffold — dbt project and raw sources; no models, Spark jobs or DAGs yet |
| ML models | `ml/` | ⏳ Not started — empty packages |
| Frontend | `frontend/` | ⏳ Not started — the folder does not exist yet |
| Infrastructure | `infrastructure/`, `docker-compose.yml` | 🧱 Scaffold — compose stack, Dockerfiles, Terraform |
| CI & quality gates | `.github/`, `.pre-commit-config.yaml` | ✅ Done — pre-commit, unit, EDA, integration and dbt jobs |

The architecture, models and evaluation targets below describe the **target system**; the table above is what exists today.

## 🔎 Data Exploration (`eda/`)

A CRISP-DM study of the datathon bucket, which ships two folders: the main dataset and an unexplained `data_backup_20260831/`. It answers three questions:

1. **What is in the data?** Volumes, nulls, duplicates, referential integrity and distributions per table — [`eda/reports/eda_overview.md`](eda/reports/eda_overview.md).
2. **What is the backup?** Set difference, time-shift diagnostics, record linkage and statistical equivalence (notebooks 02–06).
3. **What looks anomalous?** Rules, robust statistics, ML, deep and supervised detectors, and their consensus (notebooks 07–10).

Key findings ([full report](eda/reports/notebooks/11_evaluation_and_report.html), [summary](docs/dataset/backup_comparison.md)):

- **The backup is not a copy.** It is a second, independently generated realisation of the same bank: same schema and statistics for the core tables, mostly different IDs, two tables missing and `transactions` truncated to 2023-07-01 → 2024-09-25. Never join it to the main data.
- **Shared IDs are noisy.** Of 4,025 customer IDs present in both folders, 25 % belong to a different person.
- **Both folders carry the same defects:** products opened before the customer registered (50 %), transactions before their product existed (18.7 %), Mexican transactions labelled `USD`, ~5 % nulls injected into mandatory fields, and `fraud_score ≥ 35` ⇒ fraud in 100 % of cases (label leakage).

Everything is reproducible: each notebook re-runs against the data and must regenerate its committed tables (`make eda-test-notebooks`). See [`eda/README.md`](eda/README.md) for the layout and how to run it.

## 📊 Dataset

13 tables, process dates 2023-06-17 → 2026-06-17, currencies MXN/COP/ARS/USD. Row counts are **measured** from the main folder; several differ from the documented sizes.

| Table | Type | Rows (measured) | Documented |
|-------|------|----------------:|-----------:|
| `customers` | Dimension | 150,000 | 150K |
| `products` | Dimension | 400,000 | 400K |
| `branches` | Dimension | 350 | 350 |
| `service_agents` | Dimension | 1,200 | 1.2K |
| `marketing_campaigns` | Dimension | 200 | 200 |
| `transactions` | Fact | 4,425,008 | 5M |
| `digital_events` | Fact | 15,620,994 | 10M |
| `call_center_interactions` | Fact | 686,296 | 800K |
| `call_transcripts` | Fact | 171,321 | 200K |
| `satisfaction_surveys` | Fact | 212,759 | 250K |
| `complaints` | Fact | 67,095 | 80K |
| `campaign_sends` | Fact | 1,746,801 | 2M |
| `daily_exchange_rates` | Reference | 13,164 | 3K |

- **Schema & relationships:** [ERD](docs/dataset/erd.md) (Mermaid, 260 columns, 24 foreign keys), generated from the [data dictionary](docs/dataset/LATAM_Bank_Complete_Data_Dictionary.pdf).
- **Getting the data:** it is not in git (~10 GB raw). `eda/scripts/download_s3.py` downloads it with AWS credentials in `eda/.env`; `LATAM_EDA_DATA` points the EDA at an existing copy.

## 🏗️ Target Architecture

```
┌──────────────────────────────────────────────────────────────────┐
│                        FRONTEND (Next.js)                        │
│  Chat Interface │ Analytics Dashboard │ Agent Monitor             │
└──────────────────────────┬───────────────────────────────────────┘
                           │ WebSocket / REST
┌──────────────────────────┴───────────────────────────────────────┐
│                     BACKEND (FastAPI)                             │
│  Auth │ Chat Router │ Analytics API │ ML Model API │ Audit Log    │
└──────────────────────────┬───────────────────────────────────────┘
                           │
┌──────────────────────────┴───────────────────────────────────────┐
│              AGENT ORCHESTRATOR (LangGraph)                       │
│                                                                   │
│  InputGuardrails → Identity → IntentRouter → Domain Agents →     │
│  Verification → ResponseGen → OutputGuardrails                    │
│                                                                   │
│  Memory: Redis (short) │ PostgreSQL (long) │ PGVector (semantic)  │
│  Search: Hybrid RAG (Vector + BM25) │ GraphRAG (Neo4j)           │
└──────────────────────────┬───────────────────────────────────────┘
                           │
┌──────────────────────────┴───────────────────────────────────────┐
│                    ML MODEL SERVING                               │
│  Intent Classifier │ Fraud Scorer │ Sentiment │ Dispute Predictor │
│  (ONNX Runtime + MLflow Model Registry)                          │
└──────────────────────────┬───────────────────────────────────────┘
                           │
┌──────────────────────────┴───────────────────────────────────────┐
│                   DATA PLATFORM                                   │
│  Ingestion: Spark ETL │ Transformation: dbt │ Orchestration: Airflow│
│  Storage: PostgreSQL + BigQuery │ Quality: Great Expectations     │
│  Streaming: Kafka + Spark Structured Streaming                    │
└──────────────────────────────────────────────────────────────────┘
```

Design specs: [product](docs/specs/PRODUCT_SPEC.md) · [data engineering](docs/specs/DATA_ENGINEERING_SPEC.md) · [ML](docs/specs/ML_SPEC.md) · [agents](docs/specs/AGENT_SPEC.md).

## 🚀 Quick Start

### Prerequisites
- Python 3.11+ and [uv](https://docs.astral.sh/uv/) (the EDA installs its own Python 3.12)
- Docker & Docker Compose, Make

### Application (scaffold)

```bash
git clone https://github.com/LEONOB2014/factored-hackathon-2026-Andres_Becerra.git
cd factored-hackathon-2026-Andres_Becerra

make setup        # installs .[dev], the pre-commit + commit-msg hooks, and creates .env
make dev          # FastAPI on http://localhost:8000 (docs at /docs)
make test         # backend unit tests
```

Fill in `.env` (copied from `.env.example`) before using LLM-backed features. The service stack is defined in `docker-compose.yml`, but `make up` includes a `frontend` service built from `./frontend`, which does not exist yet; until it does, start the data services by name:

```bash
docker compose up -d postgres redis neo4j mlflow
make db-init
```

### Exploratory analysis

```bash
make eda-setup                                 # eda/ has its own uv environment
export LATAM_EDA_DATA=/path/to/data            # or download into eda/data/ (see eda/README.md)
make eda-test                                  # tests that need no dataset (what CI runs)
make eda-test-data                             # findings recomputed from the real data
make eda-test-notebooks                        # re-run all 11 notebooks (~6 min)
```

## 🧪 Quality & Workflow

- **Branches and PRs.** Work on `feat/…`, `fix/…`, `test/…` branches and merge through pull requests into `main`.
- **Conventional Commits**, enforced by commitizen at the `commit-msg` hook (`feat(eda): …`, `fix: …`, `docs: …`).
- **pre-commit** is the single quality gate, locally and in CI: ruff (lint + format), mypy (`backend/`, `agents/`), sqlfluff (dbt), actionlint, detect-secrets, file hygiene, plus `eda-lock` and `eda-tests` for the EDA workspace.
- **CI** (`.github/workflows/ci.yml`) runs on pull requests into `main` and pushes to `main`:

| Job | What it checks |
|---|---|
| Lint, Format & Type Check | `pre-commit run --all-files` |
| Unit Tests | `backend/tests/unit`, `agents/evals` |
| EDA Tests | the EDA suite minus dataset-dependent tests |
| Integration Tests | `backend/tests/integration` against Postgres and Redis (none written yet) |
| dbt Tests | `dbt seed/run/test` against Postgres |
| Agent Evaluations | `main` only; skipped until `agents/evals/evaluator.py` exists |
| Docker Build | `main` only; builds the API image |

## 🤖 Planned ML Models

| Model | Purpose | Framework | Serving |
|-------|---------|-----------|---------|
| Intent Classifier | Route customer requests | XLM-RoBERTa | ONNX (<10ms) |
| Fraud Scorer | Transaction risk assessment | XGBoost + SHAP | MLflow (<50ms) |
| Sentiment Analyzer | Customer emotion detection | Fine-tuned mBERT | ONNX (<15ms) |
| Dispute Predictor | Predict resolution outcome | LightGBM | MLflow |
| Churn Predictor | Identify at-risk customers | XGBoost | Batch |
| Injection Detector | Input safety guardrail | DistilBERT | ONNX (<5ms) |

The EDA's [label-leakage check](eda/reports/tables/fraud_label_leakage.csv) matters for the fraud scorer: `fraud_score` alone predicts `is_fraud` with AUC 0.82, while the behavioural features alone reach 0.51. `fraud_score` is a leaked label, not a usable feature, and the real fraud signal still has to be engineered.

## 🎯 Evaluation Targets

| Metric | Target | Description |
|--------|--------|-------------|
| Safe Resolution Rate | >70% | Correct automated resolutions |
| Unsafe Outcome Rate | <2% | Wrong info or unauthorized actions |
| Escalation Precision | >85% | Correct human escalations |
| P50 Latency | <3s | Median response time |
| P95 Latency | <8s | 95th percentile response time |
| Injection Detection | >95% | Blocked prompt injections |

## 🛠️ Tech Stack

**In use**: Python, FastAPI, LangGraph, DuckDB, pandas, scikit-learn, PyOD, PyTorch, Plotly, D3.js, dbt, uv, pre-commit, GitHub Actions, Docker

**Planned**: LangChain, LiteLLM, PostgreSQL + PGVector, Neo4j, Redis, Spark, Airflow, Great Expectations, Kafka, BigQuery, XGBoost, LightGBM, HuggingFace Transformers, ONNX Runtime, MLflow, Optuna, SHAP, Evidently, Next.js, Terraform, Prometheus, Grafana

## 📁 Project Structure

```
├── agents/            # LangGraph orchestrator and agent state (scaffold)
├── backend/           # FastAPI app, routers and tests (scaffold)
├── data_engineering/  # dbt project and raw sources (scaffold)
├── docs/              # Hackathon brief, dataset docs + ERD, specs, research
├── eda/               # Exploratory analysis: notebooks, scripts, reports, tests
├── infrastructure/    # Dockerfiles and Terraform
├── ml/                # ML training, serving, monitoring (empty)
├── monitoring/        # Prometheus config
└── scripts/           # Database initialisation SQL
```

Documentation index: [`docs/README.md`](docs/README.md).

## 📜 License

MIT

## 👤 Author

**Andres Becerra** — Factored AI & Data Hackathon 2026
