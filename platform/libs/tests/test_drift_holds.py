"""Held partitions open one compliance review each, once (needs the local pg-core container; skips otherwise)."""

from __future__ import annotations

import json

import duckdb
import pytest

from latam_platform import drift_holds


@pytest.fixture
def lake():
    c = duckdb.connect()
    c.sql("CREATE SCHEMA audit")
    c.sql("""CREATE TABLE audit.dq_partition_holds AS SELECT * FROM (VALUES
        ('bronze', 'transactions', DATE '2025-03-13', 1, ['format:amount'], now()),
        ('bronze', 'digital_events', DATE '2025-06-01', 1, ['absent:browser'], now()))
        t(zone, table_name, partition_date, severe_checks, reasons, held_at)""")
    c.sql("""CREATE TABLE audit.dq_schema_drift AS SELECT * FROM (VALUES
        ('bronze', 'transactions', DATE '2025-03-13', 'amount', 'format', 'A', 1.0, 0.001, '5016 value(s) do not cast', now()),
        ('bronze', 'transactions', DATE '2025-03-13', 'note', 'empty_share', 'B', 0.4, 0.3, 'empty share moved', now()),
        ('bronze', 'digital_events', DATE '2025-06-01', 'browser', 'absent', 'A', 9397, 0, 'column missing', now()))
        t(zone, table_name, partition_date, column_name, check_name, severity, observed, threshold, detail, checked_at)""")
    yield c
    c.close()


def test_each_held_partition_opens_one_review(lake, writer_conn):
    trigger = drift_holds.load_trigger()
    assert trigger["action"] == "data_steward_review_hitl"
    first = drift_holds.raise_reviews(lake, writer_conn, trigger)
    assert first["held_partitions"] == 2 and first["new_reviews"] == 2
    rows = writer_conn.execute(
        "SELECT subject_ref, evidence, action, status, deadline_at - fired_at FROM compliance.trigger_event"
        " WHERE trigger_id = %s ORDER BY subject_ref",
        (drift_holds.TRIGGER_ID,),
    ).fetchall()
    assert [r[0] for r in rows] == ["digital_events|2025-06-01", "transactions|2025-03-13"]
    evidence = rows[1][1] if isinstance(rows[1][1], dict) else json.loads(rows[1][1])
    assert evidence["reasons"] == ["format:amount"]
    assert [c["check_name"] for c in evidence["checks"]] == ["format"], (
        "only the severe checks are evidence"
    )
    assert all(r[3] == "open" for r in rows)
    assert rows[0][4].total_seconds() == trigger["deadline_hours"] * 3600

    again = drift_holds.raise_reviews(lake, writer_conn, trigger)
    assert again["new_reviews"] == 0, "a partition already under review is not raised twice"
