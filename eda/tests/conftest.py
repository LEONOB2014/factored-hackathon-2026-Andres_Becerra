"""Shared fixtures for the EDA test suite.

Tests marked `data` read the real dataset (eda/data/, or wherever LATAM_EDA_DATA
points) and are skipped when it has not been downloaded, as in CI.
"""

from pathlib import Path

import duckdb
import pytest

from latam_eda import data

EDA = Path(__file__).resolve().parents[1]
REPO = EDA.parent
NOTEBOOKS = EDA / "notebooks"
TABLES = EDA / "reports" / "tables"


def dataset_available() -> bool:
    return any(data.MAIN.glob("*.parquet")) and any(data.BACKUP.glob("*.parquet"))


def pytest_collection_modifyitems(config, items):
    if dataset_available():
        return
    skip = pytest.mark.skip(reason=f"dataset not found under {data.DATA} (set LATAM_EDA_DATA)")
    for item in items:
        if "data" in item.keywords:
            item.add_marker(skip)


@pytest.fixture
def tiny_dataset(tmp_path, monkeypatch):
    """Main and backup Parquet folders with three small tables, wired into latam_eda.data."""
    main, backup = tmp_path / "parquet", tmp_path / "parquet_backup"
    main.mkdir()
    backup.mkdir()
    con = duckdb.connect()
    tables = {
        main: {
            "customers": "select * from (values ('C1', 'MX', 700), ('C2', 'CO', 640), "
            "('C3', 'AR', 580)) t(customer_id, country, credit_score)",
            "branches": "select * from (values ('B1', 'Centro'), ('B2', 'Norte')) t(branch_id, name)",
            "service_agents": "select * from (values ('A1'), ('A2')) t(agent_id)",
        },
        backup: {
            # C2 re-scored, C3 replaced by C4: one changed value, one key on each side only
            "customers": "select * from (values ('C1', 'MX', 700), ('C2', 'CO', 655), "
            "('C4', 'AR', 610)) t(customer_id, country, credit_score)",
            "branches": "select * from (values ('B1', 'Centro'), ('B2', 'Norte')) t(branch_id, name)",
            "service_agents": "select * from (values ('A1'), ('A3')) t(agent_id)",
        },
    }
    for folder, queries in tables.items():
        for name, q in queries.items():
            con.sql(f"copy ({q}) to '{folder / name}.parquet' (format parquet)")
    monkeypatch.setattr(data, "MAIN", main)
    monkeypatch.setattr(data, "BACKUP", backup)
    return main, backup
