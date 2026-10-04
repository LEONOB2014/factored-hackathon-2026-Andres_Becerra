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

Rebuild an image after **any** change to its Dockerfile or requirements: a running stack keeps the image it was
started with. To check, compare `docker image inspect latam/airflow:3.1.0 --format '{{.Created}}'` with
`git log -1 --format=%cI -- platform/docker/airflow`. Library code (`platform/libs`), DAGs and dbt are mounted, so
they need no rebuild.

## 2 · Start profiles
```bash
docker compose --profile core --profile graph --profile ml --profile obs up -d    # ~4.5 GB RAM at rest
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
uv run pytest platform/libs/tests/test_dag_sources.py -q             # DAG sources, static (also in CI)
docker compose exec airflow-scheduler python -m pytest /opt/latam/platform/airflow/tests -q   # DAG integrity
docker compose exec airflow-scheduler airflow dags list-import-errors     # must print no errors
cd platform/dbt && DBT_PROFILES_DIR=. uv run dbt build                 # data tests, governance tests, unit tests
uv run python -m latam_platform.cli governance-check                   # manifest vs policies
cd platform/infra/terraform/gcp/envs/mx && terraform init -backend=false && terraform validate
```
The DAG integrity tests need pytest in the Airflow image: if `No module named pytest`, the image predates the
Dockerfile, rebuild it (§1).
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

The memory **limits** of `core` alone add up to 7.9 GB (scheduler 4 GB), and every extra profile adds 1–4 GB of
limits, so a dbt run with every profile up can push the VM to its ceiling. Measured at rest on 2026-10-04:
`core` 2.5 GB; plus `graph`, `ml` and Marquez 4.1 GB. Start `graph`, `ml` and `obs` after a heavy dbt run, or give
Docker more memory.

## 8 · Lossless bronze (bronze of record)
Every landed record is stored with every field as its original text in `data/lake/bronze_raw` (facts after the
stream cutoff in `holdout_raw`), after proving that each file rebuilds byte-exact from what will be stored. The
`bronze_build` DAG runs this as `build_raw` → `verify_raw` → `seal_raw`. Outside Airflow, from `platform/`:

```bash
uv run python -m latam_platform.cli bronze-raw-build --workers 8                  # prove + write every file
uv run python -m latam_platform.cli bronze-raw-verify                             # rebuild every file from storage
uv run python -m latam_platform.cli bronze-raw-build --source backup_20260831     # the quarantined copy
uv run python -m latam_platform.cli bronze-raw-verify --source backup_20260831
```

`bronze-raw-verify` exits non-zero if any landed file cannot be rebuilt byte-exact from what is stored. The build
runs a process pool (`--workers`); in the scheduler container the DAG uses 2 workers.

## 9 · Contract-driven silver, findings and held partitions
Silver types lossless bronze against the reviewed **source contracts** in `platform/contracts/sources/<table>.yml`
(types, accepted formats, key patterns, vocabularies and variants, scale baselines). From them,
`scripts/generate_silver_from_contracts.py` writes the `typed_*` models, the partition profile, the cell findings
and the seed `source_contract_columns`; a platform test fails CI when they are out of date. To change a contract:

```bash
# edit platform/contracts/sources/<table>.yml in a pull request, then from platform/dbt:
uv run python scripts/generate_silver_from_contracts.py           # regenerate (or --check)
DBT_PROFILES_DIR=. uv run dbt build -s +dq_rule_summary            # typed, breaker, findings, summary
```

**Findings.** Every cell that breaks its contract is one row of `audit.dq_cell_findings` (lineage: `source_file`,
`record_no`, `record_sha256`; personal data only as a shape), summarised per rule and table in
`audit.dq_rule_summary` (C01–C10) next to the row rules (R01–R27). The `dq_gate` task blocks on enforced
severity-A rules above their SLO.

**Held partitions.** `audit.dq_partition_holds` lists partitions whose schema drifted (`audit.dq_schema_drift`
says which check, column, observed value and threshold). Their rows stay in bronze and in `silver.typed_*`; staging
and everything built on it exclude them. The `drift_holds` task opens one `schema_drift_partition_held` trigger per
new hold (24 h review deadline). To release a reviewed partition, add a row to `seeds/dq_partition_releases.csv`
(`released_by` and `approved_by` must be different people) in a pull request and rebuild; if the change is
legitimate and permanent, update the contract instead. Phase 4 moves releases to the four-eyes ledger flow.

**Retiring typed bronze (once, after this change is deployed).** The typed bronze is no longer built or read.
Move it into the read-only archive (nothing is copied or deleted; per-zone SHA-256 recorded in
`ARCHIVE_*.json` and the audit ledger), then re-parse the dbt manifest Cosmos renders. Docker Desktop bind mounts
ignore `chmod` from a container: the command checks the permissions held and, if not, exits with the host command
to run (`chmod -R a-w data/lake/archive/bronze_typed_v1`).

```bash
docker compose exec airflow-scheduler /opt/airflow/platform-venv/bin/python -m latam_platform.cli archive-typed-bronze
docker compose exec airflow-scheduler bash -lc 'cd /opt/latam/platform/dbt && /opt/airflow/dbt-venv/bin/dbt parse --quiet --target-path target-airflow'
```

## 10 · Deploying a merged change
The stack serves whatever checkout it was started from (the `develop` worktree). To deploy a merged change:

1. **Wait until no run is active.** A run parked on a human approval (for example `ml_fraud_ensemble` waiting for
   `model_risk_approval`) does not count:
   ```bash
   docker compose exec airflow-scheduler python -c "
   from airflow.settings import Session; from sqlalchemy import text
   print(Session().execute(text(\"select dag_id, state from dag_run where state in ('running','queued')\")).fetchall())"
   ```
   The daily `landing_ingest` (00:00 UTC) triggers the whole chain, which takes about an hour.
2. **Update the checkout:** `git -C <stack worktree> pull --ff-only`. `latam_platform` is loaded from the mount
   through a `.pth` file, so library, DAG and dbt changes need no image rebuild (Dockerfile changes do, §1).
3. **Re-parse the manifest** Cosmos renders:
   `docker compose exec airflow-scheduler bash -lc 'cd /opt/latam/platform/dbt && /opt/airflow/dbt-venv/bin/dbt parse --quiet --target-path target-airflow'`
4. **Check the DAGs load:** `airflow dags list-import-errors` is empty.
5. **Run and check:** trigger `dbt_lakehouse`, then read the return values of `drift_holds` (held partitions),
   `dq_gate` (blocking rules) and `governance_gate` (errors) in the run.

If Docker Desktop restarts during a run, Airflow resumes it when the stack is back; clear a task only if it stays
`running` past the heartbeat timeout (5 minutes).
