# Runbook: run the platform locally

[index](README.md)

## Prerequisites
Docker Desktop with ≥ 8 GB memory, about 15 GB of free disk for images, `uv`. Data already downloaded to
`data/raw` (or run `landing_ingest` with `download_from_s3=true` and AWS credentials in `.env`).

## 1 · Secrets and images
```bash
cd platform/docker
python bootstrap_env.py                       # random secrets into platform/docker/.env (git-ignored)
docker compose --profile core build           # Airflow image (dbt + platform venvs)
docker compose --profile stream build         # Flink with connectors, fraud scorer
```
MinIO's own images are no longer public; the stack uses Chainguard's signed build (`cgr.dev/chainguard/minio`).

## 2 · Start profiles
```bash
docker compose --profile core --profile graph --profile ml --profile obs up -d    # ~3 GB RAM at rest
docker compose --profile core --profile ml --profile stream up -d                  # add streaming for the demo
```
| UI | URL (localhost only) |
|---|---|
| Airflow | http://127.0.0.1:8080 (users `admin`, `auditor`; passwords in the `airflow-config` volume, `simple_auth_passwords.json`) |
| MLflow | http://127.0.0.1:5001 |
| Marquez (lineage) | http://127.0.0.1:3000 |
| Neo4j Browser | http://127.0.0.1:7474 (user `neo4j`, password `NEO4J_PASSWORD`) |
| MinIO console | http://127.0.0.1:9001 |
| Flink | http://127.0.0.1:8081 |
| Grafana / Prometheus | http://127.0.0.1:3001 / :9090 |
| Kong (scorer API) | http://127.0.0.1:8000/fraud/score with header `x-api-key: $SCORER_API_KEY` |

The audit database has no published port by design: `docker compose exec pg-audit psql -U postgres -d audit`.

## 3 · Run the pipelines
Unpause the DAGs in the UI (or `airflow dags unpause <id>`), then trigger `landing_ingest`. Assets chain the
rest: `bronze_build` → `dbt_lakehouse` → `publish_serving`, `graph_load`, `compliance_triggers`,
`monitoring_drift`, `ml_fraud_ensemble` → approve the model in the Airflow UI (Required actions) →
`ml_tgn`, `ml_federated_gnn` after `graph_load`. `kb_sync` and `audit_anchor` run hourly.

## 4 · Real-time demo
With `fraud_ensemble@champion` approved and the stream profile up, trigger `stream_demo` with `days=3`,
`seconds_per_day=20`. It replays the holdout, waits for decisions and fails on any stream/batch mismatch.
Watch decisions in Grafana or `SELECT * FROM decisions.fraud_decision_log ORDER BY decision_id DESC LIMIT 20`.

## 5 · Verify the guarantees
```bash
uv run pytest platform/libs/tests -q                                  # PII guard, ledger, GenAI audit, DP, KB
docker compose exec airflow-scheduler python -m pytest /opt/latam/platform/airflow/tests -q   # DAG integrity
cd platform/dbt && DBT_PROFILES_DIR=. uv run dbt build                 # data tests, governance tests, unit tests
uv run python -m latam_platform.cli governance-check                   # manifest vs policies
cd platform/infra/terraform/gcp/envs/mx && terraform init -backend=false && terraform validate
```
Tamper demonstrations (safe on the local stack): see [04 §4.1](04_audit_and_lineage.md); after trying them,
recreate the audit volume (`docker compose rm -sf pg-audit && docker volume rm latam-platform_pg-audit-data`)
because a detected tamper stays in the chain by design.

## 6 · Host and container share one lakehouse file
When Airflow builds dbt, silver views store the container path (`/opt/latam/data/lake/...`). Query tables from the
host, or rebuild locally (`cd platform/dbt && DBT_PROFILES_DIR=. uv run dbt build`) before using views; never run host
dbt while an Airflow dbt run is active (DuckDB has a single writer).

## 7 · Memory notes (8 GB Docker allocation)
Tasks run inside the scheduler (LocalExecutor, 4 GB limit). DuckDB is capped at 1.5 GB per task and every heavy
DuckDB task shares the one-slot `duckdb_lakehouse` pool; the bronze build processes one month of files at a time
in a file-backed database. Start the stream profile without the obs profile if memory is tight.
