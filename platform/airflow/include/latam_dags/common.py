"""Shared building blocks for the LATAM platform DAGs.

* Two isolated runtimes: Airflow itself (scheduling, providers) and /opt/airflow/platform-venv
  (latam_platform + ML/KB/privacy libs) used through @task.external_python. dbt runs from its own venv.
* Assets give data-aware scheduling (landing -> bronze -> lakehouse -> serving/graph/ml).
* Every DAG run writes start/finish events to the hash-chained audit ledger (pg-audit) via callbacks.
"""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime, timedelta

from airflow.sdk import Asset

PLATFORM_PY = "/opt/airflow/platform-venv/bin/python"
DBT_BIN = "/opt/airflow/dbt-venv/bin/dbt"
REPO = "/opt/latam"
DBT_DIR = f"{REPO}/platform/dbt"
LAKE = f"{REPO}/data/lake"

# ------------------------------------------------------------------------------------------- assets
LANDING = Asset("lake://landing/raw")
BRONZE = Asset("lake://bronze")
LAKEHOUSE = Asset("duckdb://lakehouse/gold")
SERVING = Asset("postgres://pg-core:5432/bank_serving/serving/publication_log")
KNOWLEDGE = Asset("postgres://pg-core:5432/knowledge/kb/active_set_snapshot")
GRAPH = Asset("neo4j://neo4j/latam")
FRAUD_MODEL = Asset("mlflow://models/fraud_ensemble")
STREAM_DECISIONS = Asset("postgres://pg-core:5432/bank_serving/decisions/fraud_decision_log")

DEFAULT_ARGS = {
    "owner": "data-platform",
    "retries": 1,
    "retry_delay": timedelta(minutes=2),
}

DUCKDB_POOL = (
    "duckdb_lakehouse"  # one slot: DuckDB allows one writer, and heavy DuckDB jobs must not
)
# run concurrently inside the memory-capped scheduler (LocalExecutor)


def _ledger_event(event_type: str, context, extra: dict | None = None) -> None:
    """Append a run event to the audit ledger. Never fails the task: audit outages raise a separate alert."""
    try:
        import psycopg2

        dag_run = context.get("dag_run")
        ti = context.get("ti") or context.get("task_instance")
        conn = psycopg2.connect(
            host=os.environ.get("LATAM_PG_AUDIT_HOST", "pg-audit"),
            dbname="audit",
            user="audit_writer",
            password=os.environ["AUDIT_WRITER_PASSWORD"],
            connect_timeout=5,
        )
        with conn, conn.cursor() as cur:
            payload = {
                "dag_id": dag_run.dag_id if dag_run else None,
                "run_id": dag_run.run_id if dag_run else None,
                "task_id": getattr(ti, "task_id", None),
                "try_number": getattr(ti, "try_number", None),
                "state": str(getattr(ti, "state", None)),
                **(extra or {}),
            }
            cur.execute(
                "INSERT INTO ledger.event (event_time, actor, event_type, subject_ref, lineage_run_id, payload) "
                "VALUES (%s, %s, %s, %s, %s, %s)",
                (
                    datetime.now(UTC),
                    "svc-airflow",
                    event_type,
                    payload["dag_id"],
                    payload["run_id"],
                    json.dumps(payload, default=str),
                ),
            )
        conn.close()
    except Exception as exc:  # pragma: no cover
        print(f"[audit] ledger write failed: {exc!r}")


def on_dag_success(context):
    _ledger_event("airflow.dag_run_succeeded", context)


def on_dag_failure(context):
    _ledger_event("airflow.dag_run_failed", context, {"reason": str(context.get("reason"))})


def on_task_failure(context):
    _ledger_event(
        "airflow.task_failed", context, {"exception": repr(context.get("exception"))[:500]}
    )


AUDIT_CALLBACKS = {"on_success_callback": on_dag_success, "on_failure_callback": on_dag_failure}
