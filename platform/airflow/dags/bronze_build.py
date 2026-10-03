"""Bronze build: landing CSV -> typed, partitioned, append-only Parquet with reconciliation.

Triggered by the landing asset. One mapped task per table (sequential: DuckDB memory is capped per task).
A table that does not reconcile (loaded + rejected != landing records) or would rewrite an existing partition
fails the run. Partition manifests (digests) are written to the object-locked bucket and the ledger.
"""

from __future__ import annotations

import pendulum
from airflow.sdk import dag, task

from latam_dags.common import (
    AUDIT_CALLBACKS,
    BRONZE,
    DEFAULT_ARGS,
    DUCKDB_POOL,
    LANDING,
    PLATFORM_PY,
)

TABLES = [
    "transactions",
    "digital_events",
    "call_center_interactions",
    "call_transcripts",
    "satisfaction_surveys",
    "complaints",
    "campaign_sends",
    "customers",
    "products",
    "branches",
    "service_agents",
    "marketing_campaigns",
    "daily_exchange_rates",
]


@dag(
    dag_id="bronze_build",
    schedule=[LANDING],
    start_date=pendulum.datetime(2026, 9, 1, tz="UTC"),
    catchup=False,
    max_active_runs=1,
    default_args=DEFAULT_ARGS,
    tags=["ingestion", "bronze", "audit"],
    doc_md=__doc__,
    **AUDIT_CALLBACKS,
)
def bronze_build():
    @task.external_python(python=PLATFORM_PY, expect_airflow=False)
    def lake_init() -> list[str]:
        from latam_platform import cli

        return cli.cmd_lake_init(None)

    @task.external_python(python=PLATFORM_PY, expect_airflow=False, pool=DUCKDB_POOL)
    def build(table: str, lineage_run_id: str) -> dict:
        from latam_platform import config, ops
        from latam_platform.lakehouse import bronze, landing

        manifest = landing.latest_manifest() or {"files": []}
        lines = {f["path"]: f["lines"] for f in manifest["files"]}
        res = bronze.build_table(config.TABLES[table], f"bronze-{lineage_run_id}", lines or None)
        ops.ledger("bronze.table_built", f"bronze/{table}", res, lineage_run_id)
        if not res.get("reconciled", True):
            raise RuntimeError(f"{table} does not reconcile with landing: {res}")
        return res

    @task.external_python(python=PLATFORM_PY, expect_airflow=False, pool=DUCKDB_POOL)
    def quarantine_backup(lineage_run_id: str) -> list:
        from latam_platform import ops
        from latam_platform.lakehouse import bronze

        out = bronze.build_quarantine_backup(f"quarantine-{lineage_run_id}")
        ops.ledger(
            "quarantine.backup_refreshed",
            "quarantine/backup_20260831",
            {"tables": out},
            lineage_run_id,
        )
        return out

    @task.external_python(python=PLATFORM_PY, expect_airflow=False, outlets=[BRONZE])
    def seal_manifests(results: list, lineage_run_id: str) -> str:
        import json

        from latam_platform import config, ops

        doc = {
            "run_id": lineage_run_id,
            "tables": results,
            "manifests": {
                p.stem: json.loads(p.read_text())
                for p in (config.MANIFESTS / "bronze").glob("*.json")
            },
        }
        uri = ops.worm_put_json("bronze-worm", f"manifests/bronze/{lineage_run_id}.json", doc)
        ops.ledger(
            "bronze.manifests_sealed",
            "bronze",
            {"worm_uri": uri, "tables": len(results)},
            lineage_run_id,
        )
        return uri

    results = build.partial(lineage_run_id="{{ run_id }}").expand(table=TABLES)
    lake_init() >> results
    seal_manifests(results, lineage_run_id="{{ run_id }}") << quarantine_backup(
        lineage_run_id="{{ run_id }}"
    )


bronze_build()
