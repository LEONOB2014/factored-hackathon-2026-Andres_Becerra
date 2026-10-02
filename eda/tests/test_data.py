"""latam_eda.data: table catalogue and the DuckDB connection the notebooks share."""

import os
import subprocess
import sys
from pathlib import Path

from latam_eda import data


def test_catalogue_has_the_13_documented_tables():
    assert len(data.FACTS) == 7
    assert len(data.DIMS) == 6
    assert not set(data.FACTS) & set(data.DIMS)


def test_every_table_with_a_single_key_has_a_primary_key():
    # daily_exchange_rates has a composite key (date, source, target) and is left out on purpose
    assert set(data.PK) == set(data.FACTS) | set(data.DIMS) - {"daily_exchange_rates"}
    assert all(v.endswith("_id") for v in data.PK.values())


def test_paths_live_under_the_data_folder():
    assert data.MAIN.parent == data.DATA
    assert data.BACKUP.parent == data.DATA
    assert data.DERIVED.parent == data.DATA


def test_data_folder_can_be_redirected(tmp_path):
    src = str(Path(data.__file__).resolve().parents[1])
    env = {**os.environ, "LATAM_EDA_DATA": str(tmp_path), "PYTHONPATH": src}
    out = subprocess.run(
        [sys.executable, "-c", "from latam_eda import data; print(data.MAIN)"],
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    assert out.stdout.strip() == str(tmp_path.resolve() / "parquet")
    assert (tmp_path / "derived").is_dir()  # created on import for notebook outputs


def test_connect_exposes_main_and_backup_views(tiny_dataset):
    con = data.connect()
    views = {
        r[0] for r in con.sql("select view_name from duckdb_views() where not internal").fetchall()
    }
    assert views == {
        "m_customers",
        "m_branches",
        "m_service_agents",
        "b_customers",
        "b_branches",
        "b_service_agents",
    }
    assert con.sql("select count(*) from m_customers").fetchone()[0] == 3
    shared = con.sql(
        "select count(*) from m_customers join b_customers using (customer_id)"
    ).fetchone()[0]
    assert shared == 2


def test_connect_with_no_parquet_files_has_no_views(tmp_path, monkeypatch):
    monkeypatch.setattr(data, "MAIN", tmp_path / "none")
    monkeypatch.setattr(data, "BACKUP", tmp_path / "none")
    con = data.connect()
    assert con.sql("select count(*) from duckdb_views() where not internal").fetchone()[0] == 0
