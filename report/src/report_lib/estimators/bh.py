"""Benjamini–Hochberg step-up adjustment (Benjamini and Hochberg, 1995).

For ordered p-values p(1) <= ... <= p(m), the adjusted value of p(i) is min over j >= i of m p(j) / j, capped at 1.
Rejecting every hypothesis with adjusted value <= alpha controls the false discovery rate at alpha for
independent or positively dependent tests.
"""

from __future__ import annotations

import numpy as np


def adjust(p) -> np.ndarray:
    p = np.asarray(p, dtype=float)
    if p.ndim != 1:
        raise ValueError("p must be one-dimensional")
    if np.isnan(p).any():
        raise ValueError("p contains NaN; drop untested hypotheses before adjusting")
    if ((p < 0) | (p > 1)).any():
        raise ValueError("p-values must lie in [0, 1]")
    m = len(p)
    if m == 0:
        return p.copy()
    order = np.argsort(p, kind="mergesort")
    scaled = p[order] * m / np.arange(1, m + 1)
    adjusted = np.minimum(np.minimum.accumulate(scaled[::-1])[::-1], 1.0)
    out = np.empty(m)
    out[order] = adjusted
    return out


def reject(p, alpha: float = 0.05) -> np.ndarray:
    return adjust(p) <= alpha
