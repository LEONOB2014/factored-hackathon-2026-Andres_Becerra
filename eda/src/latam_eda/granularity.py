"""The granularity experiment: an aggregate star built on top of gold, and the statistics used to judge each grain.

The aggregate models live in `granularity_sql/*.sql`, one model per file, written like dbt models: a model refers to
another relation by `{name}`. A name is resolved, in order, to an aggregate model of this folder (schema `agg` of the
scratch lakehouse), then to a node of the compiled dbt project (silver, gold, ...), so the files can be promoted to
`platform/dbt/models/gold/aggregates/` by replacing `{name}` with `{{ ref('name') }}`.

Each model declares its contract in a header comment:

    -- grain: customer_id, month_start
    -- reconcile: n_tx = count(*) from {fct_transaction} | month_start = date_trunc('month', transaction_ts_utc)
    -- dense: customer_id from {int_customer_profile} x month_start from {dim_month}

* `grain` is checked unique (`grain_unique`);
* `reconcile` lines state that an additive measure, summed per the given key, equals the same aggregate computed on
  the atomic fact (`reconciles`); the part after `|` maps the atomic fact's columns to the key;
* `dense` states the full cross product the fact must cover (`dense_complete`).
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np
import pandas as pd
from scipy import stats

if TYPE_CHECKING:
    from latam_eda import pipeline as pipe

SQL_DIR = Path(__file__).with_name("granularity_sql")
SQL_DIR_TIME = Path(__file__).with_name(
    "granularity_time_sql"
)  # the hour and campaign-cell aggregates (series II)
SCHEMA = "agg"
REF = re.compile(r"\{(\w+)\}")


@dataclass
class Model:
    name: str
    sql: str
    grain: list[str] = field(default_factory=list)
    reconcile: list[tuple[str, str, str]] = field(
        default_factory=list
    )  # (measure, atomic expr, key mapping)
    dense: str | None = None
    doc: str = ""

    @property
    def refs(self) -> set[str]:
        body = "\n".join(
            line for line in self.sql.splitlines() if not line.lstrip().startswith("--")
        )
        return set(REF.findall(body))


def parse(path: Path) -> Model:
    text = path.read_text()
    m = Model(path.stem, text)
    doc = []
    for line in text.splitlines():
        s = line.strip()
        if not s.startswith("--"):
            continue
        s = s[2:].strip()
        if s.startswith("grain:"):
            m.grain = [c.strip() for c in s.removeprefix("grain:").split(",") if c.strip()]
        elif s.startswith("reconcile:"):
            rule, _, keymap = s.removeprefix("reconcile:").partition("|")
            measure, _, atomic = rule.partition("=")
            m.reconcile.append((measure.strip(), atomic.strip(), keymap.strip()))
        elif s.startswith("dense:"):
            m.dense = s.removeprefix("dense:").strip()
        else:
            doc.append(s)
    m.doc = " ".join(doc).strip()
    return m


def load(sql_dir: Path = SQL_DIR) -> dict[str, Model]:
    return {p.stem: parse(p) for p in sorted(sql_dir.glob("*.sql"))}


def order(models: dict[str, Model]) -> list[str]:
    """Topological order of the aggregate models (refs to non-aggregate names are external inputs)."""
    seen: list[str] = []

    def visit(n: str, stack: tuple[str, ...] = ()) -> None:
        if n in seen:
            return
        if n in stack:
            raise ValueError(f"cycle: {' -> '.join((*stack, n))}")
        for d in sorted(models[n].refs & models.keys()):
            visit(d, (*stack, n))
        seen.append(n)

    for n in sorted(models):
        visit(n)
    return seen


def country_calendar(start: str = "2023-06-01", end: str = "2026-06-30") -> pd.DataFrame:
    """The seed behind `dim_country_day`: `country.calendar` for every bank market, stacked."""
    from latam_eda import country

    return pd.concat(
        [country.calendar(c, start, end).assign(country_code=c) for c in country.COUNTRIES],
        ignore_index=True,
    )


def open_star(pl: pipe.Pipeline, sql_dir: Path = SQL_DIR) -> Star:
    """A Star over a scratch lakehouse with its seeds registered (what every notebook of the series starts with)."""
    from latam_eda import country

    s = Star(pl, sql_dir)
    s.seed("seed_country_calendar", country_calendar())
    # the clock every day-grain fact places events on (see country.BUSINESS_UTC_OFFSET)
    s.seed("seed_clock", pd.DataFrame({"utc_offset_hours": [country.BUSINESS_UTC_OFFSET]}))
    return s


class Star:
    """Builds and checks the aggregate star inside a scratch lakehouse opened by `latam_eda.country.session`."""

    def __init__(self, pl: pipe.Pipeline, sql_dir: Path = SQL_DIR):
        self.pl = pl
        self.models = load(sql_dir)
        self.seeds: set[str] = set()
        pl.con.sql(f"CREATE SCHEMA IF NOT EXISTS {SCHEMA}")

    def seed(self, name: str, df: pd.DataFrame) -> None:
        """A table computed in Python (like a dbt seed) that models can reference as `{name}`."""
        self.pl.con.register("_seed_df", df)
        self.pl.con.sql(f"CREATE OR REPLACE TABLE {SCHEMA}.{name} AS SELECT * FROM _seed_df")
        self.pl.con.unregister("_seed_df")
        self.seeds.add(name)

    def relation(self, name: str) -> str:
        if name in self.models or name in self.seeds:
            return f"{SCHEMA}.{name}"
        return self.pl.relation(self.pl.key(name))

    def render(self, sql: str) -> str:
        return REF.sub(lambda m: self.relation(m.group(1)), sql)

    def q(self, sql: str) -> pd.DataFrame:
        return self.pl.con.sql(self.render(sql)).df()

    def build(self, names: list[str] | None = None, verbose: bool = True) -> pd.DataFrame:
        """Build the given models (default: all) and what they depend on, in dependency order."""
        wanted = set(names or self.models)
        todo = [n for n in order(self.models) if n in wanted or self._needed_by(n, wanted)]
        rows = []
        for n in todo:
            m = self.models[n]
            for ext in sorted(m.refs - self.models.keys() - self.seeds):
                self.pl.ensure(self.pl.key(ext))
            t = time.time()
            body = "\n".join(
                line for line in m.sql.splitlines() if not line.lstrip().startswith("--")
            )
            self.pl.con.sql(f"CREATE OR REPLACE TABLE {SCHEMA}.{n} AS {self.render(body)}")
            n_rows = self.pl.con.sql(f"SELECT count(*) FROM {SCHEMA}.{n}").fetchone()[0]
            rows.append({"model": n, "rows": n_rows, "seconds": round(time.time() - t, 1)})
            if verbose:
                print(f"{n:<32} {n_rows:>12,} rows {rows[-1]['seconds']:>7.1f}s")
        return pd.DataFrame(rows)

    def _needed_by(self, n: str, wanted: set[str]) -> bool:
        return any(n in self._closure(w) for w in wanted)

    def _closure(self, n: str) -> set[str]:
        out, stack = set(), [n]
        while stack:
            for d in self.models[stack.pop()].refs & self.models.keys():
                if d not in out:
                    out.add(d)
                    stack.append(d)
        return out

    # ------------------------------------------------------------------------------------------------ checks
    def grain_unique(self, name: str) -> dict:
        m = self.models[name]
        keys = ", ".join(m.grain)
        n, d = self.pl.con.sql(
            f"SELECT count(*), count(DISTINCT ({keys})) FROM {SCHEMA}.{name}"
        ).fetchone()
        return {
            "model": name,
            "check": "grain_unique",
            "detail": keys,
            "expected": n,
            "observed": d,
            "ok": n == d,
        }

    def reconciles(self, name: str) -> list[dict]:
        out = []
        m = self.models[name]
        for measure, atomic, keymap in m.reconcile:
            # atomic: "count(*) from {fact}" or "sum(col) from {fact}"; keymap: "k = expr, k2 = expr2" or empty (total)
            agg, _, src = atomic.partition(" from ")
            pairs = [p.split("=", 1) for p in _split_top(keymap) if "=" in p]
            keys = [k.strip() for k, _ in pairs]
            exprs = [e.strip() for _, e in pairs]
            if keys:
                left = f"SELECT {', '.join(keys)}, sum({measure}) AS v FROM {SCHEMA}.{name} GROUP BY ALL"
                right = (
                    f"SELECT {', '.join(f'{e} AS {k}' for k, e in zip(keys, exprs, strict=True))}, {agg} AS v "
                    f"FROM {self.render(src.strip())} GROUP BY ALL"
                )
                on = " AND ".join(f"l.{k} IS NOT DISTINCT FROM r.{k}" for k in keys)
                bad, total, diff = self.pl.con.sql(f"""
                    WITH l AS ({left}), r AS ({right})
                    SELECT count(*) FILTER (WHERE coalesce(l.v, 0) <> coalesce(r.v, 0)
                                              AND abs(coalesce(l.v, 0) - coalesce(r.v, 0)) > 1e-6 * greatest(1, abs(coalesce(r.v, 0)))),
                           count(*), sum(abs(coalesce(l.v, 0) - coalesce(r.v, 0)))
                    FROM l FULL OUTER JOIN r ON {on}""").fetchone()
            else:
                lv = float(
                    self.pl.con.sql(f"SELECT sum({measure}) FROM {SCHEMA}.{name}").fetchone()[0]
                    or 0
                )
                rv = float(
                    self.pl.con.sql(f"SELECT {agg} FROM {self.render(src.strip())}").fetchone()[0]
                    or 0
                )
                bad, total, diff = int(abs(lv - rv) > 1e-6 * max(1, abs(rv))), 1, abs(lv - rv)
            out.append(
                {
                    "model": name,
                    "check": "reconciles",
                    "detail": f"{measure} = {agg} per {', '.join(keys) or 'total'}",
                    "expected": total,
                    "observed": total - bad,
                    "ok": bad == 0,
                    "abs_difference": float(diff or 0),
                }
            )
        return out

    def dense_complete(self, name: str) -> dict | None:
        m = self.models[name]
        if not m.dense:
            return None
        parts = [p.strip() for p in m.dense.split(" x ")]
        sels = []
        for p in parts:
            col, _, src = p.partition(" from ")
            sels.append(f"(SELECT DISTINCT {col.strip()} FROM {self.render(src.strip())})")
        cols = [p.partition(" from ")[0].strip() for p in parts]
        expected = self.pl.con.sql(f"SELECT count(*) FROM {' CROSS JOIN '.join(sels)}").fetchone()[
            0
        ]
        on = " AND ".join(f"f.{c} = g.{c}" for c in cols)
        missing = self.pl.con.sql(f"""
            SELECT count(*) FROM (SELECT * FROM {" CROSS JOIN ".join(sels)}) g
            WHERE NOT EXISTS (SELECT 1 FROM {SCHEMA}.{name} f WHERE {on})""").fetchone()[0]
        return {
            "model": name,
            "check": "dense_complete",
            "detail": " x ".join(cols),
            "expected": expected,
            "observed": expected - missing,
            "ok": missing == 0,
        }

    def check(self, names: list[str] | None = None) -> pd.DataFrame:
        rows = []
        for n in names or order(self.models):
            if self.models[n].grain:
                rows.append(self.grain_unique(n))
            rows.extend(self.reconciles(n))
            d = self.dense_complete(n)
            if d:
                rows.append(d)
        return pd.DataFrame(rows)


def _split_top(text: str, sep: str = ",") -> list[str]:
    """Split on `sep` outside parentheses and quotes (a key mapping may hold function calls)."""
    out, depth, quote, cur = [], 0, None, []
    for ch in text:
        if quote:
            quote = None if ch == quote else quote
        elif ch in "'\"":
            quote = ch
        elif ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        elif ch == sep and depth == 0:
            out.append("".join(cur))
            cur = []
            continue
        cur.append(ch)
    if "".join(cur).strip():
        out.append("".join(cur))
    return out


# ---------------------------------------------------------------------------------------------- statistics
def transition_matrix(states: pd.DataFrame, entity: str, period: str, state: str) -> pd.DataFrame:
    """Row-stochastic first-order transition matrix P[i, j] = P(state_t+1 = j | state_t = i), pooled over entities.

    Consecutive periods only: a gap in an entity's history is not counted as a transition.
    """
    s = states.sort_values([entity, period], kind="mergesort")
    nxt = s.groupby(entity)[state].shift(-1)
    step = s.groupby(entity)[period].shift(-1)
    consecutive = step.notna() & (
        (pd.to_datetime(step).dt.to_period("M") - pd.to_datetime(s[period]).dt.to_period("M")).map(
            lambda d: getattr(d, "n", None) == 1
        )
    )
    counts = pd.crosstab(s.loc[consecutive, state], nxt[consecutive])
    return counts.div(counts.sum(axis=1), axis=0)


def stationary(p: pd.DataFrame) -> pd.Series:
    """Stationary distribution π of a transition matrix (π P = π, Σπ = 1): left eigenvector of eigenvalue 1."""
    vals, vecs = np.linalg.eig(p.to_numpy().T)
    v = np.real(vecs[:, np.argmin(np.abs(vals - 1))])
    return pd.Series(v / v.sum(), index=p.index)


def expected_sojourn(p: pd.DataFrame) -> pd.Series:
    """Expected consecutive periods spent in a state once entered: 1 / (1 - P[i, i]) (geometric holding time)."""
    d = pd.Series(np.diag(p.to_numpy()), index=p.index)
    return 1 / (1 - d.clip(upper=1 - 1e-12))


def erlang_c(arrivals_per_hour: float, aht_seconds: float, agents: int) -> float:
    """Erlang C: probability that a contact waits (M/M/c queue), for offered load A = λ·AHT."""
    a = arrivals_per_hour * aht_seconds / 3600
    if agents <= a:
        return 1.0
    terms = _poisson_sum(a, agents)
    top = a**agents / _factorial(agents) * agents / (agents - a)
    return float(top / (terms + top))


def _factorial(n: int) -> float:
    from math import factorial

    return float(factorial(n))


def _poisson_sum(a: float, c: int) -> float:
    return float(sum(a**k / _factorial(k) for k in range(c)))


def service_level(
    arrivals_per_hour: float, aht_seconds: float, agents: int, target_seconds: float
) -> float:
    """Share of contacts answered within `target_seconds` under Erlang C."""
    a = arrivals_per_hour * aht_seconds / 3600
    if agents <= a:
        return 0.0
    pw = erlang_c(arrivals_per_hour, aht_seconds, agents)
    return float(1 - pw * np.exp(-(agents - a) * target_seconds / aht_seconds))


def agents_needed(
    arrivals_per_hour: float, aht_seconds: float, target_seconds: float = 20, service: float = 0.8
) -> int:
    """Smallest number of agents meeting the service level (e.g. 80 % of contacts within 20 s)."""
    c = max(1, int(np.ceil(arrivals_per_hour * aht_seconds / 3600)))
    while service_level(arrivals_per_hour, aht_seconds, c, target_seconds) < service:
        c += 1
    return c


def newsvendor_quantile(underage_cost: float, overage_cost: float) -> float:
    """Critical ratio of the newsvendor problem: stock the q-quantile of demand, q = Cu / (Cu + Co)."""
    return underage_cost / (underage_cost + overage_cost)


def bh_fdr(p: np.ndarray | pd.Series, alpha: float = 0.05) -> tuple[np.ndarray, np.ndarray]:
    """Benjamini–Hochberg: (rejected, adjusted p-values), controlling the false discovery rate at `alpha`."""
    p = np.asarray(p, dtype=float)
    n = len(p)
    o = np.argsort(p, kind="mergesort")
    ranked = p[o] * n / np.arange(1, n + 1)
    adj = np.minimum.accumulate(ranked[::-1])[::-1].clip(max=1)
    out = np.empty(n)
    out[o] = adj
    return out <= alpha, out


def mase(actual: np.ndarray, forecast: np.ndarray, insample: np.ndarray, season: int = 7) -> float:
    """Mean absolute scaled error: MAE of the forecast over the in-sample MAE of the seasonal-naive forecast."""
    scale = np.mean(np.abs(insample[season:] - insample[:-season]))
    return float(np.mean(np.abs(actual - forecast)) / scale)


def diebold_mariano(e1: np.ndarray, e2: np.ndarray, horizon: int = 1) -> tuple[float, float]:
    """Diebold–Mariano test of equal accuracy under absolute loss, with the Harvey small-sample correction.

    Returns (statistic, two-sided p-value); a negative statistic means model 1 is more accurate.
    """
    d = np.abs(e1) - np.abs(e2)
    n = len(d)
    mean = d.mean()
    gamma = [np.sum((d[k:] - mean) * (d[: n - k] - mean)) / n for k in range(horizon)]
    var = (gamma[0] + 2 * sum(gamma[1:])) / n
    if var <= 0:
        return float("nan"), float("nan")
    dm = mean / np.sqrt(var)
    k = np.sqrt((n + 1 - 2 * horizon + horizon * (horizon - 1) / n) / n)
    stat = dm * k
    return float(stat), float(2 * stats.t.sf(abs(stat), df=n - 1))


def hhi(shares: pd.Series) -> float:
    """Herfindahl–Hirschman index of concentration on shares that sum to 1 (0..10,000 scale)."""
    s = shares / shares.sum()
    return float((100 * s).pow(2).sum())


TARGET_COLUMNS = [
    "grain",
    "target",
    "kind",
    "train_rows",
    "test_rows",
    "test_positives",
    "base_rate",
    "metric",
    "value",
    "ci_low",
    "ci_high",
    "baseline",
    "p_value",
    "best_single_feature",
    "best_single_value",
    "verdict",
    "note",
]


def classification_row(grain: str, r: dict) -> dict:
    """One row of the series' common target table from `country.evaluate_target` output.

    The p-value is one-sided for AUC > 0.5 from the Hanley–McNeil standard error (the interval's half-width / 1.96);
    notebook 09 pools these p-values across every target of every grain and controls the false discovery rate.
    """
    auc = r.get("auc", np.nan)
    se = (r.get("auc_hi", np.nan) - r.get("auc_lo", np.nan)) / (2 * 1.96)
    p = float(stats.norm.sf((auc - 0.5) / se)) if np.isfinite(auc) and se > 0 else np.nan
    from latam_eda import country

    return {
        "grain": grain,
        "target": r["target"] if "name" not in r else r["name"],
        "kind": "classification",
        "train_rows": r.get("train_rows"),
        "test_rows": r.get("test_rows"),
        "test_positives": r.get("test_positives"),
        "base_rate": r.get("base_rate"),
        "metric": "AUC",
        "value": auc,
        "ci_low": r.get("auc_lo"),
        "ci_high": r.get("auc_hi"),
        "baseline": 0.5,
        "p_value": p,
        "best_single_feature": r.get("best_single_feature"),
        "best_single_value": r.get("best_single_auc"),
        "verdict": country.verdict(r),
        "note": r.get("note", ""),
    }


def forecast_row(
    grain: str,
    target: str,
    model: str,
    mase_model: float,
    mase_naive: float,
    dm_p: float,
    note: str = "",
) -> dict:
    """One row of the common target table for a forecast: skill is MASE against the seasonal-naive forecast, and the
    p-value is the Diebold–Mariano test of equal accuracy against it (one-sided: the model is better)."""
    better = mase_model < mase_naive
    if not np.isfinite(dm_p):
        verdict = "not evaluable"
    elif better and dm_p < 0.05 and mase_model < 0.9 * mase_naive:
        verdict = "forecastable: beats seasonal naive"
    elif better and dm_p < 0.05:
        verdict = "marginal gain over seasonal naive"
    else:
        verdict = "no gain over seasonal naive"
    return {
        "grain": grain,
        "target": target,
        "kind": "forecast",
        "metric": "MASE",
        "value": mase_model,
        "baseline": mase_naive,
        "p_value": dm_p / 2 if better else 1 - dm_p / 2,
        "best_single_feature": model,
        "verdict": verdict,
        "note": note,
    }


# ---------------------------------------------------------------------------------------------- clock and cells
def clock_scan(
    ts: pd.Series, counts: pd.Series | None = None, shifts: range = range(-12, 13)
) -> pd.DataFrame:
    """For each shift k (hours added to the raw timestamps), the chi-square of independence between weekday and hour.

    A generator (or a source system) that applies a weekly rhythm to whole days of some clock leaves hour of day
    independent of weekday only in that clock: on any other, the weekend boundary cuts through the hours. The shift that
    minimises the statistic is the clock the days were drawn in; at that shift the statistic is close to its degrees of
    freedom (independence), elsewhere it grows with the distance in hours.

    `ts` holds event timestamps, or hour-floored timestamps with their event `counts` (much faster on large tables).
    """
    t = pd.to_datetime(ts)
    w = (
        pd.Series(1, index=t.index)
        if counts is None
        else pd.Series(np.asarray(counts), index=t.index)
    )
    ok = t.notna()
    t, w = t[ok], w[ok]
    rows = []
    for k in shifts:
        s = t + pd.Timedelta(hours=k)
        tab = pd.crosstab(s.dt.weekday, s.dt.hour, values=w, aggfunc="sum").fillna(0).to_numpy()
        chi2, p, dof, _ = stats.chi2_contingency(tab)
        rows.append(
            {
                "shift_hours": k,
                "chi2": float(chi2),
                "dof": int(dof),
                "chi2_over_dof": float(chi2 / dof),
            }
        )
    return pd.DataFrame(rows)


def beta_binomial_fit(successes: np.ndarray, trials: np.ndarray) -> tuple[float, float]:
    """Maximum-likelihood (alpha, beta) of a beta-binomial: the prior of cell rates that empirical Bayes shrinks to.

    Each cell's posterior mean is (s + alpha) / (n + alpha + beta): a cell with few trials is pulled towards the common
    mean alpha / (alpha + beta), a cell with many keeps its own rate.
    """
    from scipy.optimize import minimize
    from scipy.special import betaln

    s, n = np.asarray(successes, dtype=float), np.asarray(trials, dtype=float)
    m = s.sum() / n.sum()

    def nll(log_ab):
        a, b = np.exp(log_ab)
        return -np.sum(betaln(s + a, n - s + b) - betaln(a, b))

    res = minimize(
        nll,
        x0=np.log([m * 10, (1 - m) * 10]),
        method="Nelder-Mead",
        options={"xatol": 1e-8, "fatol": 1e-10, "maxiter": 4000},
    )
    a, b = np.exp(res.x)
    return float(a), float(b)


def policy_value(cells: pd.DataFrame, weights: pd.Series, total_sends: float) -> dict:
    """Value of sending `total_sends` split across cells in proportion to `weights`, using each cell's **realised**
    held-out conversion rate, value per conversion and cost per send (columns rate_ho, value_per_conv_ho, cost_per_send_ho).

    The evaluation never uses a cell's held-out outcome to choose the weights (the caller fits them on earlier months);
    it is a replay on observed cells, not a causal estimate (no randomised holdout).
    """
    w = weights.reindex(cells.index).fillna(0).clip(lower=0)
    sends = total_sends * w / w.sum() if w.sum() > 0 else w
    conv = sends * cells.rate_ho
    value = conv * cells.value_per_conv_ho
    cost = sends * cells.cost_per_send_ho
    return {
        "sends": float(sends.sum()),
        "conversions": float(conv.sum()),
        "value": float(value.sum()),
        "cost": float(cost.sum()),
        "net": float(value.sum() - cost.sum()),
        "roi": float((value.sum() - cost.sum()) / cost.sum()) if cost.sum() else float("nan"),
    }
