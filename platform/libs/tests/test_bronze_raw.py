"""Lossless bronze: build, proof, independent verification, tamper detection and append-only.

Runs on a tiny Hive layout under tmp_path with the platform config paths redirected; no services.
"""

from __future__ import annotations

import hashlib
import json
from datetime import date
from pathlib import Path

import duckdb
import pytest

from latam_platform import config
from latam_platform.config import Table
from latam_platform.lakehouse import bronze_raw as br
from latam_platform.lakehouse.bronze import BronzeIntegrityError

BOM = b"\xef\xbb\xbf"
FACT = Table("tx", ("id",), "fact", "ts")
DIM = Table("people", ("id",), "dimension")
DAYS = ["2026-05-16", "2026-05-17", "2026-05-18", "2026-05-19"]  # cutoff on 2026-05-18


def write(path: Path, body: bytes) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(body)
    return path


@pytest.fixture
def lake(tmp_path, monkeypatch):
    landing = tmp_path / "raw"
    main = landing / "data"
    for i, day in enumerate(DAYS):
        y, m, d = day.split("-")
        rows = f'T{i}a,{day} 09:00:00,"note with\nnewline",10.5\r\nT{i}b,{day} 10:00:00,,7\r\n'
        write(
            main / "tx" / f"year={y}" / f"month={m}" / f"day={d}" / f"tx_{y}{m}{d}.csv",
            BOM + b"id,ts,note,amount\r\n" + rows.encode(),
        )
    write(main / "people.csv", BOM + "id,name,country\r\nP1,Ana,México\r\nP2,,Chile\r\n".encode())
    shas = {
        str(f.relative_to(landing)): hashlib.sha256(f.read_bytes()).hexdigest()
        for f in landing.rglob("*.csv")
    }
    lake_dir = tmp_path / "lake"
    for name, value in {
        "DATA": tmp_path,
        "LANDING": landing,
        "LAKE": lake_dir,
        "MANIFESTS": lake_dir / "manifests",
        "BRONZE_RAW": lake_dir / "bronze_raw",
        "HOLDOUT_RAW": lake_dir / "holdout_raw",
        "QUARANTINE_RAW": lake_dir / "quarantine" / "backup_raw",
        "SOURCES": {"main": main},
        "STREAM_CUTOFF": date(2026, 5, 18),
        "DATA_END": date(2026, 6, 17),
    }.items():
        monkeypatch.setattr(config, name, value)
    monkeypatch.setattr(br, "_landing_shas", lambda: shas)
    return {"landing": landing, "main": main, "shas": shas, "lake": lake_dir}


def build(table, lake, **kw):
    return br.build_table_raw(table, "run-1", landing_sha=lake["shas"], workers=1, **kw)


def test_build_proves_and_writes_every_record_as_text(lake):
    res = build(FACT, lake)
    assert res["proven"] and res["files"] == 4 and res["records"] == 8 and res["verbatim"] == 0
    con = duckdb.connect()
    hist = con.sql(f"select * from read_parquet('{config.BRONZE_RAW}/tx/**/*.parquet')").df()
    hold = con.sql(f"select * from read_parquet('{config.HOLDOUT_RAW}/tx/**/*.parquet')").df()
    assert len(hist) == 4 and len(hold) == 4  # two days before the cutoff, two from it
    row = hist.sort_values(["_source_file", "_record_no"]).iloc[1]
    assert row["note"] == "" and row["amount"] == "7"  # empty stays '', numbers stay text
    assert hist.sort_values(["_source_file", "_record_no"]).iloc[0]["note"] == "note with\nnewline"
    types = {
        r[0]: r[1]
        for r in con.sql(
            f"describe select * from read_parquet('{config.BRONZE_RAW}/tx/**/*.parquet')"
        ).fetchall()
    }
    assert all(types[c] == "VARCHAR" for c in ("id", "ts", "note", "amount"))


def test_verify_rebuilds_every_file_from_the_stored_parquet(lake):
    build(FACT, lake)
    build(DIM, lake)
    for t in (FACT, DIM):
        v = br.verify_table_raw(t)
        assert v["verified"], v["problems"]


def test_tampering_with_a_stored_value_is_detected(lake):
    build(FACT, lake)
    part = next(config.BRONZE_RAW.glob("tx/**/*.parquet"))
    con = duckdb.connect()
    con.sql(f"""copy (select * replace (case when _record_no = 1 then '99.9' else amount end as amount)
                from read_parquet('{part}')) to '{part}.new' (format parquet)""")
    Path(f"{part}.new").replace(part)
    v = br.verify_table_raw(FACT)
    assert not v["verified"] and any("rebuilt sha256" in p for p in v["problems"])


def test_a_deleted_record_is_detected(lake):
    build(FACT, lake)
    part = next(config.HOLDOUT_RAW.glob("tx/**/*.parquet"))
    con = duckdb.connect()
    con.sql(
        f"copy (select * from read_parquet('{part}') where _record_no <> 1) to '{part}.new' (format parquet)"
    )
    Path(f"{part}.new").replace(part)
    v = br.verify_table_raw(FACT)
    assert not v["verified"]
    assert any("missing" in p or "stored records" in p for p in v["problems"])


def test_a_file_changed_after_landing_fails_the_proof(lake):
    f = next(lake["main"].glob("tx/**/*.csv"))
    f.write_bytes(f.read_bytes().replace(b"10.5", b"10.6"))
    with pytest.raises(BronzeIntegrityError, match="changed since it landed"):
        build(FACT, lake)


def test_rebuild_is_a_no_op_and_a_changed_partition_is_refused(lake):
    build(FACT, lake)
    again = build(FACT, lake)
    assert again["partitions_written"] == 0
    f = next(lake["main"].glob("tx/**/*.csv"))
    f.write_bytes(f.read_bytes().replace(b"10.5", b"10.6"))
    rel = str(f.relative_to(lake["landing"]))
    lake["shas"][rel] = hashlib.sha256(f.read_bytes()).hexdigest()  # a re-landed, different file
    with pytest.raises(BronzeIntegrityError, match="would change"):
        build(FACT, lake)


def test_proof_manifest_records_every_file(lake):
    build(FACT, lake)
    proof = json.loads((config.MANIFESTS / "bronze_raw_proof" / "tx.json").read_text())["files"]
    assert len(proof) == 4
    for p in proof.values():
        assert p["sha256"] == p["landing_sha256"] == p["rebuilt_sha256"]
        assert p["records"] == p["independent_records"] == 2 and p["ok"] == 2


def test_a_landed_file_missing_from_storage_is_detected(lake):
    build(FACT, lake)
    extra = lake["main"] / "tx" / "year=2026" / "month=05" / "day=20" / "tx_20260520.csv"
    write(extra, BOM + b"id,ts,note,amount\r\nT9,2026-05-20 09:00:00,x,1\r\n")
    v = br.verify_table_raw(FACT)
    assert not v["verified"] and any("landed but not stored" in p for p in v["problems"])


class FakeS3:
    """Minimal S3 client: list_objects_v2 paginator and upload_file."""

    def __init__(self):
        self.objects: dict[str, bytes] = {}

    def get_paginator(self, _name):
        outer = self

        class P:
            def paginate(self, Bucket, Prefix):  # noqa: N803 (boto3 signature)
                yield {"Contents": [{"Key": k} for k in outer.objects if k.startswith(Prefix)]}

        return P()

    def upload_file(self, path, bucket, key):
        self.objects[key] = Path(path).read_bytes()


def test_worm_sync_uploads_new_partitions_once(lake):
    build(FACT, lake)
    s3 = FakeS3()
    first = br.worm_sync(s3, "bronze-worm", "run-1")
    assert first["partitions_uploaded"] == 4 and first["proof_manifests"] == 1
    again = br.worm_sync(s3, "bronze-worm", "run-2")
    assert again["partitions_uploaded"] == 0 and again["already_sealed"] == 4
    assert "manifests/bronze_raw_proof/run-2/tx.json" in s3.objects
