"""Model and data monitoring: feature drift (PSI) between the training window and the latest window, and
fairness of the transparent eligibility policy across protected groups (measured, never used as input).

Results go to the monitoring database (Grafana) and, when a threshold from regulatory_triggers.yaml is
breached, to a `model_drift_or_fairness_breach` trigger event that requires a model-risk review.
"""

from __future__ import annotations

from datetime import UTC

import pendulum
from airflow.sdk import dag, task

from latam_dags.common import AUDIT_CALLBACKS, DEFAULT_ARGS, DUCKDB_POOL, LAKEHOUSE, PLATFORM_PY

FEATURES = [
    "log_amount",
    "tx_count_24h",
    "amount_usd_24h",
    "hours_since_prev_tx",
    "amount_zscore_vs_history",
    "local_hour",
    "minutes_since_last_login",
]


@dag(
    dag_id="monitoring_drift",
    schedule=[LAKEHOUSE],
    start_date=pendulum.datetime(2026, 9, 1, tz="UTC"),
    catchup=False,
    max_active_runs=1,
    default_args={**DEFAULT_ARGS, "owner": "model-risk"},
    tags=["monitoring", "drift", "fairness", "model-risk"],
    doc_md=__doc__,
    **AUDIT_CALLBACKS,
)
def monitoring_drift():
    @task.external_python(python=PLATFORM_PY, expect_airflow=False, pool=DUCKDB_POOL)
    def drift_and_fairness(features: list, lineage_run_id: str) -> dict:
        import json
        from datetime import datetime

        import numpy as np

        from latam_platform import ops

        def psi(a, b, bins=10):
            a, b = a[~np.isnan(a)], b[~np.isnan(b)]
            edges = np.unique(np.quantile(a, np.linspace(0, 1, bins + 1)))
            pa = np.histogram(a, edges)[0] / max(len(a), 1) + 1e-6
            pb = np.histogram(b, edges)[0] / max(len(b), 1) + 1e-6
            return float(np.sum((pa - pb) * np.log(pa / pb)))

        con = ops.lakehouse(read_only=True)
        cols = ", ".join(f"cast({f} as double) as {f}" for f in features)
        ref = con.sql(f"select {cols} from features.ml_fraud_train using sample 200000").df()
        cur = con.sql(f"select {cols} from features.ml_fraud_test").df()
        drift = {f: round(psi(ref[f].to_numpy(), cur[f].to_numpy()), 4) for f in features}
        fair = con.sql("""select f.gender, avg(e.eligible_credit_card::int) as approval_rate, count(*) as n
                          from gold.mart_credit_eligibility e
                          join silver.int_customer_fairness_attributes f using (customer_id)
                          group by 1 order by 1""").df()
        rates = fair.set_index("gender")["approval_rate"]
        ratio = float(rates.min() / rates.max()) if rates.max() > 0 else 1.0
        breach = max(drift.values()) > 0.25 or ratio < 0.8
        report = {
            "psi": drift,
            "approval_rate_by_gender": rates.round(5).to_dict(),
            "disparate_impact_ratio": round(ratio, 4),
            "breach": breach,
            "computed_at": datetime.now(UTC).isoformat(),
        }
        with ops.pg("monitoring", role="monitoring") as m:
            m.execute(
                "CREATE TABLE IF NOT EXISTS drift_report (run_id text, computed_at timestamptz, report jsonb)"
            )
            m.execute(
                "INSERT INTO drift_report VALUES (%s, now(), %s)",
                (lineage_run_id, json.dumps(report)),
            )
        if breach:
            with ops.audit() as a:
                a.execute(
                    "INSERT INTO compliance.trigger_event (trigger_id, fired_at, subject_ref, evidence, action, status)"
                    " VALUES ('model_drift_or_fairness_breach', now(), 'fraud_features+eligibility', %s,"
                    " 'model_risk_review_hitl', 'open')",
                    (json.dumps(report),),
                )
        ops.ledger("monitoring.drift_evaluated", "features+eligibility", report, lineage_run_id)
        return report

    drift_and_fairness(features=FEATURES, lineage_run_id="{{ run_id }}")


monitoring_drift()
