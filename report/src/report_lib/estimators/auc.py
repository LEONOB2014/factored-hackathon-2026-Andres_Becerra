"""The area under the ROC curve with the DeLong variance, computed by the midrank algorithm of Sun and Xu (2014).

The AUC is the Mann-Whitney probability that a random positive scores above a random negative (ties count one
half). DeLong, DeLong and Clarke-Pearson (1988) estimate its variance from the structural components
V10_i (the share of negatives positive i beats) and V01_j (the share of positives that beat negative j):

    Var(AUC) = Var(V10) / m + Var(V01) / n,

with m positives and n negatives. Rows are treated as independent; the interval is a normal one, clipped to [0, 1].
"""

from __future__ import annotations

import numpy as np
from scipy import stats

from report_lib.estimators.intervals import Interval


def _midrank(x: np.ndarray) -> np.ndarray:
    return stats.rankdata(x, method="average")


def delong(y, score, level: float = 0.95) -> Interval:
    """AUC of `score` for the binary label `y`, with a DeLong interval (method "delong")."""
    y = np.asarray(y).astype(bool)
    s = np.asarray(score, float)
    pos, neg = s[y], s[~y]
    m, n = len(pos), len(neg)
    if m == 0 or n == 0:
        raise ValueError("AUC needs both classes")
    r_all = _midrank(np.concatenate([pos, neg]))
    r_pos, r_neg = _midrank(pos), _midrank(neg)
    auc = (r_all[:m].sum() - m * (m + 1) / 2) / (m * n)
    v10 = (r_all[:m] - r_pos) / n
    v01 = 1 - (r_all[m:] - r_neg) / m
    var = np.var(v10, ddof=1) / m + np.var(v01, ddof=1) / n
    z = stats.norm.ppf(0.5 + level / 2)
    se = float(np.sqrt(var))
    return Interval(float(auc), max(0.0, auc - z * se), min(1.0, auc + z * se), "delong", None)
