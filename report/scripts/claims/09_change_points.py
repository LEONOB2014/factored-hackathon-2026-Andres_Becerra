"""Chapter 9 · Change points and monitoring.

Report-only re-analysis of the country notebooks' abnormal-day and level-shift results (country_template/13, stored
per scope), the control charts of granularity/04 and the intraday limits of granularity_time/02:

* daily transaction counts per customer country on the transactions' delivery clock, adjusted for weekday, month
  end and trend; abnormal days by a robust z rule;
* level shifts on weekly means by the notebook's kernel PELT, by PELT with a Gaussian mean cost and a BIC penalty,
  and by permutation binary segmentation; their false-alarm rate on permuted series and their power against planted
  steps of known size;
* EWMA charts on the residuals and p-charts of the daily decline rate, with the decline rate's dispersion;
* hourly limits from a Poisson and from a negative binomial carrying the day-level dispersion.

    uv run python scripts/claims/09_change_points.py
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import ruptures as rpt
import statsmodels.formula.api as smf
from scipy import stats

from report_lib import db
from report_lib.build import Chapter
from report_lib.eda import change_detection as cd
from report_lib.estimators import intervals
from report_lib.paths import BUILD, REPO, TABLES
from report_lib.texgen import render_table

MAIN = REPO / "data" / "parquet"
NB13 = REPO / "eda" / "notebooks" / "country_template" / "13_anomalies_and_change_points.py"
NB04 = REPO / "eda" / "notebooks" / "granularity" / "04_market_and_channel_day.py"
NB02 = REPO / "eda" / "notebooks" / "granularity_time" / "02_the_hour_grain.py"
THIS = REPO / "report" / "scripts" / "claims" / "09_change_points.py"
OUT = BUILD / "sources"
CLOCK = {
    "transactions": 6,
    "call_center_interactions": 8,
}  # delivery-day offsets in hours (Chapter 4)
Z_DAY = 4.0  # the country notebooks' abnormal-day rule
LAMBDA, L = 0.2, 3.0  # granularity/04's EWMA chart
DELTAS = (0.02, 0.03, 0.04, 0.05, 0.06, 0.08, 0.1, 0.15, 0.2, 0.3)
SIMS = 150
TOL = 4  # weeks between a planted step and a detected change point for it to count as found
CODE = {"México": "mx", "Colombia": "co", "Argentina": "ar"}


def daily(con, table: str) -> pd.DataFrame:
    ts = "transaction_date" if table == "transactions" else "interaction_date"
    extra = (
        ", count(*) filter (where t.transaction_status = 'Declined') as declined"
        if table == "transactions"
        else ""
    )
    d = con.sql(f"""select c.country, cast(t.{ts} - interval {CLOCK[table]} hour as date) as day, count(*) as n {extra}
                    from m_{table} t join m_customers c using (customer_id) group by all order by 1, 2""").df()  # fmt: skip
    d["day"] = pd.to_datetime(d.day)
    # the first and last delivery days are partial
    first, last = (
        d.groupby("country").day.transform("min"),
        d.groupby("country").day.transform("max"),
    )
    return d[(d.day > first) & (d.day < last)].reset_index(drop=True)


def residuals(g: pd.DataFrame) -> np.ndarray:
    g = g.assign(
        wd=g.day.dt.dayofweek,
        t=(g.day - g.day.min()).dt.days / 365.25,
        me=g.day.dt.is_month_end.astype(int),
    )
    return smf.ols("np.log(n) ~ C(wd) + me + t", data=g).fit().resid.to_numpy()


def detectors(n: int, s2: float):
    return {
        "kernel PELT (notebook)": lambda x: rpt.Pelt(model="rbf", min_size=6).fit(x.reshape(-1, 1)).predict(pen=3 * np.log(n))[:-1],
        "Gaussian PELT, BIC penalty": lambda x: rpt.Pelt(model="l2", min_size=6).fit(x.reshape(-1, 1)).predict(pen=2 * s2 * np.log(n))[:-1],
        "binary segmentation, permutation": lambda x: cd.binseg(x, alpha=0.01, min_size=6),
    }  # fmt: skip


def shifts(ch: Chapter, weekly: dict[str, np.ndarray]) -> None:
    rng = np.random.default_rng(2026)
    rows, power = [], []
    for ctry, wk in weekly.items():
        n, s2 = len(wk), float(np.var(wk, ddof=1))
        for name, det in detectors(n, s2).items():
            found = len(det(wk))
            false = sum(len(det(rng.permutation(wk))) > 0 for _ in range(SIMS))
            rows.append({"country": ctry, "detector": name, "change points": found, "false": false})
            for delta in DELTAS:
                hit = 0
                for _ in range(SIMS):
                    k = int(rng.integers(10, n - 10))
                    x = wk.copy()
                    x[k:] += delta
                    hit += any(abs(c - k) <= TOL for c in det(x))
                power.append({"country": ctry, "detector": name, "shift": delta, "found": hit})
    t, pw = pd.DataFrame(rows), pd.DataFrame(power)
    src = MAIN / "transactions.parquet"
    tags = {
        "kernel PELT (notebook)": "rbf",
        "Gaussian PELT, BIC penalty": "l2",
        "binary segmentation, permutation": "bs",
    }
    summary = []
    for name, g in pw.groupby("detector", sort=False):
        curve = g.groupby("shift").found.sum() / (SIMS * g.country.nunique())
        mde = next((d for d, p in curve.items() if p >= 0.8), np.nan)
        fa = t[t.detector == name]
        k_false, n_false = int(fa.false.sum()), SIMS * len(fa)
        tag = tags[name]
        ch.proportion(
            f"false-{tag}", k_false, n_false, intervals.wilson(k_false, n_false), THIS, digits=2
        )
        ch.count(f"found-{tag}", int(fa["change points"].sum()), src)
        if not np.isnan(mde):
            ch.census(f"mde-{tag}", 100 * mde, src, unit="percent")
        for d in (0.05, 0.1, 0.3):
            k = int(g[g["shift"] == d].found.sum())
            ch.proportion(f"power-{tag}-{int(round(100 * d))}", k, SIMS * g.country.nunique(),
                          intervals.wilson(k, SIMS * g.country.nunique()), THIS, digits=2)  # fmt: skip
        summary.append({"detector": name, "change points found": int(fa["change points"].sum()),
                        "false-alarm rate": k_false / n_false, "smallest step found 80 % of the time": mde,
                        "power at a step of 0.05": float(curve[0.05]), "power at 0.10": float(curve[0.1]),
                        "power at 0.30": float(curve[0.3])})  # fmt: skip
    pd.DataFrame(summary).to_csv(OUT / "ch09_shift_detectors.csv", index=False)
    (pw.groupby(["detector", "shift"], sort=False).found.sum() / (SIMS * len(weekly))).rename("power").reset_index().to_csv(
        OUT / "ch09_power.csv", index=False)  # fmt: skip
    ch.constant("sims", SIMS, THIS)
    ch.constant("power-target", 80, THIS, unit="percent")
    ch.constant("step-small", 5, THIS, unit="percent")
    ch.constant("step-mid", 10, THIS, unit="percent")
    ch.constant("tol", TOL, THIS)
    ch.constant("bs-alpha", 0.01, THIS)
    render_table(OUT / "ch09_shift_detectors.csv", "ch09-shift-detectors", "Level-shift detectors on the weekly "
                 "calendar-adjusted log volume of each market: change points found in the real series, false-alarm "
                 "rate on permuted series, and the share of planted steps (in log units) found within a few weeks of "
                 "where they were planted.", digits=2)  # fmt: skip


def charts(ch: Chapter, con, tx: pd.DataFrame) -> None:
    src = MAIN / "transactions.parquet"
    rows = []
    ct = daily(con, "call_center_interactions")
    for table, d in (("transactions", tx), ("contacts", ct)):
        for ctry, g in d.groupby("country"):
            e = residuals(g)
            z = np.zeros_like(e)
            for i in range(len(e)):
                z[i] = LAMBDA * e[i] + (1 - LAMBDA) * (z[i - 1] if i else 0.0)
            lim = L * e.std() * np.sqrt(LAMBDA / (2 - LAMBDA))
            rows.append({"measure": table, "country": ctry, "chart": "EWMA", "days": len(e),
                         "alerts": int((np.abs(z) > lim).sum()), "lag-1 autocorrelation": float(np.corrcoef(e[:-1], e[1:])[0, 1]),
                         "dispersion": np.nan})  # fmt: skip
    for ctry, g in tx.groupby("country"):
        p = g.declined.sum() / g.n.sum()
        rate = g.declined / g.n
        lim = L * np.sqrt(p * (1 - p) / g.n)
        phi = float((g.n * (rate - p) ** 2 / (p * (1 - p))).sum() / (len(g) - 1))
        rows.append({"measure": "decline rate", "country": ctry, "chart": "p-chart", "days": len(g),
                     "alerts": int(((rate - p).abs() > lim).sum()), "lag-1 autocorrelation": float(np.corrcoef(rate[:-1], rate[1:])[0, 1]),
                     "dispersion": phi})  # fmt: skip
        ch.census(f"decline-dispersion-{CODE[ctry]}", phi, src, digits=3)
    t = pd.DataFrame(rows)
    t.to_csv(OUT / "ch09_charts.csv", index=False)
    ew = t[t.chart == "EWMA"]
    pc = t[t.chart == "p-chart"]
    ch.count("ewma-alerts", int(ew.alerts.sum()), src)
    ch.count("ewma-days", int(ew.days.sum()), src)
    ch.count("p-alerts", int(pc.alerts.sum()), src)
    ch.count("p-days", int(pc.days.sum()), src)
    nominal = 2 * stats.norm.sf(L)
    for tag, part in (("ewma", ew), ("p", pc)):
        expected = float(part.days.sum() * nominal)
        ch.census(f"{tag}-expected", expected, src, digits=2)
        ch.census(
            f"{tag}-tail", float(stats.poisson.sf(part.alerts.sum() - 1, expected)), src, digits=2
        )
    ch.census("nominal-alert-pct", 100 * 2 * stats.norm.sf(L), THIS, unit="percent", digits=2)
    ch.census("ewma-lag1-max", float(ew["lag-1 autocorrelation"].abs().max()), src, digits=2)
    ch.constant("lambda", LAMBDA, NB04, source_type="notebook")
    ch.constant("ewma-l", L, NB04, source_type="notebook")
    ch.census("dispersion-max", float(pc.dispersion.max()), src, digits=3)
    render_table(OUT / "ch09_charts.csv", "ch09-charts", "Control charts per market on the delivery clock: EWMA charts "
                 "of the calendar-adjusted log volume of transactions and contacts, and p-charts of the daily decline "
                 "rate, with the days alerted, the lag-one autocorrelation of the charted series and, for the decline "
                 "rate, its Pearson dispersion.", digits=3)  # fmt: skip


def hours(ch: Chapter, con) -> None:
    src = MAIN / "transactions.parquet"
    h = con.sql(f"""select c.country, cast(t.transaction_date - interval {CLOCK['transactions']} hour as date) as day,
                           hour(t.transaction_date - interval {CLOCK['transactions']} hour) as hr, count(*) as n
                    from m_transactions t join m_customers c using (customer_id) group by all""").df()  # fmt: skip
    h["day"] = pd.to_datetime(h.day)
    rows = []
    for ctry, g in h.groupby("country"):
        g = g[(g.day > g.day.min()) & (g.day < g.day.max())]
        grid = g.pivot_table(index="day", columns="hr", values="n", fill_value=0)
        tot = grid.sum(axis=1)
        wd = tot.index.dayofweek
        e_wd = tot.groupby(wd).transform("mean")
        c = max(1e-9, float((((tot - e_wd) ** 2 - e_wd).mean()) / (e_wd**2).mean()))
        mu = np.repeat((e_wd / 24).to_numpy()[:, None], 24, axis=1)
        x = grid.to_numpy()
        lo_p, hi_p = stats.poisson.ppf(0.0005, mu), stats.poisson.ppf(0.9995, mu)
        size = 1 / c
        pr = size / (size + mu)
        lo_n, hi_n = stats.nbinom.ppf(0.0005, size, pr), stats.nbinom.ppf(0.9995, size, pr)
        fp, fn = int(((x < lo_p) | (x > hi_p)).sum()), int(((x < lo_n) | (x > hi_n)).sum())
        # are the hours of a day a multinomial thinning of its total? Pearson dispersion of hour counts given the day
        expct = tot.to_numpy()[:, None] / 24
        phi_hour = float(((x - expct) ** 2 / (expct * (1 - 1 / 24))).sum() / (x.size - len(tot)))
        rows.append({"country": ctry, "hours": x.size, "day-level CV beyond Poisson": np.sqrt(c),
                     "Poisson flagged": fp / x.size, "negative binomial flagged": fn / x.size,
                     "hour dispersion given the day": phi_hour})  # fmt: skip
        tag = CODE[ctry]
        ch.census(f"cv-{tag}", 100 * np.sqrt(c), src, unit="percent", digits=2)
        ch.proportion(f"pois-{tag}", fp, x.size, intervals.wilson(fp, x.size), src, digits=2)
        ch.proportion(f"nb-{tag}", fn, x.size, intervals.wilson(fn, x.size), src, digits=2)
        ch.census(f"hour-phi-{tag}", phi_hour, src, digits=3)
    pd.DataFrame(rows).to_csv(OUT / "ch09_hours.csv", index=False)
    ch.census("hour-nominal-pct", 0.1, NB02, source_type="notebook", unit="percent")
    render_table(OUT / "ch09_hours.csv", "ch09-hours", "Hourly limits for transactions per market on the delivery "
                 "clock: the day-level variation beyond Poisson, the share of hours outside Poisson and "
                 "negative-binomial limits that a correct model would breach a thousandth of the time, and the "
                 "dispersion of hour counts given their day's total.", digits=3)  # fmt: skip


def main() -> None:
    con = db.connect()
    ch = Chapter(9, "ch09")
    OUT.mkdir(parents=True, exist_ok=True)
    src = MAIN / "transactions.parquet"
    tx = daily(con, "transactions")
    weekly, rows = {}, []
    for ctry, g in tx.groupby("country"):
        r = residuals(g)
        mad = 1.4826 * np.median(np.abs(r - np.median(r)))
        z = (r - np.median(r)) / mad
        weekly[ctry] = pd.Series(r, index=g.day.to_numpy()).resample("W").mean().dropna().to_numpy()
        rows.append({"country": ctry, "days": len(r), "residual sd": r.std(ddof=1), "abnormal": int((np.abs(z) > Z_DAY).sum()),
                     "lag1": float(np.corrcoef(r[:-1], r[1:])[0, 1]), "weeks": len(weekly[ctry]),
                     "weekly sd": float(np.std(weekly[ctry], ddof=1))})  # fmt: skip
    t = pd.DataFrame(rows)
    ch.count("days", int(t.days.iloc[0]), src)
    ch.count("weeks", int(t.weeks.iloc[0]), src)
    ch.count("abnormal", int(t.abnormal.sum()), src)
    ch.census("abnormal-expected", float(t.days.sum() * 2 * stats.norm.sf(Z_DAY)), src, digits=2)
    ch.census("resid-sd-min", float(t["residual sd"].min()), src, digits=2)
    ch.census("resid-sd-max", float(t["residual sd"].max()), src, digits=2)
    ch.census("weekly-sd-max", float(t["weekly sd"].max()), src, digits=2)
    ch.census("lag1-max", float(t.lag1.abs().max()), src, digits=2)
    ch.constant("z-day", Z_DAY, NB13, source_type="notebook")
    stored = pd.concat(
        [pd.read_csv(TABLES / f"country_{c}_anomalies.csv") for c in ("all", "mx", "co", "ar")]
    )
    ch.count(
        "nb-change-points",
        int(stored.change_points.sum()),
        TABLES / "country_all_anomalies.csv",
        source_type="table",
    )
    ch.count(
        "nb-abnormal",
        int(stored.abnormal_days.sum()),
        TABLES / "country_all_anomalies.csv",
        source_type="table",
    )
    shifts(ch, weekly)
    charts(ch, con, tx)
    hours(ch, con)
    print(f"{len(ch.claims)} claims -> {ch.write()}")


if __name__ == "__main__":
    main()
