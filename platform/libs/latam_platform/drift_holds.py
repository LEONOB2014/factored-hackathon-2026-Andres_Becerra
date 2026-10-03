"""Schema-drift holds -> compliance reviews.

The dbt circuit breaker (models/silver/quality) holds a bronze partition whose schema changed: its rows stay in
lossless bronze and the typed models but are kept out of staging and everything built on it. This module opens one
`compliance.trigger_event` (trigger `schema_drift_partition_held`, platform/policies/regulatory_triggers.yaml) per
newly held partition, with the failed checks as evidence, so a data steward reviews it within the deadline.
Idempotent: a partition already under review is not raised again.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import yaml

from latam_platform import config

TRIGGER_ID = "schema_drift_partition_held"
HOLDS_SQL = """
    select h.zone, h.table_name, cast(h.partition_date as varchar), h.reasons,
           list(struct_pack(check_name := d.check_name, column_name := d.column_name,
                            observed := d.observed, threshold := d.threshold, detail := d.detail)
                order by d.check_name, d.column_name)
    from audit.dq_partition_holds h
    join audit.dq_schema_drift d using (table_name, partition_date)
    where d.severity = 'A'
    group by all
    order by 2, 3
"""


def load_trigger(trigger_id: str = TRIGGER_ID) -> dict:
    policy = config.REPO_ROOT / "platform" / "policies" / "regulatory_triggers.yaml"
    return next(t for t in yaml.safe_load(policy.read_text())["triggers"] if t["id"] == trigger_id)


def raise_reviews(lake, audit_conn, trigger: dict, now: datetime | None = None) -> dict:
    """Insert an open trigger event for every held partition not yet under review."""
    now = now or datetime.now(UTC)
    holds = lake.sql(HOLDS_SQL).fetchall()
    seen = {
        r[0]
        for r in audit_conn.execute(
            "SELECT subject_ref FROM compliance.trigger_event WHERE trigger_id = %s",
            (trigger["id"],),
        ).fetchall()
    }
    new = [h for h in holds if f"{h[1]}|{h[2]}" not in seen]
    with audit_conn.cursor() as cur:
        cur.executemany(
            "INSERT INTO compliance.trigger_event"
            " (trigger_id, fired_at, deadline_at, subject_ref, evidence, action, status)"
            " VALUES (%s, %s, %s, %s, %s, %s, 'open')",
            [
                (
                    trigger["id"],
                    now,
                    now + timedelta(hours=trigger["deadline_hours"]),
                    f"{table}|{day}",
                    json.dumps({"zone": zone, "reasons": reasons, "checks": checks}, default=str),
                    trigger["action"],
                )
                for zone, table, day, reasons, checks in new
            ],
        )
    return {
        "held_partitions": len(holds),
        "new_reviews": len(new),
        "new": [f"{h[1]}|{h[2]}" for h in new][:50],
    }
