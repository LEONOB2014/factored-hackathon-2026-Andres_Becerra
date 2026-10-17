"""The paired main-backup estimator (report-only, Chapter 6).

For a share computed in each copy, D = share(backup) - share(main). Its noise under the hypothesis that both copies
come from the same process is calibrated on the main copy alone: split main's clusters (customers) at random into
halves A and B, many times, and record D0 = share(A) - share(B). Clusters, not rows, are split, so within-customer
dependence is kept (Chapter 2). D0 has variance proportional to 1/n_A + 1/n_B, while D has variance proportional to
1/n_main + 1/n_backup, so the tolerance rescales the 1 - alpha quantile of |D0| by the ratio of those terms:

    tolerance = quantile(|D0|, 1 - alpha) * sqrt((1/n_main + 1/n_backup) / mean(1/n_A + 1/n_B)).

A difference is material when |D| > tolerance. The frozen protocol uses the same construction, on each gate's metric,
as the main-backup tolerance of Chapter 19.
"""

from __future__ import annotations

import numpy as np


def halving_noise(
    num: np.ndarray, den: np.ndarray, reps: int = 400, seed: int = 0
) -> tuple[np.ndarray, np.ndarray]:
    """D0 replicates for every column at once.

    `num` is clusters x columns (e.g. null counts per customer and column), `den` the rows per cluster. Returns the
    replicates (reps x columns) and 1/n_A + 1/n_B per replicate.
    """
    num = np.asarray(num, dtype=float)
    den = np.asarray(den, dtype=float)
    if num.ndim == 1:
        num = num[:, None]
    rng = np.random.default_rng(seed)
    a = rng.random((reps, len(den))) < 0.5
    na, nb = a @ den, (~a) @ den
    sa, sb = a.astype(float) @ num, (~a).astype(float) @ num
    d0 = sa / na[:, None] - sb / nb[:, None]
    return d0, 1 / na + 1 / nb


def tolerance(
    d0: np.ndarray, inv_halves: np.ndarray, n_main: float, n_backup: float, alpha: float = 0.05
):
    """The 1 - alpha tolerance for |share(backup) - share(main)|, one per column."""
    scale = np.sqrt((1 / n_main + 1 / n_backup) / np.mean(inv_halves))
    return np.quantile(np.abs(d0), 1 - alpha, axis=0) * scale


def iid_tolerance(p_main: np.ndarray, n_main: float, n_backup: float, z: float = 1.959963984540054):
    """What the tolerance would be if rows were independent (two-proportion normal approximation)."""
    p = np.asarray(p_main, dtype=float)
    return z * np.sqrt(p * (1 - p) * (1 / n_main + 1 / n_backup))
