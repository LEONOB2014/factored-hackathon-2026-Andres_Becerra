"""Change detection on daily fingerprint series, and classification of what changed.

Two kinds of signal come out of raw_forensics:
* discrete: is a value class / vocabulary value / header present on a given day?
* continuous: the share of a class, a null rate, a log10 scale, per day.

Discrete signals are classified with a persistence rule:
  stable       present on (almost) every day;
  born / died  absent then present (or the reverse) for at least `k` consecutive days: evolution;
  transient    appears on fewer than `k` consecutive days: an incident, not a schema change;
  coexisting   present throughout alongside another class of the same column: design heterogeneity
               (two formats or two sources feeding one column), reported by the caller.
Continuous signals use change points (binary segmentation with a permutation test on the
standardized CUSUM statistic; PELT with a permutation-calibrated penalty as a slower cross-check), a two-sided CUSUM
on weekday-adjusted values, robust z-scores and binomial rate tests with Benjamini-Hochberg control.
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd
from scipy import stats


# ------------------------------------------------------------------------------------ discrete
def longest_run(present: np.ndarray) -> int:
    best = run = 0
    for x in present:
        run = run + 1 if x else 0
        best = max(best, run)
    return best


def classify_presence(
    present: pd.Series, k: int = 7, stable_share: float = 0.98, alpha: float = 0.001
) -> dict:
    """Classify a daily boolean presence series (index = dates).

    Within its own span (first to last day seen) a value recurs with daily rate p. Under a stationary
    presence, a run of L absent days has probability (1 - p)^L, so an absence before the first sighting
    (or after the last) is significant when (1 - p)^L < alpha. That separates a late-born value
    (e.g. a channel launched months after the table starts, even if it is sparse afterwards) from a
    rare value that merely skipped a few days.

    stable        present on >= stable_share of the days;
    born / died   significant absence before the first / after the last sighting: evolution;
    episode       significant absence on both sides: born, then died;
    intermittent  no significant absence: a rare but normal value, not a change;
    transient     present on fewer than k days in total: an isolated incident;
    absent        never present.
    """
    s = present.sort_index().astype(bool)
    on = s.to_numpy()
    if not on.any():
        return {"kind": "absent", "first_seen": None, "last_seen": None, "coverage": 0.0}
    days = s.index
    first, last = int(on.argmax()), len(on) - 1 - int(on[::-1].argmax())
    coverage = float(on.mean())
    rate = float(on[first : last + 1].mean())
    lead, trail = first, len(on) - 1 - last
    late = lead >= k and (1 - rate) ** lead < alpha
    early = trail >= k and (1 - rate) ** trail < alpha
    if coverage >= stable_share:
        kind = "stable"
    elif on.sum() < k:
        kind = "transient"
    elif late and early:
        kind = "episode"
    elif late:
        kind = "born"
    elif early:
        kind = "died"
    else:
        kind = "intermittent"
    return {
        "kind": kind,
        "first_seen": days[first],
        "last_seen": days[last],
        "coverage": round(coverage, 4),
    }


def jaccard(a: set, b: set) -> float:
    return 1.0 if not a and not b else len(a & b) / len(a | b)


def jensen_shannon(p: np.ndarray, q: np.ndarray) -> float:
    """Jensen-Shannon divergence (natural log, bounded by ln 2) between two distributions."""
    p, q = np.asarray(p, float), np.asarray(q, float)
    p, q = p / p.sum(), q / q.sum()
    m = (p + q) / 2

    def kl(a, b):
        mask = a > 0
        return float(np.sum(a[mask] * np.log(a[mask] / b[mask])))

    return 0.5 * kl(p, m) + 0.5 * kl(q, m)


def day_over_day_jsd(shares: pd.DataFrame) -> pd.Series:
    """JSD between consecutive days of a class-share matrix (rows = days)."""
    rows = shares.to_numpy() + 1e-12
    vals = [np.nan] + [jensen_shannon(rows[i - 1], rows[i]) for i in range(1, len(rows))]
    return pd.Series(vals, index=shares.index)


# ---------------------------------------------------------------------------------- continuous
def robust_z(x: pd.Series) -> pd.Series:
    """(x - median) / (1.4826 MAD); 0 where MAD is 0 and x equals the median."""
    med = x.median()
    mad = 1.4826 * (x - med).abs().median()
    if mad == 0:
        return (x - med).apply(lambda d: 0.0 if d == 0 else math.copysign(np.inf, d))
    return (x - med) / mad


def weekday_adjust(x: pd.Series) -> pd.Series:
    """Remove the weekday profile (median per weekday) from a daily series with a date index."""
    idx = pd.to_datetime(x.index)
    dow = pd.Series(idx.dayofweek, index=x.index)
    return x - x.groupby(dow).transform("median")


def cusum(x: pd.Series, k: float = 0.5, h: float = 5.0, warmup: int = 60) -> list:
    """Two-sided tabular CUSUM on standardized values; returns the dates where an alarm starts.

    Mean and sd come from the first `warmup` points (the reference period). k and h are in sd units.
    """
    ref = x.iloc[:warmup]
    sd = ref.std(ddof=1) or 1e-12
    z = ((x - ref.mean()) / sd).to_numpy()
    hi = lo = 0.0
    alarms, armed = [], True
    for d, v in zip(x.index, z):
        hi, lo = max(0.0, hi + v - k), min(0.0, lo + v + k)
        if (hi > h or lo < -h) and armed:
            alarms.append(d)
            armed = False
        if hi == 0.0 and lo == 0.0:
            armed = True
    return alarms


def pelt(x: np.ndarray, penalty: float, model: str = "l2", min_size: int = 7) -> list[int]:
    """Change-point indices (start of each new segment) by PELT."""
    import ruptures as rpt

    if len(x) < 2 * min_size:
        return []
    bkps = (
        rpt.Pelt(model=model, min_size=min_size)
        .fit(np.asarray(x, float).reshape(-1, 1))
        .predict(pen=penalty)
    )
    return [b for b in bkps if b < len(x)]


def calibrated_penalty(
    x: np.ndarray, alpha: float = 0.05, n_perm: int = 50, seed: int = 0, model: str = "l2"
) -> float:
    """Smallest penalty for which PELT finds a change in at most `alpha` of permuted copies of x.

    Permuting destroys any change point while keeping the marginal distribution, so the result
    controls the false-alarm rate of the detector on this very series.
    """
    rng = np.random.default_rng(seed)
    x = np.asarray(x, float)
    scale = float(np.var(x)) or 1e-12
    grid = scale * np.log(len(x)) * np.array([0.5, 1, 2, 3, 5, 8, 13, 21, 34])
    perms = [rng.permutation(x) for _ in range(n_perm)]
    for pen in grid:
        false = sum(bool(pelt(px, pen, model)) for px in perms) / n_perm
        if false <= alpha:
            return float(pen)
    return float(grid[-1])


def _max_cusum(x: np.ndarray, min_size: int) -> tuple[int, float]:
    """Split index and value of the max standardized CUSUM |S_k| / sqrt(k (n-k) / n), rows = series."""
    x = np.atleast_2d(x)
    n = x.shape[1]
    s = np.cumsum(x - x.mean(axis=1, keepdims=True), axis=1)[:, :-1]
    k = np.arange(1, n)
    stat = np.abs(s) / np.sqrt(k * (n - k) / n)
    stat[:, : min_size - 1] = 0
    stat[:, n - min_size :] = 0
    idx = stat.argmax(axis=1)
    return idx + 1, stat[np.arange(len(stat)), idx]


def binseg(
    x: np.ndarray, alpha: float = 0.01, n_perm: int = 199, min_size: int = 7, seed: int = 0
) -> list[int]:
    """Change points by binary segmentation; each split must pass a permutation test at level alpha.

    The statistic is the max standardized CUSUM of the segment; its null distribution comes from
    `n_perm` permutations of that segment (computed at once with numpy). Permuting destroys any change
    point but keeps the marginal distribution, so the false-alarm rate is controlled on the data
    itself without distributional assumptions. Returns the start index of each new segment.
    """
    rng = np.random.default_rng(seed)
    x = np.asarray(x, float)
    found: list[int] = []

    def split(lo: int, hi: int) -> None:
        seg = x[lo:hi]
        if len(seg) < 2 * min_size or np.ptp(seg) == 0:
            return
        (cut,), (obs,) = _max_cusum(seg, min_size)
        perms = np.array([rng.permutation(seg) for _ in range(n_perm)])
        _, null = _max_cusum(perms, min_size)
        if (1 + (null >= obs).sum()) / (n_perm + 1) <= alpha:
            found.append(lo + int(cut))
            split(lo, lo + int(cut))
            split(lo + int(cut), hi)

    split(0, len(x))
    return sorted(found)


def benjamini_hochberg(p: np.ndarray, q: float = 0.05) -> np.ndarray:
    """Boolean mask of discoveries at false-discovery rate q."""
    p = np.asarray(p, float)
    n = len(p)
    order = np.argsort(p)
    thresh = q * (np.arange(1, n + 1) / n)
    passed = p[order] <= thresh
    k = np.max(np.nonzero(passed)[0]) + 1 if passed.any() else 0
    out = np.zeros(n, bool)
    out[order[:k]] = True
    return out


def rate_shift_tests(k: pd.Series, n: pd.Series, warmup: int = 60, q: float = 0.05) -> pd.DataFrame:
    """Per-day two-sided binomial test of k/n against the reference rate (first `warmup` days), BH-adjusted."""
    p0 = k.iloc[:warmup].sum() / max(n.iloc[:warmup].sum(), 1)
    pv = np.array(
        [stats.binomtest(int(ki), int(ni), p0).pvalue if ni else 1.0 for ki, ni in zip(k, n)]
    )
    return pd.DataFrame(
        {"rate": k / n.replace(0, np.nan), "p_value": pv, "flag": benjamini_hochberg(pv, q)},
        index=k.index,
    )


def scale_steps(log10_median: pd.Series, tol: float = 0.15, min_step: float = 0.1) -> pd.DataFrame:
    """Step changes in a daily log10 location, annotated with the implied multiplicative factor.

    A step whose size is close to log10 of a power of ten or of a common FX rate is labelled, e.g.
    3.60 -> 'COP/USD ~4000'. Steps below `min_step` (a factor of 1.26) are significant at this sample
    size but immaterial, and are not reported. Change points come from `binseg`.
    """
    x = log10_median.dropna()
    if len(x) < 30:
        return pd.DataFrame(columns=["date", "step_log10", "factor", "label"])
    cps = binseg(x.to_numpy())
    known = {
        "x10": 1,
        "x100": 2,
        "x1000": 3,
        "COP/USD ~4000": math.log10(4000),
        "ARS/USD ~350": math.log10(350),
        "MXN/USD ~17": math.log10(17),
    }
    rows = []
    bounds = [0, *cps, len(x)]
    for a, b, c in zip(bounds, bounds[1:], bounds[2:]):
        step = float(x.iloc[b:c].median() - x.iloc[a:b].median())
        if abs(step) < min_step:  # significant but immaterial (< x1.26): not a unit change
            continue
        label = next((n for n, v in known.items() if abs(abs(step) - v) <= tol), "")
        rows.append(
            {
                "date": x.index[b],
                "step_log10": round(step, 3),
                "factor": round(10**step, 4),
                "label": label,
            }
        )
    return pd.DataFrame(rows, columns=["date", "step_log10", "factor", "label"])


# ------------------------------------------------------------------------------ table findings
FINDING_COLUMNS = [
    "level",
    "column",
    "signal",
    "kind",
    "first_seen",
    "last_seen",
    "coverage",
    "detail",
]
# Value classes that are not evidence of a format (absence of a value).
_NON_FORMAT = {"empty", "null_token"}


def _presence(df: pd.DataFrame, by: str, flag: pd.Series) -> pd.Series:
    """Daily presence of a per-file flag (any file of the day)."""
    return flag.groupby(df[by]).any().sort_index()


def _share_transition(add, col, signal, share, index, alpha, min_delta) -> None:
    """One finding per (column, signal): material change points of a daily share, as one transition.

    A gradual ramp yields several nested change points; reporting them together (level of the first
    segment -> level of the last, over the dates of the first and last change point) is what a reviewer
    needs. Splits whose prefix/suffix means differ by less than `min_delta` are immaterial.
    """
    bounds = binseg(share, alpha=alpha)
    cps = [cp for cp in bounds if abs(share[cp:].mean() - share[:cp].mean()) >= min_delta]
    if not cps:
        return
    first_seg, last_seg = share[: bounds[0]].mean(), share[bounds[-1] :].mean()
    add(
        "L2",
        col,
        signal,
        {
            "kind": "share_shift",
            "first_seen": index[min(cps)],
            "last_seen": index[max(cps)],
            "coverage": 1.0,
        },
        f"{first_seg:.4f} -> {last_seg:.4f} ({len(cps)} change point(s))",
    )


def detect_table(
    files: pd.DataFrame,
    lexical: pd.DataFrame,
    vocabulary: pd.DataFrame | None = None,
    k: int = 7,
    share_alpha: float = 0.01,
    max_values: int = 50,
    min_share_delta: float = 0.05,
) -> pd.DataFrame:
    """Classified findings for one table from its cached fingerprints (see scripts/raw_schema_scan.py).

    Only signals that are not 'stable' are reported, except value classes that coexist in a column
    (several formats every day), which are reported as 'coexisting'. Dimension tables (one file, no
    partition date) get point findings with kind 'snapshot'.
    """
    from latam_eda.raw_forensics import CLASS_NAMES

    rows: list[dict] = []
    dated = files["partition_date"].notna().any()

    def add(level, column, signal, res, detail=""):
        rows.append({"level": level, "column": column, "signal": signal, "detail": detail, **res})

    # L0 / L1: file-level properties
    l0 = {
        "bom": files["bom"],
        "crlf_line_endings": (files["crlf"] > 0) & (files["lf"] == 0),
        "utf8_errors": files["utf8_errors"] > 0,
        "nul_bytes": files["nul_bytes"] > 0,
        "ragged_rows": files["ragged"] > 0,
        "grammar_error": files["grammar_error"].notna(),
    }
    headers = files["header"].astype(str)
    for h in headers.unique():
        l0[f"header={h[:60]}"] = headers == h
    for signal, flag in l0.items():
        level = "L1" if signal.startswith("header=") else "L0"
        if not dated:
            if flag.any() and signal in (
                "utf8_errors",
                "nul_bytes",
                "ragged_rows",
                "grammar_error",
            ):
                add(
                    level,
                    None,
                    signal,
                    {"kind": "snapshot", "first_seen": None, "last_seen": None, "coverage": 1.0},
                )
            continue
        res = classify_presence(_presence(files, "partition_date", flag), k)
        healthy_always = signal in ("bom", "crlf_line_endings") or signal.startswith("header=")
        if res["kind"] == "stable" and healthy_always:
            continue
        if res["kind"] not in ("absent", "intermittent"):
            add(level, None, signal, res)

    # L2: value classes per column
    for col, g in lexical.groupby("column"):
        if not dated:
            present = [c for c in CLASS_NAMES if c not in _NON_FORMAT and g[f"n_{c}"].sum() > 0]
            if len(present) > 1:
                add(
                    "L2",
                    col,
                    "+".join(present),
                    {"kind": "snapshot", "first_seen": None, "last_seen": None, "coverage": 1.0},
                    "several formats",
                )
            continue
        daily = (
            g.groupby("partition_date")[[f"n_{c}" for c in CLASS_NAMES] + ["n"]].sum().sort_index()
        )
        stable_formats = []
        for c in CLASS_NAMES:
            if c in _NON_FORMAT:
                continue
            res = classify_presence(daily[f"n_{c}"] > 0, k)
            if res["kind"] in ("absent", "intermittent"):
                continue
            if res["kind"] == "stable":
                stable_formats.append(c)
                # sustained shift of the class share (PELT with a permutation-calibrated penalty)
                share = (daily[f"n_{c}"] / daily["n"].where(daily["n"] > 0)).fillna(0).to_numpy()
                if 0 < share.mean() < 1 and share.std() > 0:
                    _share_transition(
                        add, col, f"share:{c}", share, daily.index, share_alpha, min_share_delta
                    )
                continue
            add("L2", col, f"class:{c}", res)
        if len(stable_formats) > 1:
            add(
                "L2",
                col,
                "+".join(stable_formats),
                {
                    "kind": "coexisting",
                    "first_seen": daily.index[0],
                    "last_seen": daily.index[-1],
                    "coverage": 1.0,
                },
                "several formats every day",
            )
        # null-rate shift (empty strings)
        if daily["n_empty"].sum():
            share = (daily["n_empty"] / daily["n"].where(daily["n"] > 0)).fillna(0).to_numpy()
            if share.std() > 0:
                _share_transition(
                    add, col, "share:empty", share, daily.index, share_alpha, min_share_delta
                )
        # scale steps of numeric columns
        loc = g.groupby("partition_date")["log10_median"].median().dropna()
        if len(loc) >= 30 and loc.std() > 0:
            steps = scale_steps(loc)
            for kind, part in (
                ("unit_change", steps[steps["label"] != ""]),
                ("level_shift", steps[steps["label"] == ""]),
            ):
                # a factor near 10^k or an FX rate is a unit change; any other step is drift (phase F)
                if len(part):
                    add(
                        "L3",
                        col,
                        "scale",
                        {
                            "kind": kind,
                            "first_seen": part["date"].min(),
                            "last_seen": part["date"].max(),
                            "coverage": 1.0,
                        },
                        f"{len(part)} step(s), factors "
                        + ", ".join(f"x{f:g}" for f in part["factor"].head(5))
                        + (
                            " " + ", ".join(sorted(set(part["label"]) - {""}))
                            if kind == "unit_change"
                            else ""
                        ),
                    )

    # L3: vocabularies
    if vocabulary is not None and len(vocabulary):
        from latam_eda.raw_forensics import variant_groups

        for col, g in vocabulary.groupby("column"):
            values = g["value"].dropna().astype(str).unique().tolist()
            for key, spellings in variant_groups(values).items():
                add(
                    "L3",
                    col,
                    f"variants:{key}",
                    {"kind": "variant", "first_seen": None, "last_seen": None, "coverage": 1.0},
                    " | ".join(spellings),
                )
            if not dated:
                continue
            days = pd.Index(sorted(g["partition_date"].dropna().unique()))
            unstable = []
            for value, gv in g.groupby("value", dropna=False):
                on = pd.Series(days.isin(gv["partition_date"]), index=days)
                res = classify_presence(on, k)
                if res["kind"] not in ("stable", "absent", "intermittent"):
                    unstable.append((value, res))
            if len(unstable) > max_values:
                # e.g. numbers pouring into a code column after a column swap: one finding, not thousands
                # dated by the earliest change: a value that died changed the day after it was last seen
                first = min(
                    pd.Timestamp(r["last_seen"]) + pd.Timedelta(days=1)
                    if r["kind"] == "died"
                    else pd.Timestamp(r["first_seen"])
                    for _, r in unstable
                )
                add(
                    "L3",
                    col,
                    "vocabulary_burst",
                    {"kind": "burst", "first_seen": first, "last_seen": None, "coverage": 1.0},
                    f"{len(unstable):,} values appear or vanish, e.g. "
                    + ", ".join(str(v) for v, _ in unstable[:5]),
                )
            else:
                for value, res in unstable:
                    add("L3", col, f"value={value}", res)

    out = pd.DataFrame(rows, columns=[c for c in FINDING_COLUMNS if c != "change_date"])
    # when the change happened: a value that died changed on the day after it was last seen
    first, last = pd.to_datetime(out["first_seen"]), pd.to_datetime(out["last_seen"])
    out.insert(4, "change_date", first.where(out["kind"] != "died", last + pd.Timedelta(days=1)))
    return out
