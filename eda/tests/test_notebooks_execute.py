"""Opt-in: execute each notebook against the real data and check its tables reproduce.

    uv run pytest -m notebooks              # all eleven (long: full-data analysis)
    uv run pytest -m notebooks -k 02        # one notebook

Each notebook runs in a scratch copy of eda/ (src, notebooks, committed tables), so the
committed reports are never touched; only the shared cache in data/derived/ is written,
as a normal run would. The tables a notebook writes are then compared with the
committed ones: same shape and columns, numbers equal to a relative 1e-6.
"""

import shutil

import nbformat
import pandas as pd
import pytest
from nbclient import NotebookClient

import build_notebook
from conftest import EDA, TABLES
from latam_eda import data
from test_notebook_sources import SOURCES, WRITES

pytestmark = [pytest.mark.notebooks, pytest.mark.data, pytest.mark.slow]


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    for sub in ("src", "notebooks"):
        shutil.copytree(
            EDA / sub, tmp_path / sub, ignore=shutil.ignore_patterns("*.ipynb", "__pycache__")
        )
    shutil.copytree(TABLES, tmp_path / "reports" / "tables")
    # the kernel inherits this, so the copy reads the same dataset
    monkeypatch.setenv("LATAM_EDA_DATA", str(data.DATA))
    return tmp_path


def assert_same_table(produced: pd.DataFrame, committed: pd.DataFrame, name: str):
    assert list(produced.columns) == list(committed.columns), name
    assert produced.shape == committed.shape, name
    for col in committed.columns:
        if col.endswith(" s"):
            continue  # wall-clock seconds (e.g. "fit+score s") never reproduce
        a, b = produced[col], committed[col]
        if pd.api.types.is_numeric_dtype(b) and pd.api.types.is_numeric_dtype(a):
            pd.testing.assert_series_equal(a, b, check_dtype=False, rtol=1e-6, obj=f"{name}.{col}")
        else:
            assert a.astype(str).tolist() == b.astype(str).tolist(), f"{name}.{col}"


@pytest.mark.parametrize("src", SOURCES, ids=lambda p: p.stem)
def test_notebook_runs_and_reproduces_its_tables(src, workspace):
    copy = workspace / "notebooks" / src.name
    ipynb = build_notebook.build(copy, html_dir=None)
    nb = nbformat.read(ipynb, as_version=4)
    NotebookClient(
        nb,
        timeout=3600,
        kernel_name="python3",
        resources={"metadata": {"path": str(copy.parent)}},
    ).execute()

    for name in WRITES.findall(src.read_text()):
        produced = pd.read_csv(workspace / "reports" / "tables" / name)
        committed = pd.read_csv(TABLES / name)
        assert_same_table(produced, committed, name)
