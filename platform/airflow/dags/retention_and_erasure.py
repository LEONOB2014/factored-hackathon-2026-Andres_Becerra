"""Data-subject erasure (ARCO cancellation / LGPD art. 18 / Ley 1581 / Ley 25.326) and retention.

For each open erasure request in audit.dsar.request without a legal hold:
  1. crypto-shred the subject key (immutable logs become unreadable for that person, chains stay valid);
  2. purge the subject from derived operational stores (Postgres serving tables, online features, Neo4j);
  3. record a ledger event and a `data_subject_erasure` trigger event as actioned.
Lakehouse/bronze rows are handled by the next rebuild with the subject on the suppression list (production:
Iceberg row-level deletes on silver+). Legal holds (AML, transaction ledgers) block erasure and are logged.
"""

from __future__ import annotations

from datetime import UTC

import pendulum
from airflow.sdk import dag, task

from latam_dags.common import AUDIT_CALLBACKS, DEFAULT_ARGS, PLATFORM_PY

SERVING_TABLES = [
    "customer_360",
    "account_inquiry",
    "card_support",
    "dispute_case",
    "credit_eligibility",
]


@dag(
    dag_id="retention_and_erasure",
    schedule="@daily",
    start_date=pendulum.datetime(2026, 9, 1, tz="UTC"),
    catchup=False,
    max_active_runs=1,
    default_args={**DEFAULT_ARGS, "owner": "data-protection-office"},
    tags=["privacy", "erasure", "retention", "compliance"],
    doc_md=__doc__,
    **AUDIT_CALLBACKS,
)
def retention_and_erasure():
    @task.external_python(python=PLATFORM_PY, expect_airflow=False)
    def process_erasure_requests(tables: list, lineage_run_id: str) -> dict:
        import json
        from datetime import datetime

        from latam_platform import audit_ledger, ops

        done, held = [], []
        with ops.audit() as a:
            reqs = a.execute("""SELECT r.dsar_id, r.subject_token, r.legal_hold FROM dsar.request r
                                WHERE r.right_invoked = 'cancellation/erasure' AND r.status = 'approved'
                                  AND NOT EXISTS (SELECT 1 FROM compliance.trigger_event t
                                                  WHERE t.trigger_id = 'data_subject_erasure'
                                                    AND t.subject_ref = r.dsar_id::text)""").fetchall()
            for dsar_id, token, hold in reqs:
                if hold:
                    held.append(str(dsar_id))
                    audit_ledger.append_event(
                        a,
                        "svc-dpo",
                        "privacy.erasure_blocked_legal_hold",
                        token,
                        {"dsar_id": str(dsar_id)},
                        lineage_run_id,
                    )
                    continue
                audit_ledger.shred_subject(a, token, actor="svc-dpo", dsar_id=str(dsar_id))
                purged = {}
                with ops.pg("bank_serving") as pg:
                    ids = [
                        r[0]
                        for r in pg.execute(
                            "SELECT customer_id FROM serving.customer_360 WHERE document_token = %s",
                            (token,),
                        ).fetchall()
                    ]
                    for t in tables:
                        purged[t] = pg.execute(
                            f"DELETE FROM serving.{t} WHERE customer_id = ANY(%s)", (ids,)
                        ).rowcount
                    purged["online_state"] = pg.execute(
                        "DELETE FROM online_features.customer_state WHERE customer_id = ANY(%s)",
                        (ids,),
                    ).rowcount
                neo = ops.neo4j_driver()
                recs, _, _ = neo.execute_query(
                    "MATCH (c:Customer) WHERE c.id IN $ids DETACH DELETE c RETURN count(*) AS n",
                    ids=ids,
                )
                neo.close()
                purged["neo4j_customers"] = recs[0]["n"]
                a.execute(
                    "INSERT INTO compliance.trigger_event (trigger_id, fired_at, subject_ref, evidence, action, status)"
                    " VALUES ('data_subject_erasure', %s, %s, %s, 'crypto_shred_and_propagate', 'actioned')",
                    (datetime.now(UTC), str(dsar_id), json.dumps(purged)),
                )
                done.append({"dsar_id": str(dsar_id), "purged": purged})
        return {"erased": done, "legal_hold": held}

    process_erasure_requests(tables=SERVING_TABLES, lineage_run_id="{{ run_id }}")


retention_and_erasure()
