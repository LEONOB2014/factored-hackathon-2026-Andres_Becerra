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
    "dq_correction_review",
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
            if t.task_id.split(".")[-1]
            in (
                "publish",
                "drift_holds",
                "dq_gate",
                "build_raw",
                "verify_raw",
                "quarantine_backup_raw",
            )
            or t.task_type.startswith("DbtRun")
        ]
        assert heavy and all(t.pool == "duckdb_lakehouse" for t in heavy), dag_id


def test_lossless_bronze_is_proven_and_sealed_before_the_bronze_asset(bag):
    dag = bag.get_dag("bronze_build")
    ids = {t.task_id for t in dag.tasks}
    assert {"build_raw", "verify_raw", "seal_raw", "quarantine_backup_raw"} <= ids
    assert "build_raw" in dag.get_task("verify_raw").upstream_task_ids
    assert "verify_raw" in dag.get_task("seal_raw").upstream_task_ids
    assert "seal_raw" in dag.get_task("seal_manifests").upstream_task_ids
    assert not ids & {"build", "quarantine_backup"}, (
        "typed bronze is retired: silver types lossless bronze"
    )


def test_drift_holds_are_raised_before_the_quality_gates(bag):
    dag = bag.get_dag("dbt_lakehouse")
    assert "drift_holds" in dag.get_task("dq_gate").upstream_task_ids
    assert "dq_gate" in dag.get_task("governance_gate").upstream_task_ids


def test_corrections_need_an_assigned_approver_and_rebuild_the_lakehouse(bag):
    dag = bag.get_dag("dq_correction_review")
    review = dag.get_task("review")
    assert type(review).__name__ == "HITLOperator"
    assert review.assigned_users, "only assigned approvers may decide"
    assert {u["id"] for u in review.assigned_users}.isdisjoint({"steward", "admin"})
    assert "review" in dag.get_task("decide_and_apply").upstream_task_ids
    assert "validate_and_stage" in review.upstream_task_ids
    assert [o.uri for o in dag.get_task("decide_and_apply").outlets] == [
        "lake://corrections/applied"
    ]
    rebuild_on = bag.get_dag("dbt_lakehouse").timetable.asset_condition.objects
    assert "lake://corrections/applied" in {a.uri for a in rebuild_on}, (
        "an applied correction rebuilds"
    )
