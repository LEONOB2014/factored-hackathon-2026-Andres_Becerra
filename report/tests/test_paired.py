"""The paired main-backup estimator: calibrated under the null, wider than iid under clustering, sensitive to shifts.

Simulated clustered fixtures with a known answer; never evidence about the bank.
"""

import numpy as np

from report_lib.estimators import paired


def _copy(rng, customers=2000, rows=30, p=0.2, sd=1.2, shift=0.0):
    """Per-customer null counts of one copy: a customer effect makes rows of a customer correlated."""
    logit = np.log(p / (1 - p)) + rng.normal(0, sd, customers) + shift
    pi = 1 / (1 + np.exp(-logit))
    den = rng.integers(rows // 2, rows * 2, customers).astype(float)
    num = rng.binomial(den.astype(int), pi).astype(float)
    return num, den


def _flag_rate(shift, sims=120, seed=1):
    rng = np.random.default_rng(seed)
    flags = 0
    for s in range(sims):
        nm, dm = _copy(rng)
        nb, db = _copy(rng, shift=shift)
        d0, inv = paired.halving_noise(nm, dm, reps=300, seed=s)
        tol = paired.tolerance(d0, inv, dm.sum(), db.sum())[0]
        flags += abs(nb.sum() / db.sum() - nm.sum() / dm.sum()) > tol
    return flags / sims


def test_false_alarm_rate_is_near_alpha_under_the_null():
    assert _flag_rate(0.0) <= 0.12


def test_detects_a_real_shift():
    assert _flag_rate(0.5) >= 0.9


def test_clustered_tolerance_is_wider_than_iid():
    rng = np.random.default_rng(3)
    nm, dm = _copy(rng)
    d0, inv = paired.halving_noise(nm, dm, reps=400)
    tol = paired.tolerance(d0, inv, dm.sum(), dm.sum())[0]
    iid = paired.iid_tolerance(nm.sum() / dm.sum(), dm.sum(), dm.sum())
    assert tol > 2 * iid


def test_many_columns_at_once():
    rng = np.random.default_rng(4)
    cols = [_copy(rng)[0] for _ in range(3)]
    _, den = _copy(rng)
    num = np.column_stack([np.minimum(c, den) for c in cols])
    d0, inv = paired.halving_noise(num, den, reps=50)
    assert d0.shape == (50, 3) and inv.shape == (50,)
