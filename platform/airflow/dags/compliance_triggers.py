"""Regulatory triggers (platform/policies/regulatory_triggers.yaml) evaluated against the lakehouse.

Each trigger with a batch source produces one append-only `compliance.trigger_event` per subject with its
evidence and deadline. Stream triggers (fraud decisions) are written by the scorer; KB expiry by kb_sync;
residency and PII-zone triggers by the dbt/governance gates. This DAG covers the data-driven ones.
"""

from __future__ import annotations

from datetime import UTC

import pendulum
from airflow.sdk import dag, task

from latam_dags.common import AUDIT_CALLBACKS, DEFAULT_ARGS, DUCKDB_POOL, LAKEHOUSE, PLATFORM_PY

CHECKS = {
    # trigger_id: (SQL returning subject_ref, evidence json, deadline hours from policy)
    "consent_revoked": """
        select send_id as subject_ref,
               json_object('campaign_id', campaign_id, 'customer_id', customer_id, 'send_ts', send_ts_utc) as evidence
        from gold.mart_campaign_compliance_uplift
        where sent_without_current_consent and send_ts_utc >= timestamp '{as_of}' - interval 7 day""",
    "complaint_sla_at_risk": """
        select complaint_id, json_object('priority', priority, 'hours_open', hours_open_or_to_resolution,
                                         'via_regulator', came_via_regulator)
        from gold.mart_transaction_disputes
        where not is_closed and hours_open_or_to_resolution >= 0.8 * case priority when 'Critical' then 48
              when 'High' then 120 when 'Medium' then 240 else 360 end""",
    "aml_typology_hit": """
        select customer_id || '|' || cast(month_start as varchar),
               json_object('typologies', typology_hits, 'inflow_usd', inflow_usd, 'peer_z', inflow_robust_z_vs_peers)
        from gold.mart_aml_customer_month
        where len(typology_hits) > 0 and month_start >= date_trunc('month', date '{as_of}') - interval 1 month""",
}


@dag(
    dag_id="compliance_triggers",
    schedule=[LAKEHOUSE],
    start_date=pendulum.datetime(2026, 9, 1, tz="UTC"),
    catchup=False,
    max_active_runs=1,
    default_args={**DEFAULT_ARGS, "owner": "compliance"},
    tags=["compliance", "regulatory", "audit"],
    doc_md=__doc__,
    **AUDIT_CALLBACKS,
)
def compliance_triggers():
    @task.external_python(python=PLATFORM_PY, expect_airflow=False, pool=DUCKDB_POOL)
    def evaluate(checks: dict, lineage_run_id: str, as_of: str = "2026-05-17") -> dict:
        import json
        from datetime import datetime, timedelta

        import yaml

        from latam_platform import config, ops

        policy = {
            t["id"]: t
            for t in yaml.safe_load(
                (config.REPO_ROOT / "platform/policies/regulatory_triggers.yaml").read_text()
            )["triggers"]
        }
        con = ops.lakehouse(read_only=True)
        now = datetime.now(UTC)
        counts = {}
        with ops.audit() as a:
            seen = {
                r[0]
                for r in a.execute(
                    "SELECT trigger_id || '|' || subject_ref FROM compliance.trigger_event"
                ).fetchall()
            }
            for trig, sql in checks.items():
                rows = con.sql(sql.format(as_of=as_of)).fetchall()
                new = [
                    (s, e) for s, e in rows if f"{trig}|{s}" not in seen
                ]  # idempotent: one event per subject
                deadline = now + timedelta(hours=policy[trig]["deadline_hours"])
                with a.cursor() as cur:
                    cur.executemany(
                        "INSERT INTO compliance.trigger_event (trigger_id, fired_at, deadline_at, subject_ref, evidence, action, status)"
                        " VALUES (%s, %s, %s, %s, %s, %s, 'open')",
                        [
                            (
                                trig,
                                now,
                                deadline,
                                s,
                                e if isinstance(e, str) else json.dumps(e),
                                policy[trig]["action"],
                            )
                            for s, e in new[:5000]
                        ],
                    )  # cap per run; the rest fire next run
                counts[trig] = {"matching": len(rows), "new_events": min(len(new), 5000)}
        ops.ledger(
            "compliance.triggers_evaluated", "regulatory_triggers.yaml", counts, lineage_run_id
        )
        return counts

    evaluate(checks=CHECKS, lineage_run_id="{{ run_id }}")


compliance_triggers()
