"""Differentially private statistics release (cross-country / external use only).

Reads the contribution-bounded input built by dbt (privacy.privacy_input_complaints_country_month), adds
OpenDP discrete-Laplace noise over PUBLIC group keys, debits the epsilon from the immutable budget ledger
(refused when exhausted) and writes the release to data/lake/privacy/ for the BigQuery/analytics publish.
"""

from __future__ import annotations

import pendulum
from airflow.sdk import dag, task

from latam_dags.common import AUDIT_CALLBACKS, DEFAULT_ARGS, DUCKDB_POOL, PLATFORM_PY


@dag(
    dag_id="dp_release",
    schedule="@monthly",
    start_date=pendulum.datetime(2026, 9, 1, tz="UTC"),
    catchup=False,
    max_active_runs=1,
    default_args={**DEFAULT_ARGS, "owner": "data-protection-office"},
    tags=["privacy", "differential-privacy", "compliance"],
    doc_md=__doc__,
    **AUDIT_CALLBACKS,
)
def dp_release():
    @task.external_python(python=PLATFORM_PY, expect_airflow=False, pool=DUCKDB_POOL)
    def release_complaints(lineage_run_id: str, epsilon: float = 0.5) -> dict:
        from latam_platform import config, ops, privacy

        con = ops.lakehouse(read_only=True)
        df = con.sql("""select customer_id, country_code, year_month, category, bounded_contribution as contribution
                        from privacy.privacy_input_complaints_country_month""").df()
        months = sorted(df.year_month.unique().tolist())
        domains = {
            "country_code": ["MX", "CO", "AR", "BR"],
            "year_month": months,
            "category": ["Transactions", "Fees", "Technical", "Branch", "Service"],
        }
        with ops.audit() as a:
            privacy.ensure_budget_policy(
                a,
                "complaints_country_month",
                epsilon_total=4.0,
                delta_total=0.0,
                period="calendar_year",
            )
            rel = privacy.dp_count_release(
                df,
                unit="customer_id",
                group_cols=["country_code", "year_month", "category"],
                public_domains=domains,
                epsilon=epsilon,
                max_per_group=3,
                max_groups=12,
                release_name=f"complaints_country_month@{lineage_run_id}",
                dataset="complaints_country_month",
                ledger_conn=a,
                requested_by="dp_release DAG",
            )
        out = config.LAKE / "privacy"
        out.mkdir(parents=True, exist_ok=True)
        path = out / f"dp_complaints_country_month__{lineage_run_id.replace(':', '-')}.parquet"
        rel.table.to_parquet(path, index=False)
        res = {
            "epsilon": rel.epsilon,
            "groups": len(rel.table),
            "suppressed": int(rel.table.suppressed.sum()),
            "path": str(path),
        }
        ops.ledger("privacy.dp_release", "complaints_country_month", res, lineage_run_id)
        return res

    release_complaints(lineage_run_id="{{ run_id }}")


dp_release()
