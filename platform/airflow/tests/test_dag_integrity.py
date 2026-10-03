"""DAG integrity tests (run inside the Airflow image: `pytest /opt/latam/platform/airflow/tests`).

Every DAG must import cleanly, declare an owner other than the default and tags, write run events to the
audit ledger, and keep lakehouse-writing tasks on the single-writer DuckDB pool.
"""

import pytest
from airflow.models import DagBag

DAG_FOLDER = "/opt/latam/platform/airflow/dags"
EXPECTED = {
    "landing_ingest",
    "bronze_build",
    "dbt_lakehouse",
    "publish_serving",
    "graph_load",
    "kb_sync",
    "ml_fraud_ensemble",
    "ml_tgn",
    "ml_federated_gnn",
    "stream_demo",
    "audit_anchor",
    "compliance_triggers",
    "dp_release",
    "monitoring_drift",
    "backup_reconciliation",
    "retention_and_erasure",
}


@pytest.fixture(scope="module")
def bag():
    return DagBag(dag_folder=DAG_FOLDER, include_examples=False)


def test_no_import_errors(bag):
    assert bag.import_errors == {}, bag.import_errors


def test_all_platform_dags_present(bag):
    assert set(bag.dag_ids) >= EXPECTED, EXPECTED - set(bag.dag_ids)


@pytest.mark.parametrize("dag_id", sorted(EXPECTED))
def test_ownership_tags_and_audit(bag, dag_id):
    dag = bag.get_dag(dag_id)
    assert dag.tags, f"{dag_id}: no tags"
    assert all(t.owner not in ("airflow", "") for t in dag.tasks), (
        f"{dag_id}: task without an owner"
    )
    assert dag.on_success_callback and dag.on_failure_callback, (
        f"{dag_id}: no audit ledger callbacks"
    )
    assert dag.max_active_runs == 1, f"{dag_id}: concurrent runs of a stateful pipeline"


def test_lakehouse_writers_use_duckdb_pool(bag):
    for dag_id in ("dbt_lakehouse", "publish_serving", "bronze_build"):
        dag = bag.get_dag(dag_id)
        heavy = [
            t
            for t in dag.tasks
            if t.task_id.split(".")[-1] in ("build", "quarantine_backup", "publish", "dq_gate")
            or t.task_type.startswith("DbtRun")
        ]
        assert heavy and all(t.pool == "duckdb_lakehouse" for t in heavy), dag_id
