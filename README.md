# 🏦 AI-First Banking Customer Service System

### Factored AI & Data Hackathon 2026

> An intelligent, multilingual customer service system for LATAM banking operations. Handles transaction disputes, card support, and account inquiries with AI-powered decision making, human escalation, and full observability.

[![CI](https://github.com/your-team/factored-hackathon-2026-andres/actions/workflows/ci.yml/badge.svg)](https://github.com/your-team/factored-hackathon-2026-andres/actions)

---

## 🎯 Problem Statement

Build an AI-first banking customer service system that can **understand** complex customer interactions, **decide** on appropriate actions, **act** using secure tools, **verify** outcomes, and **escalate** to human agents when needed — serving customers across Mexico, Colombia, and Argentina in Spanish and Portuguese.

**Focused Workflow**: Transaction Disputes & Card Support

## 🏗️ Architecture

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

## 🚀 Quick Start

### Prerequisites
- Docker & Docker Compose
- Python 3.11+
- Make

### Setup

```bash
# Clone the repository
git clone https://github.com/your-team/factored-hackathon-2026-andres.git
cd factored-hackathon-2026-andres

# Copy environment template
cp .env.example .env
# Edit .env with your API keys (OPENAI_API_KEY, GOOGLE_API_KEY)

# Install Python dependencies
make setup

# Start core services (PostgreSQL, Redis, Neo4j, MLflow)
make up

# Initialize database
make db-init

# Start the API server
make dev
```

The API will be available at `http://localhost:8000` with docs at `http://localhost:8000/docs`.

### Full Stack

```bash
# Start everything (including monitoring, orchestration)
make up-full

# Services available:
# API:         http://localhost:8000
# Frontend:    http://localhost:3000
# MLflow:      http://localhost:5000
# Neo4j:       http://localhost:7474
# Airflow:     http://localhost:8080
# Grafana:     http://localhost:3001
# Prometheus:  http://localhost:9090
```

## 📊 Dataset

| Table | Rows | Type | Description |
|-------|------|------|-------------|
| `customers` | 150K | Dimension | Bank customers across MX/CO/AR |
| `products` | 400K | Dimension | Financial products (accounts, cards, loans) |
| `transactions` | 5M | Fact | Daily financial transactions |
| `call_center_interactions` | 800K | Fact | Customer service interactions |
| `call_transcripts` | 200K | Fact | Call transcripts in Spanish |
| `complaints` | 80K | Fact | Complaints and claims |
| `digital_events` | 10M | Fact | Digital channel events |
| `satisfaction_surveys` | 250K | Fact | CSAT/NPS surveys |
| `campaign_sends` | 2M | Fact | Marketing campaign sends |
| + 4 reference tables | | | Branches, agents, campaigns, exchange rates |

## 🤖 ML Models

| Model | Purpose | Framework | Serving |
|-------|---------|-----------|---------|
| Intent Classifier | Route customer requests | XLM-RoBERTa | ONNX (<10ms) |
| Fraud Scorer | Transaction risk assessment | XGBoost + SHAP | MLflow (<50ms) |
| Sentiment Analyzer | Customer emotion detection | Fine-tuned mBERT | ONNX (<15ms) |
| Dispute Predictor | Predict resolution outcome | LightGBM | MLflow |
| Churn Predictor | Identify at-risk customers | XGBoost | Batch |
| Injection Detector | Input safety guardrail | DistilBERT | ONNX (<5ms) |

## 🧪 Evaluation

| Metric | Target | Description |
|--------|--------|-------------|
| Safe Resolution Rate | >70% | Correct automated resolutions |
| Unsafe Outcome Rate | <2% | Wrong info or unauthorized actions |
| Escalation Precision | >85% | Correct human escalations |
| P50 Latency | <3s | Median response time |
| P95 Latency | <8s | 95th percentile response time |
| Injection Detection | >95% | Blocked prompt injections |

## 🛠️ Tech Stack

**Backend**: FastAPI, LangGraph, LangChain, LiteLLM, PostgreSQL, PGVector, Neo4j, Redis

**Data**: Apache Spark, dbt, Airflow, Great Expectations, Kafka, BigQuery

**ML**: scikit-learn, XGBoost, LightGBM, HuggingFace Transformers, ONNX Runtime, MLflow, Optuna, SHAP, Evidently

**Frontend**: Next.js, React, TypeScript, TailwindCSS

**Infrastructure**: Docker, Terraform, GitHub Actions, Prometheus, Grafana

## 📁 Project Structure

```
├── agents/          # LangGraph multi-agent system
├── backend/         # FastAPI REST + WebSocket API
├── data_engineering/ # Spark ETL, dbt models, Airflow DAGs
├── docs/            # Architecture decisions, specs
├── frontend/        # Next.js customer & admin UI
├── infrastructure/  # Docker, Terraform, CI/CD
├── ml/              # ML training, serving, monitoring
├── monitoring/      # Prometheus, Grafana configs
└── scripts/         # Setup & utility scripts
```

## 📜 License

MIT

## 👤 Author

**Andres Becerra** — Factored AI & Data Hackathon 2026
