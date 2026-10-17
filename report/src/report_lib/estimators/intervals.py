"""Interval estimators for the report's claims, chosen by the cluster policy frozen in conf/protocol.toml.

- iid data: Wilson (1927) for proportions, exact Poisson (Garwood 1936) for rates;
- clustered data with at least MIN_CLUSTERS clusters: percentile cluster bootstrap of a ratio of sums;
- 10 to 29 clusters: CR2 cluster-robust interval (Bell and McCaffrey 2002) with t(G − 1) reference, and the wild
  cluster bootstrap with Rademacher weights (Cameron, Gelbach and Miller 2008);
- fewer than 10 clusters: no inferential interval (the claim is descriptive);
- serially dependent day series: stationary bootstrap (Politis and Romano 1994) with the Politis–White block length.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy import stats

from latam_eda import granularity as _g

MIN_CLUSTERS = _g.MIN_CLUSTERS
MIN_FEW = 10
Z95 = stats.norm.ppf(0.975)


@dataclass(frozen=True)
class Interval:
    estimate: float
    lo: float | None
    hi: float | None
    method: str  # one of manifest.IntervalMethod, or "none" for a descriptive claim
    n_clusters: int | None = None


def wilson(num: float, den: float, level: float = 0.95) -> Interval:
    if den <= 0:
        raise ValueError("denominator must be positive")
    z = stats.norm.ppf(0.5 + level / 2)
    p = num / den
    centre = (p + z**2 / (2 * den)) / (1 + z**2 / den)
    half = z * np.sqrt(p * (1 - p) / den + z**2 / (4 * den**2)) / (1 + z**2 / den)
    # at p = 0 or 1 the boundary bound is exact (floating point would otherwise leave it just inside)
    lo = 0.0 if num == 0 else max(0.0, centre - half)
    hi = 1.0 if num == den else min(1.0, centre + half)
    return Interval(p, lo, hi, "wilson-iid")


def poisson_exact(events: float, exposure: float, level: float = 0.95) -> Interval:
    if exposure <= 0:
        raise ValueError("exposure must be positive")
    a = 1 - level
    lo = 0.0 if events == 0 else stats.chi2.ppf(a / 2, 2 * events) / 2
    hi = stats.chi2.ppf(1 - a / 2, 2 * events + 2) / 2
    return Interval(events / exposure, lo / exposure, hi / exposure, "poisson-exact")


def _cluster_sums(num, den, groups):
    codes, _ = __import__("pandas").factorize(np.asarray(groups), sort=True)
    g = codes.max() + 1
    return np.bincount(codes, np.asarray(num, float), g), np.bincount(
        codes, np.asarray(den, float), g
    )


def cluster_bootstrap_ratio(
    num, den, groups, B: int = 2000, seed: int = 0, level: float = 0.95
) -> Interval:
    """sum(num)/sum(den) with a percentile interval from resampling whole clusters."""
    n_c, d_c = _cluster_sums(num, den, groups)
    G = len(n_c)
    rng = np.random.default_rng(seed)
    pick = rng.integers(0, G, (B, G))
    draws = n_c[pick].sum(1) / d_c[pick].sum(1)
    a = (1 - level) / 2
    lo, hi = np.quantile(draws, [a, 1 - a])
    return Interval(n_c.sum() / d_c.sum(), float(lo), float(hi), "cluster-bootstrap", G)


def cr2_ratio(num, den, groups, level: float = 0.95) -> Interval:
    """Ratio of sums as a weighted mean of cluster ratios, with a CR2 standard error and a t(G − 1) interval.

    With weights w_g = d_g / sum(d), the estimate is sum(w_g r_g); its residuals e_g = r_g − estimate get the CR2
    leverage correction 1 / sqrt(1 − h_g), h_g = w_g, for the intercept-only weighted model.
    """
    n_c, d_c = _cluster_sums(num, den, groups)
    G = len(n_c)
    w = d_c / d_c.sum()
    r = n_c / d_c
    est = float(np.sum(w * r))
    e = (r - est) / np.sqrt(1 - w)
    se = float(np.sqrt(np.sum((w * e) ** 2)))
    t = stats.t.ppf(0.5 + level / 2, G - 1)
    return Interval(est, est - t * se, est + t * se, "cr2", G)


def wild_cluster_ratio(
    num, den, groups, B: int = 4999, seed: int = 0, level: float = 0.95
) -> Interval:
    """Wild cluster bootstrap-t (Rademacher weights) for a ratio of sums, inverting the CR2 statistic."""
    n_c, d_c = _cluster_sums(num, den, groups)
    G = len(n_c)
    base = cr2_ratio(num, den, groups, level)
    w = d_c / d_c.sum()
    r = n_c / d_c
    est = base.estimate
    se0 = (base.hi - est) / stats.t.ppf(0.5 + level / 2, G - 1)
    resid = r - est
    rng = np.random.default_rng(seed)
    v = rng.choice([-1.0, 1.0], (B, G))
    rb = est + v * resid
    est_b = (rb * w).sum(1)
    eb = (rb - est_b[:, None]) / np.sqrt(1 - w)
    se_b = np.sqrt(((w * eb) ** 2).sum(1))
    tb = (est_b - est) / np.where(se_b > 0, se_b, np.nan)
    a = (1 - level) / 2
    q_lo, q_hi = np.nanquantile(tb, [a, 1 - a])
    return Interval(est, est - q_hi * se0, est - q_lo * se0, "wild-cluster-bootstrap", G)


def block_bootstrap_mean(series, B: int = 2000, seed: int = 0, level: float = 0.95) -> Interval:
    """Mean of a serially dependent series (one value per day), stationary bootstrap with Politis–White blocks."""
    x = np.asarray(series, float)
    x = x[~np.isnan(x)]
    L = _g.politis_white_block(x)
    rng = np.random.default_rng(seed)
    draws = np.array([x[_g.stationary_units(len(x), L, rng)].mean() for _ in range(B)])
    a = (1 - level) / 2
    lo, hi = np.quantile(draws, [a, 1 - a])
    return Interval(float(x.mean()), float(lo), float(hi), "block-bootstrap", len(x))


def ratio_by_policy(num, den, groups=None, seed: int = 0) -> Interval:
    """The cluster policy: iid Wilson without groups; by cluster count otherwise (bootstrap, CR2 + wild, none)."""
    if groups is None:
        return wilson(float(np.sum(num)), float(np.sum(den)))
    G = len(set(np.asarray(groups).tolist()))
    if G >= MIN_CLUSTERS:
        return cluster_bootstrap_ratio(num, den, groups, seed=seed)
    if G >= MIN_FEW:
        return wild_cluster_ratio(num, den, groups, seed=seed)
    n_c, d_c = _cluster_sums(num, den, groups)
    return Interval(float(n_c.sum() / d_c.sum()), None, None, "none", G)
