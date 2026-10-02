"""Against the real dataset: schemas, the committed findings, and full script runs.

Every test here is marked `data` and skipped when the dataset is absent (CI).
Point LATAM_EDA_DATA at a copy, or place it under eda/data/.
"""

import json
import re

import duckdb
import pandas as pd
import pytest

import build_backup_parquet
import compare_backup
import eda_overview
import export_dashboard_data
import generate_erd
from conftest import EDA, TABLES
from latam_eda import anomaly, data

pytestmark = pytest.mark.data

ABSENT_FROM_BACKUP = {"call_transcripts", "satisfaction_surveys"}
PARTITION_COLS = {"year", "month", "day"}


@pytest.fixture(scope="module")
def con():
    return data.connect()


@pytest.fixture(scope="module")
def dictionary():
    tables, _ = generate_erd.parse_dictionary()
    return {name: [c[0] for c in t["cols"]] for name, t in tables.items()}


def columns(con, view):
    return [r[0] for r in con.sql(f"describe {view}").fetchall()]


def test_main_has_every_table_and_backup_misses_two(con):
    tables = set(data.FACTS) | set(data.DIMS)
    assert {p.stem for p in data.MAIN.glob("*.parquet")} == tables
    assert {p.stem for p in data.BACKUP.glob("*.parquet")} == tables - ABSENT_FROM_BACKUP


def test_main_schema_matches_the_dictionary(con, dictionary):
    for table, cols in dictionary.items():
        assert columns(con, f"m_{table}") == cols, table


def test_backup_schema_matches_except_partition_columns(con, dictionary):
    for table, cols in dictionary.items():
        if table in ABSENT_FROM_BACKUP:
            continue
        backup = columns(con, f"b_{table}")
        assert [c for c in backup if c not in PARTITION_COLS] == cols, table
        assert set(backup) - set(cols) <= PARTITION_COLS


def test_primary_keys_are_unique_and_never_null(con):
    for table, pk in data.PK.items():
        n, distinct, nulls = con.sql(
            f"select count(*), count(distinct {pk}), count(*) - count({pk}) from m_{table}"
        ).fetchone()
        assert n == distinct and nulls == 0, table


def test_set_difference_table_reproduces(con):
    """reports/tables/set_difference_summary.csv (notebook 02) recomputed from the data."""
    summary = pd.read_csv(TABLES / "set_difference_summary.csv").set_index("table")
    for table, row in summary.iterrows():
        pk = data.PK[table]
        main_keys = con.sql(f"select count(distinct {pk}) from m_{table}").fetchone()[0]
        assert main_keys == row.main_keys, table
        if table in ABSENT_FROM_BACKUP:
            assert row.backup_keys == 0
            continue
        backup_keys, shared = con.sql(
            f"select (select count(distinct {pk}) from b_{table}), "
            f"(select count(*) from (select {pk} from m_{table} intersect select {pk} from b_{table}))"
        ).fetchone()
        assert (backup_keys, shared) == (row.backup_keys, row.shared), table


def test_overview_row_counts_reproduce(con):
    md = (EDA / "reports" / "eda_overview.md").read_text()
    for table in [*data.FACTS, *data.DIMS]:
        documented = int(re.search(rf"\| {table}\s+\|\s+(\d+) \|", md).group(1))
        assert con.sql(f"select count(*) from m_{table}").fetchone()[0] == documented, table


def test_backup_transactions_are_truncated(con):
    lo, hi = con.sql("select min(process_date), max(process_date) from b_transactions").fetchone()
    assert (str(lo), str(hi)) == ("2023-07-01", "2024-09-25")


def test_complaints_differ_only_in_their_foreign_keys():
    (r,) = compare_backup.compare(data.MAIN, data.BACKUP, {"complaints": "complaint_id"})
    assert r["joined"] == r["counts"]["rows_main"]
    assert set(r["column_diffs"]) == {"customer_id", "affected_product_id", "assigned_agent_id"}


def test_reference_tables_are_identical_in_both_folders(con):
    for table in ("branches", "marketing_campaigns", "daily_exchange_rates"):
        diff = con.sql(
            f"select count(*) from ((select * from m_{table} except select * from b_{table}) "
            f"union all (select * from b_{table} except select * from m_{table}))"
        ).fetchone()[0]
        assert diff == 0, table


def test_features_on_real_transactions(con):
    df = anomaly.build_tx_features(con, "m", n=2_000, seed=0)
    assert len(df) == 2_000
    assert df[anomaly.FEATURES].notna().all().all()
    assert df.country_mismatch.isin([0, 1]).all()
    assert df.hour.between(0, 23).all()


@pytest.mark.slow
def test_full_backup_comparison_runs():
    results = compare_backup.compare(data.MAIN, data.BACKUP)
    assert [r["table"] for r in results] == list(compare_backup.PK)
    customers = next(r for r in results if r["table"] == "customers")
    assert customers["joined"] == 4_025  # shared customer IDs (notebook 02)


@pytest.mark.slow
def test_overview_report_regenerates_identically(tmp_path, monkeypatch):
    monkeypatch.setattr(eda_overview, "REPORTS", tmp_path)
    monkeypatch.setattr(eda_overview, "FIGS", tmp_path / "figures")
    monkeypatch.setattr(eda_overview, "PQ", data.MAIN)
    monkeypatch.setattr("sys.argv", ["eda_overview.py"])
    eda_overview.main()
    committed = (EDA / "reports" / "eda_overview.md").read_text()
    assert (tmp_path / "eda_overview.md").read_text() == committed
    figures = {p.name: p.read_bytes() for p in (tmp_path / "figures").glob("*.png")}
    assert set(figures) == {
        "monthly_volumes.png",
        "amount_usd_hist.png",
        "credit_score_by_segment.png",
    }
    for name, png in figures.items():  # seeded sample, so the bytes are stable on one platform
        assert png == (EDA / "reports" / "figures" / name).read_bytes(), name


@pytest.mark.slow
def test_backup_conversion_of_real_csvs(tmp_path):
    """Convert one real day of two backup tables and check the result matches the full Parquet."""
    raw_backup = build_backup_parquet.RAW
    if not raw_backup.exists():
        pytest.skip("raw CSVs not downloaded")
    raw = tmp_path / "raw"
    for table in ("complaints", "branches.csv"):
        src = raw_backup / table
        if src.is_dir():
            day = sorted(src.glob("*/*/*"))[0]
            (raw / table / day.relative_to(src)).mkdir(parents=True)
            for f in day.glob("*.csv"):
                (raw / table / day.relative_to(src) / f.name).symlink_to(f)
        else:
            raw.mkdir(exist_ok=True)
            (raw / table).symlink_to(src)
    out = tmp_path / "out"
    assert build_backup_parquet.convert(raw, out) == ["branches", "complaints"]
    con = duckdb.connect()
    for table in ("branches", "complaints"):
        got = columns(con, f"'{out}/{table}.parquet'")
        expected = columns(con, f"'{data.BACKUP}/{table}.parquet'")
        assert got == expected, table
    full = con.sql(f"select count(*) from '{data.BACKUP}/branches.parquet'").fetchone()[0]
    assert con.sql(f"select count(*) from '{out}/branches.parquet'").fetchone()[0] == full


@pytest.mark.slow
def test_dashboard_export(tmp_path):
    if not (data.DERIVED / "bench_scores_main.parquet").exists():
        pytest.skip("derived tables from notebooks 02–10 not present")
    export_dashboard_data.main(tmp_path)
    for name in ("overlap", "timeshift", "anomalies"):
        payload = json.loads((tmp_path / f"{name}.json").read_text())
        js = (tmp_path / f"{name}.js").read_text()
        assert js.startswith(f"window.DATA_{name} = ")
        assert payload
    overlap = json.loads((tmp_path / "overlap.json").read_text())
    assert overlap["tables"] == data.FACTS
    assert len(overlap["months"]) == 37
    anomalies = json.loads((tmp_path / "anomalies.json").read_text())
    assert anomalies["types"] == anomaly.INJECTED
    assert anomalies["n_total"] == 100_000
