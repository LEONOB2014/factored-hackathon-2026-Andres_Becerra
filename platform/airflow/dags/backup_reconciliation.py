"""Backup reconciliation control (C1): any copy that claims to be a backup must match the source.

Runs the dbt audit models over the lossless quarantined backup (records compared as landed text) and fails
loudly if keys or record hashes differ.
On this dataset it is EXPECTED to fail: data_backup_20260831 is not a faithful backup (see docs/strategy/01).
The failure is recorded as an integrity incident in the ledger, which is exactly the control's purpose.
"""

from __future__ import annotations

import pendulum
from airflow.providers.standard.operators.bash import BashOperator
from airflow.sdk import dag, task

from latam_dags.common import (
    AUDIT_CALLBACKS,
    BRONZE,
    DBT_BIN,
    DBT_DIR,
    DEFAULT_ARGS,
    DUCKDB_POOL,
    PLATFORM_PY,
)


@dag(
    dag_id="backup_reconciliation",
    schedule=[BRONZE],
    start_date=pendulum.datetime(2026, 9, 1, tz="UTC"),
    catchup=False,
    max_active_runs=1,
    default_args={**DEFAULT_ARGS, "owner": "security-and-audit", "retries": 0},
    tags=["audit", "integrity", "backup"],
    doc_md=__doc__,
    **AUDIT_CALLBACKS,
)
def backup_reconciliation():
    run_models = BashOperator(
        task_id="run_reconciliation_models",
        bash_command=f"cd {DBT_DIR} && {DBT_BIN} run --select audit_backup_reconciliation --quiet",
        pool=DUCKDB_POOL,
    )

    @task.external_python(python=PLATFORM_PY, expect_airflow=False, pool=DUCKDB_POOL)
    def evaluate(lineage_run_id: str) -> dict:
        from latam_platform import ops

        con = ops.lakehouse(read_only=True)
        rows = con.sql("select * from audit.audit_backup_reconciliation").df().to_dict("records")
        unfaithful = [
            r["table_name"]
            for r in rows
            if r["only_main"] or r["only_backup"] or r["shared_changed"]
        ]
        ops.ledger(
            "backup.reconciliation_failed" if unfaithful else "backup.reconciliation_passed",
            "quarantine/backup_20260831_raw",
            {"tables": rows, "unfaithful": unfaithful},
            lineage_run_id,
        )
        if unfaithful:
            raise RuntimeError(f"backup is not a faithful copy of: {unfaithful}")
        return {"tables": len(rows)}

    run_models >> evaluate(lineage_run_id="{{ run_id }}")


backup_reconciliation()
