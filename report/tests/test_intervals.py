"""Interval estimators and the cluster policy, checked for coverage on simulated nested data.

The simulated data here are test fixtures with known truth; they are never evidence about the bank.
"""

import numpy as np
import pytest
from scipy import stats

from report_lib.estimators import intervals as iv


@pytest.mark.parametrize("num, den", [(81, 263), (0, 10), (10, 10), (1, 2), (3, 1000), (500, 1000)])
def test_wilson_matches_statsmodels(num, den):
    from statsmodels.stats.proportion import proportion_confint

    i = iv.wilson(num, den)
    lo, hi = proportion_confint(num, den, method="wilson")
    assert i.lo == pytest.approx(lo, abs=1e-12) and i.hi == pytest.approx(hi, abs=1e-12)
    assert 0.0 <= i.lo <= i.estimate <= i.hi <= 1.0


def test_poisson_exact_bounds():
    i = iv.poisson_exact(0, 100.0)
    assert i.lo == 0.0 and i.hi == pytest.approx(stats.chi2.ppf(0.975, 2) / 2 / 100)
    j = iv.poisson_exact(10, 1.0)
    assert j.lo == pytest.approx(4.7954, abs=1e-3) and j.hi == pytest.approx(18.390, abs=1e-3)


def _clustered(rng, G=60, m=40, p=0.3, sd=1.0):
    groups = np.repeat(np.arange(G), m)
    logit = np.log(p / (1 - p)) + rng.normal(0, sd, G)[groups]
    y = (rng.random(G * m) < 1 / (1 + np.exp(-logit))).astype(float)
    return y, np.ones_like(y), groups


def _truth(p=0.3, sd=1.0, n=400_000, seed=99):
    z = np.random.default_rng(seed).normal(0, sd, n)
    return float(np.mean(1 / (1 + np.exp(-(np.log(p / (1 - p)) + z)))))


def test_wilson_undercovers_and_cluster_bootstrap_covers_on_clustered_data():
    rng = np.random.default_rng(1)
    truth = _truth()
    cover_w = cover_c = 0
    sims = 200
    for s in range(sims):
        y, d, g = _clustered(rng)
        w = iv.wilson(y.sum(), d.sum())
        c = iv.cluster_bootstrap_ratio(y, d, g, B=400, seed=s)
        cover_w += w.lo <= truth <= w.hi
        cover_c += c.lo <= truth <= c.hi
    assert cover_w / sims < 0.75  # iid intervals are far too narrow under clustering
    assert 0.88 <= cover_c / sims <= 0.99


def test_cr2_and_wild_cover_with_few_clusters():
    rng = np.random.default_rng(2)
    truth = _truth()
    cover_cr2 = cover_wild = 0
    sims = 200
    for s in range(sims):
        y, d, g = _clustered(rng, G=15, m=60)
        cover_cr2 += (lambda i: i.lo <= truth <= i.hi)(iv.cr2_ratio(y, d, g))
        cover_wild += (lambda i: i.lo <= truth <= i.hi)(
            iv.wild_cluster_ratio(y, d, g, B=999, seed=s)
        )
    assert 0.85 <= cover_cr2 / sims <= 0.99
    assert 0.85 <= cover_wild / sims <= 0.99


def test_block_bootstrap_widens_under_autocorrelation():
    rng = np.random.default_rng(4)
    e = rng.normal(size=365)
    ar = np.empty(365)
    ar[0] = e[0]
    for t in range(1, 365):
        ar[t] = 0.7 * ar[t - 1] + e[t]
    block = iv.block_bootstrap_mean(ar, B=1000)
    naive_half = 1.96 * ar.std(ddof=1) / np.sqrt(len(ar))
    assert (block.hi - block.lo) / 2 > 1.5 * naive_half


def test_policy_picks_the_method_by_cluster_count():
    rng = np.random.default_rng(5)
    y, d, g = _clustered(rng, G=60)
    assert iv.ratio_by_policy(y, d).method == "wilson-iid"
    assert iv.ratio_by_policy(y, d, g).method == "cluster-bootstrap"
    y, d, g = _clustered(rng, G=15)
    assert iv.ratio_by_policy(y, d, g).method == "wild-cluster-bootstrap"
    y, d, g = _clustered(rng, G=3)
    i = iv.ratio_by_policy(y, d, g)
    assert i.method == "none" and i.lo is None and i.n_clusters == 3
