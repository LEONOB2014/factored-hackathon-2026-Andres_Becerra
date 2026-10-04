"""Four-eyes corrections: validation, staging, write-once application, reverts and releases (no dataset needed).

A temporary lake holds a few lossless-bronze records of `transactions`, typed against the real source contract.
"""

from __future__ import annotations

import json
import stat

import duckdb
import pytest

from latam_platform import config
from latam_platform import dq_corrections as dq

FILE = "data/transactions/year=2025/month=01/day=01/transactions_20250101.csv"


def _record(no: int, country: str, **over) -> dict:
    row = {
        "transaction_id": f"TRX-{no:020d}",
        "transaction_date": "2025-01-01 10:00:00",
        "process_date": "2025-01-01",
        "product_id": "PRD-000000000001",
        "customer_id": "CLI-000000000001",
        "transaction_type": "Purchase",
        "transaction_category": "Food",
        "amount": "10.5",
        "currency": "USD",
        "amount_usd": "10.5",
        "channel": "POS",
        "branch_id": "",
        "merchant_name": "Super Ahorro",
        "merchant_category": "Food",
        "transaction_country": country,
        "transaction_city": "Monterrey",
        "transaction_status": "Approved",
        "response_code": "00",
        "is_fraud": "False",
        "fraud_score": "",
        "latitude": "",
        "longitude": "",
    }
    return {**row, **over, "_record_no": no}


@pytest.fixture
def lake(tmp_path, monkeypatch):
    data = tmp_path / "data"
    monkeypatch.setattr(config, "DATA", data)
    monkeypatch.setattr(config, "LAKE", data / "lake")
    monkeypatch.setattr(config, "BRONZE_RAW", data / "lake" / "bronze_raw")
    monkeypatch.setattr(config, "HOLDOUT_RAW", data / "lake" / "holdout_raw")
    part = config.BRONZE_RAW / "transactions" / "_partition_date=2025-01-01"
    part.mkdir(parents=True)
    rows = [
        _record(1, "Mexico"),
        _record(2, "México"),
        _record(3, "Mexico"),
        _record(4, "Colombia"),
    ]
    con = duckdb.connect()
    cols = [c for c in rows[0] if c != "_record_no"]
    con.execute(f"CREATE TABLE t ({', '.join(f'{c} VARCHAR' for c in cols)}, _record_no BIGINT, "
                "_source_file VARCHAR, _partition_date VARCHAR, _parse_status VARCHAR)")  # fmt: skip
    for r in rows:
        con.execute(f"INSERT INTO t VALUES ({', '.join('?' * (len(cols) + 4))})",
                    [*(r[c] for c in cols), r["_record_no"], FILE, "2025-01-01", "ok"])  # fmt: skip
    con.execute(f"COPY t TO '{part}/part-0.parquet' (FORMAT parquet)")
    dq.ensure_log()
    yield data
    for p in (data / "lake" / "corrections" / "applied").glob(
        "*.parquet"
    ):  # read-only files: let tmp clean up
        p.chmod(0o644)


def _propose(pid: str, kind: str, **body) -> str:
    path = dq.root() / "proposals" / f"{pid}.json"
    path.write_text(json.dumps({"proposal_id": pid, "kind": kind, "reason": "test", **body}))
    return pid


MEXICO = {
    "table": "transactions",
    "column": "transaction_country",
    "from_value": "Mexico",
    "to_value": "México",
}


def _log() -> list[tuple]:
    return (
        duckdb.connect()
        .sql(
            f"SELECT proposal_id, kind, record_no, new_value, reverts_proposal_id, proposed_by, approved_by "
            f"FROM {dq.log_sql()} ORDER BY proposal_id, seq"
        )
        .fetchall()
    )


def test_a_pattern_is_expanded_staged_and_applied_write_once(lake):
    pid = _propose("cp-mexico", "pattern", pattern=MEXICO)
    summary = dq.stage(pid, "steward")
    assert (
        summary["cells"] == 2
        and summary["records"] == 2
        and summary["columns"] == ["transactions.transaction_country"]
    )
    assert summary["examples"] == [{"from": "Mexico", "to": "México", "cells": 2}]
    out = dq.apply(pid, "steward", "approver", "variant spelling, same country")
    assert out["entries"] == 2 and out["read_only"] is True
    target = dq.root() / "applied" / "cp-mexico.parquet"
    assert not target.stat().st_mode & (stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH)
    assert not (dq.root() / "staged" / "cp-mexico.parquet").exists()
    assert [(r[2], r[3], r[5], r[6]) for r in _log()] == [(1, "México", "steward", "approver"),
                                                          (3, "México", "steward", "approver")]  # fmt: skip
    with pytest.raises(dq.CorrectionError, match="already"):
        dq.stage(pid, "steward")


def test_the_proposer_cannot_approve(lake):
    pid = _propose("cp-self", "pattern", pattern=MEXICO)
    dq.stage(pid, "steward")
    with pytest.raises(dq.CorrectionError, match="four-eyes"):
        dq.apply(pid, "steward", "Steward", "looks fine to me")
    assert _log() == []


def test_a_new_value_must_satisfy_the_contract(lake):
    pid = _propose("cp-typo", "pattern", pattern={**MEXICO, "to_value": "Mexiko"})
    with pytest.raises(
        dq.CorrectionError, match="break the transactions.transaction_country contract"
    ):
        dq.stage(pid, "steward")
    pid = _propose(
        "cp-variant", "pattern", pattern={**MEXICO, "from_value": "México", "to_value": "Mexico"}
    )
    with pytest.raises(dq.CorrectionError, match="V2"):
        dq.stage(pid, "steward")


@pytest.mark.parametrize(
    ("body", "error"),
    [
        ({"pattern": {**MEXICO, "column": "nope"}}, "not in the source contract"),
        ({"pattern": {**MEXICO, "table": "nope"}}, "unknown table"),
        ({"pattern": {**MEXICO, "from_value": "Narnia"}}, "matches no cell"),
        ({"pattern": {**MEXICO, "to_value": "Mexico"}}, "equal"),
    ],
)
def test_invalid_patterns_are_refused(lake, body, error):
    pid = _propose("cp-bad", "pattern", **body)
    with pytest.raises(dq.CorrectionError, match=error):
        dq.stage(pid, "steward")


def test_cells_must_match_lossless_bronze(lake):
    cell = {"zone": "bronze", "table": "transactions", "source_file": FILE, "record_no": 4,
            "column": "transaction_city", "old_value": "Monterrey", "new_value": "Bogotá"}  # fmt: skip
    dq.stage(_propose("cp-cell", "cells", cells=[cell]), "steward")
    stale = _propose("cp-stale", "cells", cells=[{**cell, "old_value": "Cali"}])
    with pytest.raises(dq.CorrectionError, match="stale"):
        dq.stage(stale, "steward")
    missing = _propose("cp-missing", "cells", cells=[{**cell, "record_no": 99}])
    with pytest.raises(dq.CorrectionError, match="no bronze record"):
        dq.stage(missing, "steward")


def test_a_revert_undoes_an_applied_correction_once(lake):
    with pytest.raises(dq.CorrectionError, match="not an applied correction"):
        dq.stage(
            _propose("cp-undo-early", "revert", revert={"proposal_ids": ["cp-mexico"]}), "steward"
        )
    dq.stage(_propose("cp-mexico", "pattern", pattern=MEXICO), "steward")
    dq.apply("cp-mexico", "steward", "approver", "ok")
    dq.stage(_propose("cp-undo", "revert", revert={"proposal_ids": ["cp-mexico"]}), "steward")
    dq.apply("cp-undo", "steward", "approver", "wrong scope, restore the source values")
    assert dq.applied_state(duckdb.connect())["cp-mexico"]["reverted"] is True
    with pytest.raises(dq.CorrectionError, match="already reverted"):
        dq.stage(
            _propose("cp-undo-again", "revert", revert={"proposal_ids": ["cp-mexico"]}), "steward"
        )


def test_a_release_needs_a_held_partition(lake):
    lakehouse = duckdb.connect()
    lakehouse.execute(
        "CREATE SCHEMA audit; CREATE TABLE audit.dq_partition_holds (table_name VARCHAR, partition_date DATE)"
    )
    release = {"table": "transactions", "partition_date": "2025-01-01"}
    with pytest.raises(dq.CorrectionError, match="not held"):
        dq.stage(_propose("cp-release", "release", release=release), "steward", lakehouse)
    lakehouse.execute("INSERT INTO audit.dq_partition_holds VALUES ('transactions', '2025-01-01')")
    assert dq.stage("cp-release", "steward", lakehouse)["entries"] == 1


def test_a_proposal_edited_after_validation_is_refused(lake):
    pid = _propose("cp-edit", "pattern", pattern=MEXICO)
    dq.stage(pid, "steward")
    _propose("cp-edit", "pattern", pattern={**MEXICO, "to_value": "Colombia"})
    with pytest.raises(dq.CorrectionError, match="changed after it was validated"):
        dq.apply(pid, "steward", "approver", "ok")


def test_proposal_ids_and_reasons_are_required(lake):
    with pytest.raises(dq.CorrectionError, match="invalid proposal id"):
        dq.load_proposal("../etc/passwd")
    path = dq.root() / "proposals" / "cp-noreason.json"
    path.write_text(json.dumps({"proposal_id": "cp-noreason", "kind": "pattern", "reason": " "}))
    with pytest.raises(dq.CorrectionError, match="reason"):
        dq.load_proposal("cp-noreason")
