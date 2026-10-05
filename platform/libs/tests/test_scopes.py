"""The country cut (ADR-016) on a tiny lake: rules per table, shared links, holdout and idempotence."""

from __future__ import annotations

from pathlib import Path

import duckdb
import pytest

from latam_platform import scopes


def _write(con: duckdb.DuckDBPyConnection, path: Path, sql: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    con.sql(f"COPY ({sql}) TO '{path}' (FORMAT parquet)")


@pytest.fixture()
def lake(tmp_path: Path) -> Path:
    root = tmp_path / "lake"
    con = duckdb.connect()
    b = root / "bronze_raw"
    _write(
        con,
        b / "customers/p=1/part-0.parquet",
        "SELECT * FROM (VALUES ('c1', 'México', '2026-06-17'), ('c2', 'Colombia', '2026-06-17'))"
        " t(customer_id, country, _partition_date)",
    )
    _write(
        con,
        b / "transactions/p=1/part-0.parquet",
        "SELECT * FROM (VALUES ('t1', 'c1', '2025-01-01'), ('t2', 'c2', '2025-01-01'), ('t3', 'c1', '2025-01-02'))"
        " t(transaction_id, customer_id, _partition_date)",
    )
    _write(
        con,
        b / "digital_events/p=1/part-0.parquet",
        "SELECT * FROM (VALUES ('e1', 'c1', 'México', '2025-01-01'), ('e2', NULL, 'Mexico', '2025-01-01'),"
        " ('e3', NULL, 'Colombia', '2025-01-01'), ('e4', 'c2', 'Colombia', '2025-01-01'))"
        " t(event_id, customer_id, ip_country, _partition_date)",
    )
    _write(
        con,
        b / "branches/p=1/part-0.parquet",
        "SELECT * FROM (VALUES ('b1', '2026-06-17')) t(branch_id, _partition_date)",
    )
    _write(
        con,
        root / "holdout_raw/transactions/p=1/part-0.parquet",
        "SELECT * FROM (VALUES ('t9', 'c1', '2026-05-20'), ('t8', 'c2', '2026-05-20'))"
        " t(transaction_id, customer_id, _partition_date)",
    )
    (root / "corrections").mkdir()
    con.close()
    return root


def _kept(rows: list[dict], zone: str, table: str) -> int:
    return next(r["rows_kept"] for r in rows if r["zone"] == zone and r["table"] == table)


def test_cut_applies_the_rules(lake: Path, tmp_path: Path) -> None:
    out = tmp_path / "mx"
    rows = scopes.cut("MX", lake=lake, out=out)
    assert _kept(rows, "bronze_raw", "customers") == 1
    assert _kept(rows, "bronze_raw", "transactions") == 2
    # e1 (a Mexican customer) and e2 (anonymous, IP spelled without the accent); not e3 or e4
    assert _kept(rows, "bronze_raw", "digital_events") == 2
    assert _kept(rows, "holdout_raw", "transactions") == 1
    assert (out / "bronze_raw" / "branches").is_symlink()
    assert (out / "corrections").is_symlink()
    con = duckdb.connect()
    ids = con.sql(
        f"SELECT list(transaction_id ORDER BY transaction_id) FROM read_parquet('{out}/bronze_raw/transactions/*/*.parquet')"
    ).fetchone()[0]
    assert ids == ["t1", "t3"]


def test_scopes_partition_customer_rows(lake: Path, tmp_path: Path) -> None:
    mx = scopes.cut("MX", lake=lake, out=tmp_path / "mx")
    co = scopes.cut("CO", lake=lake, out=tmp_path / "co")
    total = next(
        r["rows_total"] for r in mx if r["table"] == "transactions" and r["zone"] == "bronze_raw"
    )
    assert (
        _kept(mx, "bronze_raw", "transactions") + _kept(co, "bronze_raw", "transactions") == total
    )


def test_cut_is_idempotent_and_writes_a_manifest(lake: Path, tmp_path: Path) -> None:
    out = tmp_path / "co"
    first = scopes.cut("CO", lake=lake, out=out)
    assert (out / scopes.MANIFEST).exists()
    assert scopes.cut("CO", lake=lake, out=out) == first


def test_all_is_not_cut() -> None:
    with pytest.raises(ValueError):
        scopes.cut("ALL")
    assert scopes.lake_dir("ALL") == scopes.config.LAKE
