"""Paired tests and resampling for item-level evaluations (each case, attack or call is one independent item).

- exact McNemar test (McNemar 1947) for two systems scored on the same items: under the null of equal accuracy the
  discordant items split as Binomial(b + c, 1/2), and the two-sided p-value is twice the smaller tail, capped at 1;
- percentile bootstrap over items of any statistic (a median, a high percentile, a macro-F1).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

import numpy as np
from scipy import stats

from report_lib.estimators.intervals import Interval


@dataclass(frozen=True)
class McNemar:
    b: int  # items the first system gets right and the second wrong
    c: int  # items the second gets right and the first wrong
    p: float


def mcnemar_exact(first, second) -> McNemar:
    first, second = np.asarray(first, dtype=bool), np.asarray(second, dtype=bool)
    if first.shape != second.shape:
        raise ValueError("both systems must be scored on the same items")
    b, c = int((first & ~second).sum()), int((~first & second).sum())
    p = 1.0 if b + c == 0 else min(1.0, 2 * stats.binom.cdf(min(b, c), b + c, 0.5))
    return McNemar(b, c, float(p))


def bootstrap(
    values, stat: Callable[[np.ndarray], float], reps: int, seed: int, level: float = 0.95
) -> Interval:
    """Percentile interval of `stat` over items resampled with replacement; `values` is 1-d or rows of a 2-d array."""
    x = np.asarray(values)
    if len(x) == 0:
        raise ValueError("no items to resample")
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(x), size=(reps, len(x)))
    draws = np.array([stat(x[i]) for i in idx])
    a = (1 - level) / 2
    return Interval(
        float(stat(x)),
        float(np.quantile(draws, a)),
        float(np.quantile(draws, 1 - a)),
        "bootstrap-iid",
    )


def zero_events_upper(n: int, level: float = 0.95) -> float:
    """One-sided exact (Clopper-Pearson) upper bound of a proportion when none of n items is an event."""
    return float(1 - (1 - level) ** (1 / n))
