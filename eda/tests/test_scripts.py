"""Pipeline scripts on small synthetic inputs: CSV → Parquet, backup comparison, S3 helpers."""

from pathlib import Path

import duckdb
import nbformat
import pandas as pd
import pytest

import build_backup_parquet
import compare_backup
import download_s3
import eda_overview
import explore_s3
import run_nb_timed
from latam_eda.csvio import CsvIntegrityError


def write_partitioned(folder, rows_by_day, header):
    """year=/month=/day=/part.csv layout used by the fact tables in the bucket."""
    for day, rows in rows_by_day.items():
        y, m, d = day.split("-")
        part = folder / y / m / d
        part.mkdir(parents=True)
        (part / "part-0.csv").write_text(header + "\n" + "\n".join(rows) + "\n")


def test_backup_conversion_handles_partitioned_and_flat_tables(tmp_path):
    raw, out = tmp_path / "raw", tmp_path / "out"
    write_partitioned(
        raw / "transactions",
        {"2024-01-01": ["T1,10.5", "T2,3"], "2024-01-02": ["T3,7"]},
        "transaction_id,amount",
    )
    # schema evolution: a later partition gains a column (union_by_name)
    write_partitioned(
        raw / "transactions", {"2024-01-03": ["T4,1,web"]}, "transaction_id,amount,channel"
    )
    raw.joinpath("branches.csv").write_text("branch_id,name\nB1,Centro\nB2,Norte\n")

    assert build_backup_parquet.convert(raw, out) == ["branches", "transactions"]
    con = duckdb.connect()
    tx = con.sql(f"select * from '{out}/transactions.parquet' order by 1").df()
    assert list(tx.transaction_id) == ["T1", "T2", "T3", "T4"]
    assert tx.channel.isna().sum() == 3
    assert con.sql(f"select count(*) from '{out}/branches.parquet'").fetchone()[0] == 2


def test_compare_reports_overlap_and_changed_values(tiny_dataset):
    main, backup = tiny_dataset
    pk = {"customers": "customer_id", "branches": "branch_id", "service_agents": "agent_id"}
    results = {r["table"]: r for r in compare_backup.compare(main, backup, pk)}

    customers = results["customers"]
    assert customers["counts"] == {
        "rows_main": 3,
        "rows_backup": 3,
        "uniq_main": 3,
        "uniq_backup": 3,
        "only_backup": 1,
        "only_main": 1,
    }
    assert customers["joined"] == 2
    assert customers["column_diffs"] == {"credit_score": 1}

    assert results["branches"]["column_diffs"] == {}
    assert results["branches"]["joined"] == 2


def test_compare_handles_a_table_with_only_its_key(tiny_dataset):
    """The original script built `select ,count(*)` here: invalid SQL."""
    main, backup = tiny_dataset
    (r,) = compare_backup.compare(main, backup, {"service_agents": "agent_id"})
    assert r["joined"] == 1
    assert r["column_diffs"] == {}
    assert r["main_only_cols"] == r["backup_only_cols"] == set()


def test_compare_main_prints_a_report(tiny_dataset, monkeypatch, capsys):
    main, backup = tiny_dataset
    monkeypatch.setattr(compare_backup, "MAIN", main)
    monkeypatch.setattr(compare_backup, "BACKUP", backup)
    monkeypatch.setattr(compare_backup, "PK", {"customers": "customer_id"})
    compare_backup.main()
    out = capsys.readouterr().out
    assert "=== customers" in out
    assert "credit_score" in out


def test_overview_converts_every_table_and_skips_cached_ones(tmp_path, monkeypatch):
    raw, pq = tmp_path / "raw", tmp_path / "parquet"
    for table, (pk, _) in eda_overview.FACTS.items():
        write_partitioned(raw / table, {"2024-01-01": [f"{table[:2]}1"]}, pk)
    for table, (pk, _) in eda_overview.DIMS.items():
        raw.mkdir(exist_ok=True)
        (raw / f"{table}.csv").write_text(f"{pk or 'date'}\nX1\nX2\n")
    monkeypatch.setattr(eda_overview, "RAW", raw)
    monkeypatch.setattr(eda_overview, "PQ", pq)

    con = duckdb.connect()
    eda_overview.build_parquet(con, rebuild=False)
    assert {p.stem for p in pq.glob("*.parquet")} == {*eda_overview.FACTS, *eda_overview.DIMS}

    stamp = (pq / "customers.parquet").stat().st_mtime_ns
    eda_overview.build_parquet(con, rebuild=False)
    assert (pq / "customers.parquet").stat().st_mtime_ns == stamp

    eda_overview.view_all(con)
    assert con.sql("select count(*) from transactions").fetchone()[0] == 1
    assert con.sql("select count(*) from customers").fetchone()[0] == 2


def test_parquet_build_fails_loudly_on_a_malformed_row(tmp_path, monkeypatch):
    """A row that does not parse must stop the build, not vanish from the Parquet copy."""
    raw, pq = tmp_path / "raw", tmp_path / "parquet"
    write_partitioned(
        raw / "transactions",
        {"2024-01-01": ["T1,10.5", "T2,3"], "2024-01-02": ['T3,"unterminated']},
        "transaction_id,amount",
    )
    monkeypatch.setattr(eda_overview, "RAW", raw)
    monkeypatch.setattr(eda_overview, "PQ", pq)
    monkeypatch.setattr(eda_overview, "FACTS", {"transactions": ("transaction_id", None)})
    monkeypatch.setattr(eda_overview, "DIMS", {})
    with pytest.raises(CsvIntegrityError):
        eda_overview.build_parquet(duckdb.connect(), rebuild=True)
    assert not (pq / "transactions.parquet").exists()


def test_markdown_table_helper():
    assert eda_overview.md_table(pd.DataFrame()) == "_empty_"
    md = eda_overview.md_table(pd.DataFrame({"table": ["a"], "rows": [1]}))
    assert md.splitlines()[0].startswith("| table")


@pytest.mark.parametrize("module", [download_s3, explore_s3])
def test_human_size(module):
    assert module.human_size(512) == "512.00 B"
    assert module.human_size(1536) == "1.50 KB"
    assert module.human_size(3 * 1024**3) == "3.00 GB"
    assert module.human_size(2 * 1024**5) == "2.00 PB"


class FakePaginator:
    def __init__(self, pages):
        self.pages = pages

    def paginate(self, **kwargs):
        self.kwargs = kwargs
        return self.pages


class FakeS3:
    def __init__(self, pages=(), payload=b""):
        self.paginator = FakePaginator(list(pages))
        self.payload = payload
        self.downloads = []

    def get_paginator(self, name):
        assert name == "list_objects_v2"
        return self.paginator

    def download_file(self, bucket, key, filename, Callback):  # noqa: N803 (boto3's signature)
        self.downloads.append(key)
        Path(filename).write_bytes(self.payload)
        Callback(len(self.payload))


class FakeProgress:
    def __init__(self):
        self.advanced = 0

    def update(self, task, advance):
        self.advanced += advance


def test_list_objects_skips_folder_placeholders():
    s3 = FakeS3(
        pages=[
            {"Contents": [{"Key": "data/", "Size": 0}, {"Key": "data/a.csv", "Size": 5}]},
            {"Contents": [{"Key": "data/b.csv", "Size": 7}]},
            {},  # an empty page has no Contents
        ]
    )
    assert download_s3.list_objects(s3, "data/") == [("data/a.csv", 5), ("data/b.csv", 7)]
    assert s3.paginator.kwargs == {"Bucket": download_s3.BUCKET, "Prefix": "data/"}


def test_download_one_writes_atomically(tmp_path):
    s3, progress = FakeS3(payload=b"hello"), FakeProgress()
    result = download_s3.download_one(s3, "data/x/a.csv", 5, tmp_path, progress, task=0)
    assert result == "downloaded"
    assert (tmp_path / "data/x/a.csv").read_bytes() == b"hello"
    assert not list(tmp_path.rglob("*.part"))
    assert progress.advanced == 5


def test_download_one_skips_files_already_complete(tmp_path):
    target = tmp_path / "a.csv"
    target.write_bytes(b"hello")
    s3, progress = FakeS3(payload=b"other"), FakeProgress()
    assert download_s3.download_one(s3, "a.csv", 5, tmp_path, progress, task=0) == "skipped"
    assert s3.downloads == []
    assert progress.advanced == 5


def test_download_one_replaces_partial_files(tmp_path):
    (tmp_path / "a.csv").write_bytes(b"he")
    s3 = FakeS3(payload=b"hello")
    assert download_s3.download_one(s3, "a.csv", 5, tmp_path, FakeProgress(), 0) == "downloaded"
    assert (tmp_path / "a.csv").read_bytes() == b"hello"


@pytest.mark.slow
def test_timed_runner_stops_at_the_first_failing_cell(tmp_path, capsys):
    nb = nbformat.v4.new_notebook(
        cells=[
            nbformat.v4.new_markdown_cell("# demo"),
            nbformat.v4.new_code_cell("x = 2"),
            nbformat.v4.new_code_cell("raise ValueError('boom')"),
            nbformat.v4.new_code_cell("x = 3"),
        ]
    )
    nb.metadata["kernelspec"] = {
        "name": "python3",
        "display_name": "Python 3",
        "language": "python",
    }
    path = tmp_path / "demo.ipynb"
    nbformat.write(nb, path)

    timings = run_nb_timed.run(path, timeout=120)
    assert [(i, ok) for i, _, ok in timings] == [(1, True), (2, False)]
    assert "FAILED" in capsys.readouterr().out
    saved = nbformat.read(path, as_version=4)
    assert saved.cells[2].outputs[0].ename == "ValueError"
