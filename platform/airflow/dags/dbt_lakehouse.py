"""dbt lakehouse build with Cosmos: seeds -> silver -> snapshots -> gold -> aggregates (day, cell, hour) ->
features/graph/knowledge -> privacy/serving -> audit. This DAG is scope ALL; lakehouse_scoped builds each country.

Each layer is a Cosmos task group (one Airflow task per model, tests after each group), so lineage, retries and
failures are visible per model; Cosmos emits OpenLineage events to Marquez. All tasks share the single-writer
DuckDB pool. Silver types lossless bronze against the reviewed source contracts; a bronze partition whose schema
drifted is held (audit.dq_partition_holds) and kept out of staging and everything built on it. After the build:
  * drift holds: one compliance trigger (schema_drift_partition_held) per newly held partition;
  * data-quality gate: no enforced severity-A rule above its SLO (audit.dq_rule_summary, row and cell rules);
  * governance gate: manifest check (owners, data classes, residency, contracts) from platform/policies.
"""

from __future__ import annotations

import pendulum
from airflow.sdk import dag, task
from cosmos import DbtTaskGroup, ExecutionConfig, ProfileConfig, ProjectConfig, RenderConfig
from cosmos.constants import LoadMode, TestBehavior

from latam_dags.common import (
    AUDIT_CALLBACKS,
    BRONZE,
    CORRECTIONS,
    DBT_BIN,
    DBT_DIR,
    DEFAULT_ARGS,
    DUCKDB_POOL,
    LAKEHOUSE,
    LAYERS,
    PLATFORM_PY,
)

PROJECT = ProjectConfig(
    dbt_project_path=DBT_DIR,
    manifest_path=f"{DBT_DIR}/target-airflow/manifest.json",
    dbt_vars={"as_of_date": "2026-05-17"},
    install_dbt_deps=False,
)
PROFILE = ProfileConfig(
    profile_name="latam_bank", target_name="dev", profiles_yml_filepath=f"{DBT_DIR}/profiles.yml"
)
EXECUTION = ExecutionConfig(dbt_executable_path=DBT_BIN)


def layer(group_id: str, select: list[str]) -> DbtTaskGroup:
    return DbtTaskGroup(
        group_id=group_id,
        project_config=PROJECT,
        profile_config=PROFILE,
        execution_config=EXECUTION,
        render_config=RenderConfig(
            load_method=LoadMode.DBT_MANIFEST, select=select, test_behavior=TestBehavior.AFTER_ALL
        ),
        # append_env: Cosmos runs dbt from a temp copy of the project, so it must inherit the container's
        # absolute LATAM_LAKE_DIR / LATAM_DUCKDB_PATH instead of resolving relative paths from the copy.
        operator_args={"pool": DUCKDB_POOL, "full_refresh": False, "append_env": True},
        default_args={"retries": 1},
    )


@dag(
    dag_id="dbt_lakehouse",
    schedule=(BRONZE | CORRECTIONS),  # new bronze, or an approved data correction
    start_date=pendulum.datetime(2026, 9, 1, tz="UTC"),
    catchup=False,
    max_active_runs=1,
    default_args={**DEFAULT_ARGS, "owner": "analytics-engineering"},
    tags=["dbt", "silver", "gold", "governance"],
    doc_md=__doc__,
    **AUDIT_CALLBACKS,
)
def dbt_lakehouse():
    groups = [layer(name, sel) for name, sel in LAYERS.items()]
    for a, b in zip(groups, groups[1:]):
        a >> b

    @task.external_python(python=PLATFORM_PY, expect_airflow=False, pool=DUCKDB_POOL)
    def drift_holds(lineage_run_id: str) -> dict:
        """Open a review for every partition the circuit breaker newly held. Never fails the run: a held
        partition is already contained (its rows are out of staging); the review decides its release."""
        from latam_platform import drift_holds, ops

        with ops.audit() as a:
            out = drift_holds.raise_reviews(
                ops.lakehouse(read_only=True), a, drift_holds.load_trigger()
            )
        ops.ledger("dq.drift_holds_evaluated", "audit.dq_partition_holds", out, lineage_run_id)
        return out

    @task.external_python(python=PLATFORM_PY, expect_airflow=False, pool=DUCKDB_POOL)
    def dq_gate(lineage_run_id: str) -> dict:
        from latam_platform import ops

        con = ops.lakehouse(read_only=True)
        rows = con.sql("""select rule_id, severity, rate_pct, max_rate_pct, enforce_in_dev
                          from audit.dq_rule_summary where slo_breached""").fetchall()
        blocking = [r for r in rows if r[1] == "A" and r[4]]
        summary = {
            "breaches": [list(map(str, r)) for r in rows],
            "blocking": [r[0] for r in blocking],
        }
        ops.ledger("dq.gate_evaluated", "audit.dq_rule_summary", summary, lineage_run_id)
        if blocking:
            raise RuntimeError(f"severity-A data-quality SLO breached: {summary['blocking']}")
        return summary

    @task.external_python(python=PLATFORM_PY, expect_airflow=False, outlets=[LAKEHOUSE])
    def governance_gate(lineage_run_id: str) -> dict:
        from latam_platform import governance, ops

        rep = governance.check_manifest(governance.DBT_DIR / "target-airflow" / "manifest.json")
        out = {"checked_models": rep.checked_models, "errors": rep.errors, "warnings": rep.warnings}
        ops.ledger("governance.gate_evaluated", "dbt manifest", out, lineage_run_id)
        if not rep.ok:
            raise RuntimeError(f"governance check failed: {rep.errors}")
        return out

    (
        groups[-1]
        >> drift_holds(lineage_run_id="{{ run_id }}")
        >> dq_gate(lineage_run_id="{{ run_id }}")
        >> governance_gate(lineage_run_id="{{ run_id }}")
    )


dbt_lakehouse()
