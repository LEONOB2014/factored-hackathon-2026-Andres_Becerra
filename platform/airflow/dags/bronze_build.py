"""Bronze build: landing CSV -> lossless bronze of record (partitioned, append-only Parquet).

Triggered by the landing asset. One mapped task per table (sequential: DuckDB memory is capped per task).

Every record with every field as its original text. Each file is proven byte-exact against the landing
manifest before it is written (build_raw), then rebuilt from the stored Parquet and checked again
(verify_raw); any mismatch fails the run. New partitions and the proof manifests are copied to the
object-locked bucket (seal_raw), then the partition manifests are sealed and the bronze asset published.
Silver types this zone against the reviewed source contracts (dbt models/silver/typed). The typed bronze
this DAG used to build is retired and archived read-only (docs/platform/runbook.md §9).

Every step is recorded in the audit ledger.
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

    @task.external_python(python=PLATFORM_PY, expect_airflow=False, outlets=[BRONZE])
    def seal_manifests(lineage_run_id: str) -> str:
        import json

        from latam_platform import config, ops

        doc = {  # per-partition record counts and digests of the lossless zones (append-only)
            "run_id": lineage_run_id,
            "manifests": {
                p.stem: json.loads(p.read_text())
                for p in (config.MANIFESTS / "bronze_raw").glob("*.json")
            },
        }
        uri = ops.worm_put_json(
            "bronze-worm", f"manifests/bronze_raw_partitions/{lineage_run_id}.json", doc
        )
        ops.ledger(
            "bronze.manifests_sealed",
            "bronze",
            {"worm_uri": uri, "tables": len(doc["manifests"])},
            lineage_run_id,
        )
        return uri

    @task.external_python(python=PLATFORM_PY, expect_airflow=False, pool=DUCKDB_POOL)
    def build_raw(table: str, lineage_run_id: str) -> dict:
        from latam_platform import config, ops
        from latam_platform.lakehouse import bronze_raw

        res = bronze_raw.build_table_raw(
            config.TABLES[table], f"bronze-raw-{lineage_run_id}", workers=2
        )
        ops.ledger("bronze_raw.table_built", f"bronze_raw/{table}", res, lineage_run_id)
        return res

    @task.external_python(python=PLATFORM_PY, expect_airflow=False, pool=DUCKDB_POOL)
    def verify_raw(table: str, lineage_run_id: str) -> dict:
        from latam_platform import config, ops
        from latam_platform.lakehouse import bronze_raw

        res = bronze_raw.verify_table_raw(config.TABLES[table])
        ops.ledger("bronze_raw.verified", f"bronze_raw/{table}", res, lineage_run_id)
        if not res["verified"]:
            raise RuntimeError(f"{table}: lossless bronze does not rebuild the landed files: {res}")
        return res

    @task.external_python(python=PLATFORM_PY, expect_airflow=False, pool=DUCKDB_POOL)
    def quarantine_backup_raw(lineage_run_id: str) -> list:
        from latam_platform import config, ops
        from latam_platform.lakehouse import bronze_raw

        out = []
        for t in config.TABLES.values():
            built = bronze_raw.build_table_raw(
                t, f"quarantine-raw-{lineage_run_id}", source="backup_20260831", workers=2
            )
            if built.get("status") == "absent":
                out.append(built)
                continue
            checked = bronze_raw.verify_table_raw(t, source="backup_20260831")
            if not checked["verified"]:
                raise RuntimeError(f"backup {t.name}: lossless copy does not rebuild: {checked}")
            out.append({**built, "verified": True})
        ops.ledger(
            "bronze_raw.backup_quarantined",
            "quarantine/backup_20260831_raw",
            {"tables": out},
            lineage_run_id,
        )
        return out

    @task.external_python(python=PLATFORM_PY, expect_airflow=False)
    def seal_raw(lineage_run_id: str) -> dict:
        from latam_platform import ops
        from latam_platform.lakehouse import bronze_raw

        res = bronze_raw.worm_sync(ops.s3(), "bronze-worm", lineage_run_id)
        ops.ledger("bronze_raw.sealed", "bronze_raw", res, lineage_run_id)
        return res

    init = lake_init()
    raw_built = build_raw.partial(lineage_run_id="{{ run_id }}").expand(table=TABLES)
    raw_verified = verify_raw.partial(lineage_run_id="{{ run_id }}").expand(table=TABLES)
    raw_sealed = seal_raw(lineage_run_id="{{ run_id }}")
    init >> raw_built >> raw_verified >> raw_sealed
    init >> quarantine_backup_raw(lineage_run_id="{{ run_id }}") >> raw_sealed

    # the bronze asset is published only once the lossless copy is proven, verified and sealed
    raw_sealed >> seal_manifests(lineage_run_id="{{ run_id }}")


bronze_build()
