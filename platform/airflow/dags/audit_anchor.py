"""Audit anchoring: verify every hash chain in pg-audit and anchor the chain heads to WORM storage.

Hourly. Recomputes each chain from scratch (ledger.verify_chain), writes heads + Merkle root to the
object-locked `audit-anchors` bucket (COMPLIANCE retention: not even root can delete it) and records the
anchor in ledger.anchor. Any broken chain fails the run and raises an integrity incident: an edit made by a
privileged user who bypassed the triggers is detected here, and the WORM anchors prove the earlier state.
"""

from __future__ import annotations

import pendulum
from airflow.sdk import dag, task

from latam_dags.common import AUDIT_CALLBACKS, DEFAULT_ARGS, PLATFORM_PY


@dag(
    dag_id="audit_anchor",
    schedule="@hourly",
    start_date=pendulum.datetime(2026, 9, 1, tz="UTC"),
    catchup=False,
    max_active_runs=1,
    default_args={**DEFAULT_ARGS, "owner": "security-and-audit"},
    tags=["audit", "integrity", "worm"],
    doc_md=__doc__,
    **AUDIT_CALLBACKS,
)
def audit_anchor():
    @task.external_python(python=PLATFORM_PY, expect_airflow=False)
    def verify_and_anchor() -> dict:
        from latam_platform import audit_ledger, ops

        with ops.audit() as c:
            doc = audit_ledger.anchor(c, ops.s3(), bucket="audit-anchors")
        if not doc["verified_ok"]:
            raise RuntimeError(f"AUDIT CHAIN BROKEN: {doc['problems']}")
        return {"merkle_root": doc["merkle_root"], "chains": len(doc["heads"])}

    verify_and_anchor()


audit_anchor()
