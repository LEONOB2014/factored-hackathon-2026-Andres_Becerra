"""Four-eyes data correction: proposal -> validation -> human approval -> append-only correction log.

A data steward writes a proposal (usually with the correction workbench, eda/notebooks/model_risk/02) to
data/lake/corrections/proposals/<proposal_id>.json and triggers this DAG with that id. The run:

1. **validate_and_stage**: checks the proposal against the source contracts and lossless bronze (unknown column,
   value that would break its contract, stale old value, revert of something not applied, release of a partition
   that is not held), expands a pattern into its cells, stages them and records `dq.correction_proposed` in the
   audit ledger under the steward's identity, with the impact (cells, records, partitions, findings resolved,
   downstream models);
2. **review**: an approver (CORRECTION_APPROVERS) approves or rejects in Airflow (Required actions), with a comment;
3. **decide_and_apply**: refuses an approval by the proposer (`dq.four_eyes_violation`); on approval appends the
   staged proposal to the correction log as a read-only file (`dq.correction_applied`), which updates the
   CORRECTIONS asset and rebuilds the lakehouse. Bronze is never modified; silver overlays the log.

Kinds: pattern, cells, revert (undo an applied correction), release (lift a schema-drift hold).
See docs/platform/09 §D and the runbook §11.
"""

from __future__ import annotations

import pendulum
from airflow.providers.standard.operators.hitl import HITLOperator
from airflow.sdk import Param, dag, task

from latam_dags.common import (
    AUDIT_CALLBACKS,
    CORRECTION_APPROVERS,
    CORRECTIONS,
    DEFAULT_ARGS,
    DUCKDB_POOL,
    PLATFORM_PY,
)

REJECTED = 99  # exit code of decide_and_apply on a rejection: the task is skipped, so no CORRECTIONS update

REVIEW_BODY = """\
**Proposal `{{ params.proposal_id }}`** by **{{ dag_run.triggering_user_name }}**:
{{ ti.xcom_pull(task_ids='validate_and_stage')['reason'] }}

```json
{{ ti.xcom_pull(task_ids='validate_and_stage') | tojson(indent=1) }}
```

Approving appends these changes to the correction log: silver and everything built on it will show the new values
(lossless bronze keeps the originals, and a revert restores them). The proposer cannot approve their own proposal.
"""


@dag(
    dag_id="dq_correction_review",
    schedule=None,
    start_date=pendulum.datetime(2026, 9, 1, tz="UTC"),
    catchup=False,
    max_active_runs=1,
    default_args={**DEFAULT_ARGS, "owner": "data-governance", "retries": 0},
    params={
        "proposal_id": Param(
            type="string",
            pattern=r"^[a-z0-9][a-z0-9-]{2,79}$",
            description="File name (without .json) in data/lake/corrections/proposals/",
        )
    },
    tags=["data-quality", "governance", "audit", "four-eyes"],
    doc_md=__doc__,
    **AUDIT_CALLBACKS,
)
def dq_correction_review():
    @task.external_python(python=PLATFORM_PY, expect_airflow=False, pool=DUCKDB_POOL)
    def validate_and_stage(proposal_id: str, proposed_by: str, lineage_run_id: str) -> dict:
        from latam_platform import dq_corrections as dq
        from latam_platform import ops

        try:
            lake = ops.lakehouse(read_only=True)
        except (
            Exception
        ):  # no lakehouse yet: validate against bronze only (no holds, no findings count)
            lake = None
        try:
            summary = dq.stage(proposal_id, proposed_by, lake)
        except dq.CorrectionError as exc:
            ops.ledger(
                "dq.correction_refused",
                f"corrections/{proposal_id}",
                {"error": str(exc), "proposed_by": proposed_by},
                lineage_run_id,
                actor=f"user:{proposed_by}",
            )
            raise
        ops.ledger(
            "dq.correction_proposed",
            f"corrections/{proposal_id}",
            summary,
            lineage_run_id,
            actor=f"user:{proposed_by}",
        )
        return summary

    review = HITLOperator(
        task_id="review",
        subject="Data correction {{ params.proposal_id }}: approve?",
        body=REVIEW_BODY,
        options=["Approve", "Reject"],
        params={
            "comment": Param(
                "", type="string", minLength=3, description="Why you approve or reject (recorded)"
            )
        },
        assigned_users=CORRECTION_APPROVERS,
        execution_timeout=pendulum.duration(days=3),
    )

    @task.external_python(
        python=PLATFORM_PY,
        expect_airflow=False,
        pool=DUCKDB_POOL,
        outlets=[CORRECTIONS],
        skip_on_exit_code=REJECTED,
    )
    def decide_and_apply(
        review_result: dict, proposal_id: str, proposed_by: str, lineage_run_id: str
    ) -> dict:
        import sys

        from latam_platform import dq_corrections as dq
        from latam_platform import ops

        user = review_result.get("responded_by_user") or {}
        approved_by = user.get("name") or user.get("id") or ""
        choice = review_result["chosen_options"][0]
        comment = (review_result.get("params_input") or {}).get("comment", "")
        subject = f"corrections/{proposal_id}"
        decision = {"proposed_by": proposed_by, "decided_by": approved_by, "comment": comment}
        if choice != "Approve":
            dq.discard(proposal_id)
            ops.ledger(
                "dq.correction_rejected",
                subject,
                decision,
                lineage_run_id,
                actor=f"user:{approved_by}",
            )
            sys.exit(99)  # REJECTED: skipped, the log and the lakehouse do not change
        try:
            dq.four_eyes(proposed_by, approved_by)
        except dq.CorrectionError:
            dq.discard(proposal_id)
            ops.ledger(
                "dq.four_eyes_violation",
                subject,
                decision,
                lineage_run_id,
                actor=f"user:{approved_by}",
            )
            raise
        applied = dq.apply(proposal_id, proposed_by, approved_by, comment)
        ops.ledger(
            "dq.correction_applied",
            subject,
            {**decision, **applied},
            lineage_run_id,
            actor=f"user:{approved_by}",
        )
        return applied

    staged = validate_and_stage(
        proposal_id="{{ params.proposal_id }}",
        proposed_by="{{ dag_run.triggering_user_name }}",
        lineage_run_id="{{ run_id }}",
    )
    staged >> review
    decide_and_apply(
        review_result=review.output,
        proposal_id="{{ params.proposal_id }}",
        proposed_by="{{ dag_run.triggering_user_name }}",
        lineage_run_id="{{ run_id }}",
    )


dq_correction_review()
