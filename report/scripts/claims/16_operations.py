"""Chapter 16 · Operations: forecasting, cash, staffing, agents, cases and the clock.

Report-only re-analysis of granularity/04–06, granularity_hour/03–06 and granularity_time/02:

* the 7-day-ahead backtest of the daily series (calendar regression against the seasonal-naive forecast, on each
  market's delivery days), with the Diebold-Mariano test computed three ways: as the notebooks do (no
  autocorrelation term), with a Newey-West variance over the forecast horizon, and on the means of independent
  origin blocks;
* Erlang C staffing and its assumptions: the coefficient of variation of handle times against the exponential's;
* the Granger table's adjusted p-values against Benjamini-Hochberg;
* the stored results on cash (newsvendor, hierarchy), agent reliability, case survival, the SLA flag's agreement with
  the regulatory clock, shift adherence and hourly profiles.

    uv run python scripts/claims/16_operations.py
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import statsmodels.formula.api as smf
from scipy import stats

from report_lib import db
from report_lib.build import Chapter
from report_lib.eda import granularity as g
from report_lib.estimators import bh
from report_lib.paths import BUILD, REPO, TABLES
from report_lib.texgen import render_table

MAIN = REPO / "data" / "parquet"
OUT = BUILD / "sources"
NB04 = REPO / "eda" / "notebooks" / "granularity" / "04_market_and_channel_day.py"
H, STEP, TEST = (
    7,
    28,
    182,
)  # the notebook's backtest: 7 days ahead, an origin every 28 days, the last 182 days
CLOCK = {
    "transactions": ("transaction_date", 6),
    "call_center_interactions": ("interaction_date", 8),
}


def dm_nw(e1: np.ndarray, e2: np.ndarray, lag: int) -> tuple[float, float]:
    """Diebold-Mariano with a Newey-West (Bartlett) long-run variance and the Harvey correction for horizon lag + 1."""
    d = np.abs(e1) - np.abs(e2)
    n, m = len(d), d.mean()
    gam = [np.sum((d[k:] - m) * (d[: n - k] - m)) / n for k in range(lag + 1)]
    var = (gam[0] + 2 * sum((1 - k / (lag + 1)) * gam[k] for k in range(1, lag + 1))) / n
    h = lag + 1
    stat = m / np.sqrt(var) * np.sqrt((n + 1 - 2 * h + h * (h - 1) / n) / n)
    return float(stat), float(2 * stats.t.sf(abs(stat), n - 1))


def forecasts(ch: Chapter, con) -> None:
    rows = []
    for table, (ts, off) in CLOCK.items():
        d = con.sql(f"""select c.country, cast(t.{ts} - interval {off} hour as date) as day, count(*) as n
                        from m_{table} t join m_customers c using (customer_id) group by all order by 1, 2""").df()  # fmt: skip
        for ctry, x in d.groupby("country"):
            x = x.iloc[1:-1].reset_index(drop=True)  # partial first and last delivery days
            x["day"] = pd.to_datetime(x.day)
            x = x.assign(
                wd=x.day.dt.dayofweek,
                t=(x.day - x.day.min()).dt.days / 365.25,
                me=x.day.dt.is_month_end.astype(int),
            )
            v = x.n.to_numpy(float)
            n = len(v)
            pn, pc, block = np.full(n, np.nan), np.full(n, np.nan), np.full(n, -1)
            for b, o in enumerate(range(n - TEST, n - H + 1, STEP)):
                tg = list(range(o, min(o + H, n)))
                last = v[o - 7 : o]
                pn[tg] = [last[(k - o) % 7] for k in tg]
                fit = smf.ols("np.log1p(n) ~ C(wd) + me + t", data=x.iloc[:o]).fit()
                pc[tg] = np.expm1(fit.predict(x.iloc[tg]))
                block[tg] = b
            s = block >= 0
            e_n, e_c = (v - pn)[s], (v - pc)[s]
            ins = v[: np.argmax(s)]
            d_loss = np.abs(e_c) - np.abs(e_n)
            bmeans = pd.Series(d_loss).groupby(block[s]).mean().to_numpy()
            t_b = stats.ttest_1samp(bmeans, 0.0)
            rows.append({"series": "transactions" if table == "transactions" else "contacts", "market": ctry,
                         "errors": int(s.sum()), "origins": len(bmeans),
                         "MASE model": g.mase(v[s], pc[s], ins), "MASE naive": g.mase(v[s], pn[s], ins),
                         "p as in notebooks": g.diebold_mariano(e_c, e_n)[1], "p Newey-West": dm_nw(e_c, e_n, H - 1)[1],
                         "p origin blocks": float(t_b.pvalue)})  # fmt: skip
    t = pd.DataFrame(rows)
    t.to_csv(OUT / "ch16_forecasts.csv", index=False)
    src = MAIN / "transactions.parquet"
    ch.count("fc-series", len(t), src)
    ch.count("fc-errors", int(t.errors.iloc[0]), src)
    ch.count("fc-origins", int(t.origins.iloc[0]), src)
    ch.count("fc-beats-naive", int((t["MASE model"] < t["MASE naive"]).sum()), src)
    for col, tag in (
        ("p as in notebooks", "naive"),
        ("p Newey-West", "nw"),
        ("p origin blocks", "block"),
    ):
        ch.count(f"fc-sig-{tag}", int((t[col] < 0.05).sum()), src)
    ch.census("fc-mase-min", float(t["MASE model"].min()), src, digits=2)
    ch.census("fc-mase-max", float(t["MASE model"].max()), src, digits=2)
    ch.census(
        "fc-p-ratio-max", float((t["p Newey-West"] / t["p as in notebooks"]).max()), src, digits=2
    )
    ch.census(
        "fc-p-ratio-min", float((t["p Newey-West"] / t["p as in notebooks"]).min()), src, digits=2
    )
    for k, v in (("h", H), ("step", STEP), ("test", TEST)):
        ch.constant(f"fc-{k}", v, NB04, source_type="notebook")
    render_table(OUT / "ch16_forecasts.csv", "ch16-forecasts", "Seven-day-ahead backtest of daily volume per market on "
                 "the delivery clock: errors scored and origins, the mean absolute scaled error of the calendar "
                 "regression and of the seasonal-naive forecast, and the p-value of equal accuracy computed as the "
                 "notebooks do, with a Newey-West variance over the horizon, and on the means of the origin blocks.",
                 digits=3)  # fmt: skip
    stored = pd.read_csv(TABLES / "granularity_forecast_skill.csv")
    cov = stored[stored.model.str.contains("interval coverage")]
    assert cov.model.str.contains("80 %").all()
    ch.constant(
        "cov-nominal",
        80,
        TABLES / "granularity_forecast_skill.csv",
        source_type="table",
        unit="percent",
    )
    ch.census("cov80-min", 100 * float(cov.MASE.min()), TABLES / "granularity_forecast_skill.csv", source_type="table",
              unit="percent", digits=3)  # fmt: skip
    ch.census("cov80-max", 100 * float(cov.MASE.max()), TABLES / "granularity_forecast_skill.csv", source_type="table",
              unit="percent", digits=3)  # fmt: skip


def staffing(ch: Chapter, con) -> None:
    src = MAIN / "call_center_interactions.parquet"
    r = con.sql("""select avg(duration_seconds), stddev_samp(duration_seconds), min(duration_seconds),
                          max(duration_seconds), count(duration_seconds)
                   from m_call_center_interactions where interaction_type = 'Inbound Call'""").fetchone()  # fmt: skip
    cv = r[1] / r[0]
    ch.census("aht", float(r[0]), src, unit="seconds", digits=3)
    ch.census("aht-cv", float(cv), src, digits=2)
    ch.census("aht-min", float(r[2]), src)
    ch.census("aht-max", float(r[3]), src)
    ch.census("ac-factor", float((1 + cv**2) / 2), src, digits=2)
    # a worked staffing example at the mean inbound arrival rate of a market-hour
    lam = con.sql("""select count(*) / (count(distinct cast(interaction_date as date)) * 24.0)
                     from m_call_center_interactions where interaction_type = 'Inbound Call'""").fetchone()[0]  # fmt: skip
    c = g.agents_needed(lam, r[0], target_seconds=20, service=0.8)
    ch.census("lambda-hour", float(lam), src, digits=3)
    ch.census("load", float(lam * r[0] / 3600), src, digits=3)
    ch.count("agents-80-20", c, src)
    ch.census("pw", float(g.erlang_c(lam, r[0], c)), src, digits=2)
    ch.census("sl", 100 * float(g.service_level(lam, r[0], c, 20)), src, unit="percent", digits=3)
    a = lam * r[0] / 3600
    for k in (c - 1, c):
        wq = g.erlang_c(lam, r[0], k) * r[0] / (k - a)  # mean wait in M/M/c, seconds
        ch.census(f"wq-mmc-{k}", float(wq), src, unit="seconds", digits=3)
        ch.census(f"wq-mgc-{k}", float(wq * (1 + cv**2) / 2), src, unit="seconds", digits=3)
        ch.census(
            f"sl-{k}", 100 * float(g.service_level(lam, r[0], k, 20)), src, unit="percent", digits=3
        )
    ch.count("agents-fewer", c - 1, src)
    ch.constant("target-s", 20, REPO / "eda" / "notebooks" / "granularity" / "06_contact_centre_and_cases.py",
                source_type="notebook")  # fmt: skip
    ch.constant("target-share", 80, REPO / "eda" / "notebooks" / "granularity" / "06_contact_centre_and_cases.py",
                source_type="notebook", unit="percent")  # fmt: skip


def granger(ch: Chapter) -> None:
    p = TABLES / "granularity_granger.csv"
    gr = pd.read_csv(p)
    q = bh.adjust(gr.p_value.to_numpy())
    ch.count("granger-tests", len(gr), p, source_type="table")
    ch.census("granger-p-min", float(gr.p_value.min()), p, source_type="table", digits=2)
    ch.census("granger-q-min", float(q.min()), p, source_type="table", digits=2)
    ch.count("granger-stored-one", int((gr.p_adjusted == 1).sum()), p, source_type="table")
    ch.count("granger-bh-sig", int((q <= 0.05).sum()), p, source_type="table")


def stored(ch: Chapter) -> None:
    ae = pd.read_csv(TABLES / "granularity_agent_effects.csv")
    ap = TABLES / "granularity_agent_effects.csv"
    ch.count("agents", int(ae.agents.iloc[0]), ap, source_type="table")
    ch.census(
        "sb-max",
        float(ae["Spearman–Brown reliability"].abs().max()),
        ap,
        source_type="table",
        digits=2,
    )
    ch.census(
        "icc-max", float(ae["ICC (random intercept)"].max()), ap, source_type="table", digits=2
    )
    ae.to_csv(OUT / "ch16_agents.csv", index=False)
    render_table(OUT / "ch16_agents.csv", "ch16-agents", "Reliability of agent KPIs: the correlation of each agent's KPI "
                 "between random halves of their contacts, its Spearman-Brown projection to all contacts, and the "
                 "share of variance between agents in a random-intercept model (granularity notebook 06).", digits=3)  # fmt: skip

    cs = pd.read_csv(TABLES / "granularity_survival_cases.csv")
    cp = TABLES / "granularity_survival_cases.csv"
    ch.census(
        "case-resolved",
        float(cs["resolved %"].mean()),
        cp,
        source_type="table",
        unit="percent",
        digits=3,
    )
    ch.census(
        "case-naive-mean",
        float(cs["naive mean of resolved cases (days)"].mean()),
        cp,
        source_type="table",
        digits=3,
    )
    ch.census(
        "case-p30",
        100 * float(cs["P(resolved within 30 days)"].mean()),
        cp,
        source_type="table",
        unit="percent",
        digits=3,
    )
    ch.count("case-n", int(cs.cases.sum()), cp, source_type="table")
    tc = pd.read_csv(TABLES / "granularity_targets_contact.csv")
    tcp = TABLES / "granularity_targets_contact.csv"
    sla = tc[tc.target.str.startswith("SLA")].iloc[0]
    ch.census("sla-auc", float(sla.value), tcp, source_type="table", digits=3)
    ch.census("sla-auc-lo", float(sla.ci_low), tcp, source_type="table", digits=3)
    ch.census("sla-auc-hi", float(sla.ci_high), tcp, source_type="table", digits=3)

    cc = pd.read_csv(TABLES / "granularity_hour_case_clock.csv")
    ccp = TABLES / "granularity_hour_case_clock.csv"
    kap = cc[cc.test.str.contains("κ")]
    ch.census("kappa-max", float(kap.statistic.abs().max()), ccp, source_type="table", digits=2)
    ch.census(
        "kw-hour-p",
        float(cc[cc.test.str.contains("created hour")].p_value.iloc[0]),
        ccp,
        source_type="table",
        digits=2,
    )
    ch.census(
        "lr-priority-p",
        float(cc[cc.test.str.contains("priority")].p_value.iloc[0]),
        ccp,
        source_type="table",
        digits=2,
    )

    sh = pd.read_csv(TABLES / "granularity_hour_agent_shift.csv")
    shp = TABLES / "granularity_hour_agent_shift.csv"
    inside = sh[sh.test.str.contains("inside their shift")]
    ch.census(
        "shift-inside-min",
        100 * float(inside.statistic.min()),
        shp,
        source_type="table",
        unit="percent",
        digits=3,
    )
    ch.census(
        "shift-inside-max",
        100 * float(inside.statistic.max()),
        shp,
        source_type="table",
        unit="percent",
        digits=3,
    )

    ch_h = pd.read_csv(TABLES / "granularity_hour_channel_hour.csv")
    chp = TABLES / "granularity_hour_channel_hour.csv"
    ch.count("channel-tests", len(ch_h), chp, source_type="table")
    ch.count("channel-flat", int(ch_h.reading.eq("flat").sum()), chp, source_type="table")
    ch.census("channel-w-max", float(ch_h.effect.max()), chp, source_type="table", digits=2)

    bh_ = pd.read_csv(TABLES / "granularity_hour_branch_hours.csv")
    bp = TABLES / "granularity_hour_branch_hours.csv"
    wk = bh_[bh_.test.str.contains(r"Monday to Friday\), all")].iloc[0]
    ev = bh_[bh_.test.str.contains(r"every day\), all")].iloc[0]
    ch.census(
        "teller-out-obs",
        100 * float(wk.statistic),
        bp,
        source_type="table",
        unit="percent",
        digits=3,
    )
    ch.census(
        "teller-out-blind",
        100 * float(wk.statistic - wk.effect),
        bp,
        source_type="table",
        unit="percent",
        digits=3,
    )
    ch.census(
        "teller-every-obs",
        100 * float(ev.statistic),
        bp,
        source_type="table",
        unit="percent",
        digits=3,
    )
    ch.census(
        "teller-every-blind",
        100 * float(ev.statistic - ev.effect),
        bp,
        source_type="table",
        unit="percent",
        digits=3,
    )

    cash = pd.read_csv(TABLES / "granularity_cash.csv")
    cap = TABLES / "granularity_cash.csv"
    fc = cash[cash.table == "forecast"].set_index("model")
    ch.census(
        "cash-mase-boost",
        float(fc.loc["boosting", "median branch MASE"]),
        cap,
        source_type="table",
        digits=3,
    )
    ch.census(
        "cash-mase-naive",
        float(fc.loc["seasonal naive", "median branch MASE"]),
        cap,
        source_type="table",
        digits=3,
    )
    hi = cash[cash.table == "hierarchy"]
    ch.census(
        "hier-market-bu",
        float(hi["market MAE bottom-up"].mean()),
        cap,
        source_type="table",
        digits=3,
    )
    ch.census(
        "hier-market-td",
        float(hi["market MAE top-down"].mean()),
        cap,
        source_type="table",
        digits=3,
    )
    ch.census(
        "hier-branch-bu",
        float(hi["branch MAE bottom-up"].mean()),
        cap,
        source_type="table",
        digits=3,
    )
    ch.census(
        "hier-branch-td",
        float(hi["branch MAE top-down"].mean()),
        cap,
        source_type="table",
        digits=3,
    )
    pol = cash[cash.table == "policy"][
        ["policy", "service level %", "idle cash USD·days", "shortfall USD", "total cost (USD)"]
    ]
    pol.to_csv(OUT / "ch16_cash_policy.csv", index=False)
    render_table(OUT / "ch16_cash_policy.csv", "ch16-cash", "Branch cash policies over the backtest: the share of "
                 "branch-days whose demand the loaded cash covered, idle cash, shortfall and total cost (granularity "
                 "notebook 05).", digits=3)  # fmt: skip
    best = pol.loc[pol["total cost (USD)"].idxmin()]
    ch.census(
        "cash-best-sl",
        float(best["service level %"]),
        cap,
        source_type="table",
        unit="percent",
        digits=3,
    )
    ch.count("cash-policies", len(pol), cap, source_type="table")


def main() -> None:
    con = db.connect()
    ch = Chapter(16, "ch16")
    OUT.mkdir(parents=True, exist_ok=True)
    forecasts(ch, con)
    staffing(ch, con)
    granger(ch)
    stored(ch)
    print(f"{len(ch.claims)} claims -> {ch.write()}")


if __name__ == "__main__":
    main()
