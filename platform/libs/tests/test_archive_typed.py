"""Retiring typed bronze moves it into a read-only archive: nothing copied, nothing deleted, never overwritten."""

from __future__ import annotations

import json

import pytest

from latam_platform import config
from latam_platform.lakehouse import bronze


@pytest.fixture
def lake(tmp_path, monkeypatch):
    data = tmp_path / "data"
    lake = data / "lake"
    monkeypatch.setattr(config, "DATA", data)
    monkeypatch.setattr(config, "BRONZE", lake / "bronze")
    monkeypatch.setattr(config, "HOLDOUT", lake / "holdout")
    monkeypatch.setattr(config, "QUARANTINE", lake / "quarantine")
    monkeypatch.setattr(config, "MANIFESTS", lake / "manifests")
    monkeypatch.setattr(config, "ARCHIVE_TYPED", lake / "archive" / "bronze_typed_v1")
    for rel in ("bronze/transactions/process_date=2025-01-01/part-0.parquet",
                "holdout/transactions/process_date=2026-06-01/part-0.parquet",
                "quarantine/backup_20260831/customers.parquet",
                "manifests/bronze/transactions.json",
                "quarantine/backup_20260831_raw/customers/snapshot_date=2026-06-17/part-0.parquet"):  # fmt: skip
        p = lake / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(rel.encode())
    yield lake
    for p in sorted(
        (lake / "archive").rglob("*"), key=lambda p: -len(p.parts)
    ):  # let tmp_path clean up
        p.chmod(0o755)
    (lake / "archive").chmod(0o755)


def test_typed_zones_move_into_a_read_only_archive(lake):
    out = bronze.archive_typed()
    arch = lake / "archive" / "bronze_typed_v1"
    assert set(out["moved"]) == {"lake/bronze", "lake/holdout", "lake/quarantine/backup_20260831",
                                 "lake/manifests/bronze"}  # fmt: skip
    assert not (lake / "bronze").exists() and (arch / "bronze" / "transactions").is_dir()
    assert (lake / "quarantine" / "backup_20260831_raw").exists(), (
        "the lossless copies are not touched"
    )
    f = arch / "bronze/transactions/process_date=2025-01-01/part-0.parquet"
    assert f.read_bytes() == b"bronze/transactions/process_date=2025-01-01/part-0.parquet"
    with pytest.raises(PermissionError):
        f.write_bytes(b"x")
    with pytest.raises(PermissionError):
        f.unlink()
    record = json.loads(next(arch.glob("ARCHIVE_*.json")).read_text())
    assert (
        record["moved"]["lake/bronze"]["files"] == 1
        and len(record["moved"]["lake/bronze"]["sha256"]) == 64
    )

    again = bronze.archive_typed()
    assert (
        again["moved"] == {} and "lake/archive/bronze_typed_v1/bronze" in again["already_archived"]
    )
