"""Real-time fraud demo: replay the holdout slice through Redpanda -> Flink -> scorer and prove parity.

1. export the enriched holdout (plus a 7-day warm-up so Flink windows see the same history as batch);
2. create topics; submit the Flink SQL job through the SQL Gateway (idempotent per run);
3. replay logins + transactions in event-time order at `seconds_per_day` (e.g. one data day per 20 s);
4. wait until the scorer has decided every replayed transaction;
5. parity: Flink window features must equal features.feat_fraud_stream_parity (computed by dbt with the same
   macro over history + holdout) for every transaction — any mismatch fails the run;
6. report latency/decision statistics and write everything to the audit ledger.
Requires profiles core, ml, stream and an approved fraud_ensemble@champion.
"""

from __future__ import annotations

import pendulum
from airflow.sdk import Param, dag, task

from latam_dags.common import (
    AUDIT_CALLBACKS,
    DEFAULT_ARGS,
    DUCKDB_POOL,
    PLATFORM_PY,
    STREAM_DECISIONS,
)


@dag(
    dag_id="stream_demo",
    schedule=None,
    start_date=pendulum.datetime(2026, 9, 1, tz="UTC"),
    catchup=False,
    max_active_runs=1,
    default_args={**DEFAULT_ARGS, "owner": "ml-engineering", "retries": 0},
    tags=["stream", "flink", "redpanda", "fraud", "demo"],
    params={
        "days": Param(
            3, type="integer", minimum=1, maximum=30, description="Holdout days to replay"
        ),
        "seconds_per_day": Param(
            20, type="number", minimum=1, description="Wall seconds per data day"
        ),
    },
    doc_md=__doc__,
    **AUDIT_CALLBACKS,
)
def stream_demo():
    @task.external_python(python=PLATFORM_PY, expect_airflow=False, pool=DUCKDB_POOL)
    def export(days: str) -> dict:
        from latam_platform import ops, stream

        return stream.export_holdout(ops.lakehouse(read_only=True), days=int(days))

    @task.external_python(python=PLATFORM_PY, expect_airflow=False)
    def setup(exported: dict) -> list:
        import os

        from latam_platform import ops, stream

        with ops.pg("bank_serving") as pg:  # fresh run: clear previous window features
            pg.execute("TRUNCATE online_features.tx_window_features")
        topics = stream.ensure_topics(os.environ["LATAM_KAFKA_BOOTSTRAP"])
        return stream.submit_flink_sql(
            "http://flink-sql-gateway:8083",
            "/opt/latam/platform/flink/sql/fraud_features.sql",
            {"SCORER_DB_PASSWORD": os.environ["SCORER_DB_PASSWORD"]},
        ) + [{"topics": topics}]

    @task.external_python(python=PLATFORM_PY, expect_airflow=False)
    def replay(submitted: list, seconds_per_day: str) -> dict:
        import os

        from latam_platform import stream

        return stream.replay(
            os.environ["LATAM_KAFKA_BOOTSTRAP"], seconds_per_day=float(seconds_per_day)
        )

    @task.external_python(python=PLATFORM_PY, expect_airflow=False, outlets=[STREAM_DECISIONS])
    def wait_and_verify(replayed: dict, exported: dict, lineage_run_id: str) -> dict:
        import time

        from latam_platform import ops, stream

        expected = exported["transactions"]
        with ops.pg("bank_serving") as pg:
            for _ in range(180):
                feats = pg.execute(
                    "SELECT count(*) FROM online_features.tx_window_features"
                ).fetchone()[0]
                if feats >= expected:
                    break
                time.sleep(5)
            time.sleep(10)
            stats = pg.execute("""SELECT count(*), percentile_cont(0.5) WITHIN GROUP (ORDER BY latency_ms),
                                         percentile_cont(0.95) WITHIN GROUP (ORDER BY latency_ms),
                                         count(*) FILTER (WHERE decision = 'STEP_UP'), count(*) FILTER (WHERE decision = 'DECLINE')
                                  FROM decisions.fraud_decision_log
                                  WHERE event_ts >= (SELECT min(anchor_ts) FROM online_features.tx_window_features)""").fetchone()
            par = stream.parity(ops.lakehouse(read_only=True), pg)
        report = {
            "replayed": replayed,
            "expected_transactions": expected,
            "flink_feature_rows": feats,
            "decisions": stats[0],
            "latency_ms_p50": stats[1],
            "latency_ms_p95": stats[2],
            "step_up": stats[3],
            "decline": stats[4],
            "parity": par,
        }
        ops.ledger(
            "stream.demo_verified" if par["mismatches"] == 0 else "stream.parity_failed",
            "fraud-online-features",
            report,
            lineage_run_id,
        )
        if par["mismatches"] or par["compared"] < expected:
            raise RuntimeError(f"stream/batch parity failed: {par}")
        return report

    exp = export(days="{{ params.days }}")
    rep = replay(setup(exp), seconds_per_day="{{ params.seconds_per_day }}")
    wait_and_verify(rep, exp, lineage_run_id="{{ run_id }}")


stream_demo()
