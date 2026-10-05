"""Country scope lakehouses: the dbt_lakehouse pipeline, laterally, for each market (ADR-016, ADR-020).

One DAG per market (lakehouse_mx, lakehouse_co, lakehouse_ar), generated from the same layer list as dbt_lakehouse
(scope ALL):
  cut_bronze  ->  seeds -> silver -> snapshots -> gold -> aggregates (day, cell, hour)
              ->  features/graph/knowledge -> privacy/serving -> audit  ->  drift holds -> quality gate -> governance

`cut_bronze` writes the market's lossless subset of bronze (latam_platform.scopes): customers by country, every
customer-owned table by customer, anonymous digital events by IP country, shared reference tables linked. dbt then
runs the same compiled project against the scope's lake and its own DuckDB file (LATAM_LAKE_DIR, LATAM_DUCKDB_PATH),
so a scope never shares the single writer or the gates of another. The tasks still use the DuckDB pool, which
serialises heavy DuckDB work inside the memory-capped scheduler; give the pool more slots where memory allows.
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
    LAYERS,
    PLATFORM_PY,
    SCOPE_MARKETS,
    SCOPES_DIR,
    scope_lakehouse,
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


def scope_env(code: str) -> dict[str, str]:
    root = f"{SCOPES_DIR}/{code.lower()}"
    return {"LATAM_LAKE_DIR": f"{root}/lake", "LATAM_DUCKDB_PATH": f"{root}/lakehouse.duckdb"}


def layer(code: str, group_id: str, select: list[str]) -> DbtTaskGroup:
    return DbtTaskGroup(
        group_id=group_id,
        project_config=PROJECT,
        profile_config=PROFILE,
        execution_config=EXECUTION,
        render_config=RenderConfig(
            load_method=LoadMode.DBT_MANIFEST, select=select, test_behavior=TestBehavior.AFTER_ALL
        ),
        # dbt re-renders every node at run time, so the scope's lake and lakehouse paths apply to sources and models
        operator_args={
            "pool": DUCKDB_POOL,
            "full_refresh": False,
            "append_env": True,
            "env": scope_env(code),
        },
        default_args={"retries": 1},
    )


def build(code: str):
    @dag(
        dag_id=f"lakehouse_{code.lower()}",
        schedule=(BRONZE | CORRECTIONS),
        start_date=pendulum.datetime(2026, 9, 1, tz="UTC"),
        catchup=False,
        max_active_runs=1,
        default_args={**DEFAULT_ARGS, "owner": "analytics-engineering"},
        tags=["dbt", "scope", code.lower(), "governance"],
        doc_md=__doc__,
        **AUDIT_CALLBACKS,
    )
    def lakehouse_scope():
        @task.external_python(python=PLATFORM_PY, expect_airflow=False, pool=DUCKDB_POOL)
        def cut_bronze(scope: str, lineage_run_id: str) -> dict:
            """Cut the scope's lossless subset of bronze (idempotent: a finished cut is reused)."""
            from latam_platform import ops, scopes

            rows = scopes.cut(scope, force=True)
            out = {
                "scope": scope,
                "tables": len(rows),
                "rows_kept": sum(r["rows_kept"] for r in rows),
            }
            ops.ledger("scope.bronze_cut", f"scopes/{scope.lower()}", out, lineage_run_id)
            return out

        @task.external_python(python=PLATFORM_PY, expect_airflow=False, pool=DUCKDB_POOL)
        def drift_holds(scope: str, lineage_run_id: str) -> dict:
            from latam_platform import drift_holds, ops, scopes

            con = ops.lakehouse(read_only=True, path=scopes.lakehouse_path(scope))
            with ops.audit() as a:
                out = drift_holds.raise_reviews(con, a, drift_holds.load_trigger())
            ops.ledger(
                "dq.drift_holds_evaluated", f"{scope}:audit.dq_partition_holds", out, lineage_run_id
            )
            return out

        @task.external_python(python=PLATFORM_PY, expect_airflow=False, pool=DUCKDB_POOL)
        def dq_gate(scope: str, lineage_run_id: str) -> dict:
            from latam_platform import ops, scopes

            con = ops.lakehouse(read_only=True, path=scopes.lakehouse_path(scope))
            rows = con.sql("""select rule_id, severity, rate_pct, max_rate_pct, enforce_in_dev
                              from audit.dq_rule_summary where slo_breached""").fetchall()
            blocking = [r for r in rows if r[1] == "A" and r[4]]
            summary = {
                "scope": scope,
                "breaches": [list(map(str, r)) for r in rows],
                "blocking": [r[0] for r in blocking],
            }
            ops.ledger(
                "dq.gate_evaluated", f"{scope}:audit.dq_rule_summary", summary, lineage_run_id
            )
            if blocking:
                raise RuntimeError(
                    f"{scope}: severity-A data-quality SLO breached: {summary['blocking']}"
                )
            return summary

        @task.external_python(
            python=PLATFORM_PY, expect_airflow=False, outlets=[scope_lakehouse(code)]
        )
        def governance_gate(scope: str, lineage_run_id: str) -> dict:
            from latam_platform import governance, ops

            rep = governance.check_manifest(governance.DBT_DIR / "target-airflow" / "manifest.json")
            out = {
                "scope": scope,
                "checked_models": rep.checked_models,
                "errors": rep.errors,
                "warnings": rep.warnings,
            }
            ops.ledger("governance.gate_evaluated", "dbt manifest", out, lineage_run_id)
            if not rep.ok:
                raise RuntimeError(f"governance check failed: {rep.errors}")
            return out

        groups = [layer(code, name, sel) for name, sel in LAYERS.items()]
        cut = cut_bronze(scope=code, lineage_run_id="{{ run_id }}")
        cut >> groups[0]
        for a, b in zip(groups, groups[1:], strict=False):
            a >> b
        (
            groups[-1]
            >> drift_holds(scope=code, lineage_run_id="{{ run_id }}")
            >> dq_gate(scope=code, lineage_run_id="{{ run_id }}")
            >> governance_gate(scope=code, lineage_run_id="{{ run_id }}")
        )

    return lakehouse_scope()


for _code in SCOPE_MARKETS:
    build(_code)
