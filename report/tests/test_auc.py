"""DeLong AUC: matches the Mann-Whitney AUC, and its interval covers the truth at about the nominal rate."""

import numpy as np
import pytest
from sklearn.metrics import roc_auc_score

from report_lib.estimators.auc import delong


def test_estimate_matches_sklearn_with_ties():
    rng = np.random.default_rng(0)
    y = rng.random(2000) < 0.2
    s = np.round(rng.normal(size=2000) + 0.8 * y, 1)  # rounding creates ties
    assert delong(y, s).estimate == pytest.approx(roc_auc_score(y, s), abs=1e-12)


def test_interval_covers_the_true_auc():
    # binormal model: positives N(d, 1), negatives N(0, 1), so AUC = Phi(d / sqrt(2))
    from scipy.stats import norm

    d, truth, hits = 0.6, norm.cdf(0.6 / np.sqrt(2)), 0
    rng = np.random.default_rng(1)
    for _ in range(300):
        y = np.r_[np.ones(150, bool), np.zeros(600, bool)]
        s = np.r_[rng.normal(d, 1, 150), rng.normal(0, 1, 600)]
        iv = delong(y, s)
        hits += iv.lo <= truth <= iv.hi
    assert 0.90 <= hits / 300 <= 0.98


def test_needs_both_classes():
    with pytest.raises(ValueError):
        delong(np.ones(5, bool), np.arange(5.0))
