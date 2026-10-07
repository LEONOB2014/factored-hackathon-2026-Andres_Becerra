"""The report's own Benjamini–Hochberg equals latam_eda's and statsmodels' (eng review T2)."""

import numpy as np
import pandas as pd
import pytest
from statsmodels.stats.multitest import multipletests

from latam_eda.granularity import bh_fdr  # noqa: E402
from report_lib import eda  # noqa: F401
from report_lib.estimators import bh
from report_lib.paths import TABLES


def _vectors():
    rng = np.random.default_rng(7)
    yield np.array([0.03])
    yield np.array([0.0, 1.0])
    for m in (2, 10, 50, 1000):
        p = rng.uniform(size=m)
        p[: m // 5] = rng.uniform(0, 0.01, m // 5)
        p[m // 2 :][: m // 10] = p[0]  # ties
        p[-1:] = 1.0
        p[:1] = 0.0
        yield p


@pytest.mark.parametrize("p", list(_vectors()))
def test_matches_bh_fdr_and_statsmodels(p):
    ours = bh.adjust(p)
    assert np.allclose(ours, bh_fdr(p)[1], rtol=0, atol=1e-15)
    assert np.allclose(ours, multipletests(p, method="fdr_bh")[1], rtol=0, atol=1e-15)


@pytest.mark.parametrize(
    "table, column",
    [
        ("granularity_signal.csv", "p_adjusted"),
        ("granularity_hour_signal.csv", "q_value"),
        ("granularity_time_signal.csv", "q_value"),
    ],
)
def test_reproduces_the_notebooks_stored_q_values(table, column):
    d = pd.read_csv(TABLES / table)
    assert np.allclose(bh.adjust(d["p_value"]), d[column], rtol=1e-12, atol=1e-15)


def test_matches_on_every_p_column_of_the_stored_tables():
    checked = 0
    for path in sorted(TABLES.glob("*.csv")):
        d = pd.read_csv(path)
        for col in [c for c in d.columns if c in ("p_value", "logrank_p")]:
            p = d[col].dropna().to_numpy(dtype=float)
            if len(p):
                assert np.allclose(bh.adjust(p), bh_fdr(p)[1], rtol=0, atol=1e-15), (path.name, col)
                checked += 1
    assert checked >= 30


@pytest.mark.parametrize("bad", [[0.1, float("nan")], [-0.1], [1.2], [[0.1]]])
def test_rejects_invalid_input(bad):
    with pytest.raises(ValueError):
        bh.adjust(bad)
