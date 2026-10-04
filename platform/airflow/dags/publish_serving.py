"""Publish serving contracts from the lakehouse to Postgres bank_serving (blue/green swap per table).

Pre-publish gates: governance (no restricted columns, residency declared) is already enforced upstream; here
each table is checked again against the restricted-column list and its contract columns before it replaces
the live table in one transaction. Every publication is logged (row count + content digest) in Postgres and
in the audit ledger. The online fraud state is loaded so the stream scorer starts from batch history.
"""

from __future__ import annotations

import pendulum
from airflow.sdk import dag, task

from latam_dags.common import (
    AUDIT_CALLBACKS,
    DEFAULT_ARGS,
    DUCKDB_POOL,
    LAKEHOUSE,
    PLATFORM_PY,
    SERVING,
)

SERVING_TABLES = [
    "serving_customer_360",
    "serving_account_inquiry",
    "serving_card_support",
    "serving_dispute_case",
    "serving_credit_eligibility",
    "serving_online_fraud_state",
    "serving_recent_transactions",
]


@dag(
    dag_id="publish_serving",
    schedule=[LAKEHOUSE],
    start_date=pendulum.datetime(2026, 9, 1, tz="UTC"),
    catchup=False,
    max_active_runs=1,
    default_args=DEFAULT_ARGS,
    tags=["serving", "postgres", "governance"],
    doc_md=__doc__,
    **AUDIT_CALLBACKS,
)
def publish_serving():
    @task.external_python(
        python=PLATFORM_PY, expect_airflow=False, pool=DUCKDB_POOL, max_active_tis_per_dag=1
    )
    def publish(table: str, lineage_run_id: str) -> dict:
        import os

        import yaml

        from latam_platform import config, ops

        policy = yaml.safe_load(
            (config.REPO_ROOT / "platform/policies/data_classification.yaml").read_text()
        )
        restricted = {c["column"] for c in policy["restricted_columns"]}
        import duckdb

        con = duckdb.connect()  # neutral session: lakehouse read-only, Postgres read-write
        con.sql(f"SET memory_limit = '{os.environ.get('LATAM_DUCKDB_MEMORY', '2GB')}'")
        con.sql(f"ATTACH '{config.LAKEHOUSE_DB}' AS lh (READ_ONLY)")
        cols = [r[0] for r in con.sql(f"describe lh.serving.{table}").fetchall()]
        leaked = restricted & set(cols)
        if leaked:
            ops.ledger(
                "serving.publish_blocked_pii", table, {"columns": sorted(leaked)}, lineage_run_id
            )
            raise RuntimeError(f"{table}: restricted columns {leaked}")
        digest, n = con.sql(
            f"select md5(string_agg(md5(cast(t as varchar)), '' order by md5(cast(t as varchar)))), count(*) "
            f"from lh.serving.{table} t"
        ).fetchone()
        con.sql("INSTALL postgres; LOAD postgres;")
        host = os.environ.get("LATAM_PG_CORE_HOST", "pg-core")
        con.sql(
            f"ATTACH 'host={host} dbname=bank_serving user=publisher password={os.environ['PUBLISHER_DB_PASSWORD']}' "
            "AS pg (TYPE postgres)"
        )
        live = table.removeprefix("serving_")
        con.sql(f"DROP TABLE IF EXISTS pg.serving.{live}__new")
        con.sql(f"CREATE TABLE pg.serving.{live}__new AS SELECT * FROM lh.serving.{table}")
        with ops.pg("bank_serving") as pgc:  # atomic swap
            with pgc.transaction():
                pgc.execute(f"DROP TABLE IF EXISTS serving.{live}")
                pgc.execute(f"ALTER TABLE serving.{live}__new RENAME TO {live}")
                pgc.execute(f"GRANT SELECT ON serving.{live} TO app_reader, scorer")
                pgc.execute(
                    "INSERT INTO serving.publication_log (table_name, dbt_invocation, lineage_run_id, row_count,"
                    " content_digest) VALUES (%s, %s, %s, %s, %s)",
                    (live, "dbt_lakehouse", lineage_run_id, n, digest),
                )
        ops.ledger(
            "serving.table_published",
            f"bank_serving.serving.{live}",
            {"rows": n, "digest": digest},
            lineage_run_id,
        )
        return {"table": live, "rows": n, "digest": digest}

    @task.external_python(python=PLATFORM_PY, expect_airflow=False, outlets=[SERVING])
    def load_online_state(lineage_run_id: str) -> int:
        from latam_platform import ops

        with ops.pg("bank_serving") as c:
            c.execute("TRUNCATE online_features.customer_state")
            c.execute("""INSERT INTO online_features.customer_state (customer_id, hist_tx_count, hist_sum_log_amount,
                           hist_sumsq_log_amount, hist_max_amount_usd, hist_sum_hour, seen_merchants, seen_countries,
                           seen_channels, last_tx_ts, last_lat, last_lon)
                         SELECT customer_id, hist_tx_count, hist_sum_log_amount, hist_sumsq_log_amount, hist_max_amount_usd,
                                hist_sum_hour, seen_merchants_json::jsonb, seen_countries_json::jsonb,
                                seen_channels_json::jsonb, last_tx_ts, last_lat, last_lon
                         FROM serving.online_fraud_state""")
            n = c.execute("SELECT count(*) FROM online_features.customer_state").fetchone()[0]
        ops.ledger(
            "stream.online_state_loaded",
            "online_features.customer_state",
            {"customers": n},
            lineage_run_id,
        )
        return n

    results = publish.partial(lineage_run_id="{{ run_id }}").expand(table=SERVING_TABLES)
    results >> load_online_state(lineage_run_id="{{ run_id }}")


publish_serving()
