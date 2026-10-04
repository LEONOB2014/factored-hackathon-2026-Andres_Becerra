# %% [markdown]
# # 04 · Market × day and channel × day: capacity, liquidity and operational monitoring
# **Granularity series** · grains: one market and local day (`agg.fct_country_day`), one market, transaction channel
# and local day (`agg.fct_channel_day`)
#
# **Stakeholders.** The chief operating officer (is today normal?), capacity planning for the contact centre, ATMs and
# app infrastructure (how much volume next week?), treasury (how much money moves out each day?) and the risk
# committee (decline and complaint rates against their limits).
#
# **What this grain adds.** A market's day aggregates thousands of events, so its noise is small relative to its level
# (notebook 01: no zeros, large counts). If anything in the bank has structure in time (weekday cycles, paydays,
# trends, shocks), it shows here first. And the day is the unit at which operations are staffed and monitored.
#
# **Methods.**
# 1. **Forecastability by rolling-origin backtest.** For each series, 7-day-ahead forecasts are made every 28 days over
#    the last 26 weeks, each time refitting on all data before the forecast origin (expanding window). Four forecasters:
#    the **seasonal naive** (the value 7 days earlier, the benchmark every forecast must beat), a **calendar
#    regression** (OLS on log volume with weekday, holiday, long weekend, payday window, month end and trend), a
#    **SARIMAX** with weekly seasonality, and **gradient boosting** on lags and the calendar. Skill is the **MASE**
#    (mean absolute error over the in-sample seasonal-naive error; below 1 beats the benchmark), the
#    **Diebold–Mariano** test says whether the gain is real, and the calendar regression's 80 % prediction intervals
#    are checked for coverage.
# 2. **Granger causality between processes** on calendar-adjusted daily residuals: do today's digital errors help
#    predict tomorrow's contacts, today's contacts tomorrow's complaints?
# 3. **Control charts** for the operational KPIs (EWMA on calendar-adjusted residuals; a p-chart for the decline rate):
#    how often would an alert fire, and on which days?

# %%
import sys
import time
import warnings
from pathlib import Path

sys.path.insert(0, "../../src")
import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import statsmodels.formula.api as smf
from IPython.display import Markdown, display
from itables import show
from sklearn.ensemble import HistGradientBoostingRegressor
from statsmodels.tsa.statespace.sarimax import SARIMAX
from statsmodels.tsa.stattools import grangercausalitytests

from latam_eda import country, theme
from latam_eda import granularity as g

warnings.filterwarnings("ignore")
OUT = Path("../../reports/tables")
OUT.mkdir(parents=True, exist_ok=True)
theme.register()
t0 = time.time()
pl = country.session("ALL", "main")
country.prepare(pl, "gold")
star = g.open_star(pl)
star.build(["fct_country_day", "fct_channel_day", "dim_data_day"], verbose=False)
day = star.q("""
    select f.*, d.iso_weekday, d.is_holiday, d.is_long_weekend, d.is_month_end, d.is_bonus_month,
           coalesce(d.days_since_payday, 99) <= 2 as payday_window, d.is_edge
    from {fct_country_day} f join {dim_data_day} d using (country_code, local_date)
    where not d.is_edge order by country_code, local_date""")
day["local_date"] = pd.to_datetime(day.local_date)
print(day.groupby("country_code").local_date.agg(["min", "max", "count"]))

# %% [markdown]
# ## 1 · The operational day of each market

# %%
fig = px.line(
    day,
    x="local_date",
    y="n_tx",
    color="country_code",
    title="Transactions per local day, by market",
)
fig.update_layout(height=320, xaxis_title=None)
fig.show()
KPI = day.groupby("country_code").agg(
    tx_per_day=("n_tx", "mean"),
    outflow_usd_per_day=("outflow_usd", "mean"),
    contacts_per_day=("contacts", "mean"),
    complaints_per_day=("complaints_opened", "mean"),
    decline_rate_pct=("n_declined", "sum"),
    escalation_rate_pct=("escalations", "sum"),
)
tot = day.groupby("country_code")[["n_tx", "contacts"]].sum()
KPI["decline_rate_pct"] = 100 * KPI.decline_rate_pct / tot.n_tx
KPI["escalation_rate_pct"] = 100 * KPI.escalation_rate_pct / tot.contacts
show(KPI.round(2), paging=False)

# %% [markdown]
# ## 2 · Forecastability: rolling-origin backtest, 7 days ahead

# %%
SERIES = ["n_tx", "outflow_usd", "contacts", "complaints_opened", "digital_errors", "sessions"]
H, STEP, TEST_DAYS = 7, 28, 182


def design(d: pd.DataFrame) -> pd.DataFrame:
    x = d[
        [
            "local_date",
            "iso_weekday",
            "is_holiday",
            "is_long_weekend",
            "payday_window",
            "is_month_end",
        ]
    ].copy()
    x["t"] = (x.local_date - x.local_date.min()).dt.days / 365.25
    for c in ["is_holiday", "is_long_weekend", "payday_window", "is_month_end"]:
        x[c] = x[c].astype(int)
    return x


def backtest(d: pd.DataFrame, y: str) -> dict[str, np.ndarray]:
    d = d.reset_index(drop=True)
    x = design(d)
    vals = d[y].astype(float).to_numpy()
    n = len(d)
    origins = list(range(n - TEST_DAYS, n - H + 1, STEP))
    pred = {
        k: np.full(n, np.nan)
        for k in ["seasonal naive", "calendar regression", "SARIMAX", "boosting"]
    }
    lo80, hi80 = np.full(n, np.nan), np.full(n, np.nan)
    lagdf = pd.DataFrame({f"lag{k}": pd.Series(vals).shift(k) for k in (7, 14, 21, 28)})
    lagdf["roll28"] = pd.Series(vals).shift(7).rolling(28).mean()
    feats = pd.concat([x.drop(columns="local_date"), lagdf], axis=1)
    for o in origins:
        tgt = range(o, min(o + STEP, n))
        # seasonal naive at horizon 7: the value one week before each target day (known at the origin for h <= 7;
        # beyond, the last observed week is repeated)
        last_week = vals[o - 7 : o]
        pred["seasonal naive"][list(tgt)] = [last_week[(k - o) % 7] for k in tgt]
        train = slice(0, o)
        dfit = x.iloc[train].assign(y=np.log1p(vals[train]))
        ols = smf.ols(
            "y ~ C(iso_weekday) + is_holiday + is_long_weekend + payday_window + is_month_end + t",
            data=dfit,
        ).fit()
        fut = x.iloc[list(tgt)]
        p = ols.get_prediction(fut).summary_frame(alpha=0.2)
        pred["calendar regression"][list(tgt)] = np.expm1(p["mean"].to_numpy())
        lo80[list(tgt)] = np.expm1(p["obs_ci_lower"].to_numpy())
        hi80[list(tgt)] = np.expm1(p["obs_ci_upper"].to_numpy())
        try:
            ex = x[["is_holiday", "is_long_weekend", "payday_window", "is_month_end"]].astype(float)
            sm_ = SARIMAX(
                np.log1p(vals[train]),
                exog=ex.iloc[train],
                order=(1, 0, 1),
                seasonal_order=(1, 0, 1, 7),
                trend="c",
            ).fit(disp=False, maxiter=60)
            pred["SARIMAX"][list(tgt)] = np.expm1(sm_.forecast(len(tgt), exog=ex.iloc[list(tgt)]))
        except (
            Exception
        ) as exc:  # a non-converging fit leaves this origin unscored for SARIMAX, and says so
            print(f"SARIMAX did not fit for {y} at origin {o}: {type(exc).__name__}")
        ok = ~feats.iloc[train].isna().any(axis=1).to_numpy()
        gb = HistGradientBoostingRegressor(max_iter=200, learning_rate=0.05, random_state=7).fit(
            feats.iloc[train][ok], np.log1p(vals[train][ok])
        )
        # direct strategy: lags of 7+ days are known for every target day of the block when the horizon is <= 7;
        # beyond the first week of a 28-day block they would need recursion, so only the first 7 days are scored
        pred["boosting"][list(tgt)] = np.expm1(gb.predict(feats.iloc[list(tgt)].fillna(0)))
    scored = np.zeros(n, dtype=bool)
    for o in origins:
        scored[o : min(o + H, n)] = True  # score the 7-day horizon after each origin
    return {"y": vals, "pred": pred, "lo80": lo80, "hi80": hi80, "scored": scored}


rows, sig_rows, examples = [], [], {}
for cc, d in day.groupby("country_code"):
    for y in SERIES:
        r = backtest(d, y)
        s = r["scored"]
        insample = r["y"][: np.argmax(s)]
        e_naive = (r["y"] - r["pred"]["seasonal naive"])[s]
        best, best_m = None, np.inf
        for m, p in r["pred"].items():
            if np.isnan(p[s]).all():
                continue
            mm = g.mase(r["y"][s], p[s], insample)
            stat, pv = (np.nan, np.nan)
            if m != "seasonal naive":
                stat, pv = g.diebold_mariano(r["y"][s] - p[s], e_naive)
                if mm < best_m:
                    best, best_m, best_p = m, mm, pv
            rows.append(
                {
                    "market": cc,
                    "series": y,
                    "model": m,
                    "MASE": mm,
                    "DM stat vs naive": stat,
                    "DM p": pv,
                }
            )
        cov = np.mean((r["y"][s] >= r["lo80"][s]) & (r["y"][s] <= r["hi80"][s]))
        rows.append(
            {
                "market": cc,
                "series": y,
                "model": "calendar regression 80 % interval coverage",
                "MASE": cov,
            }
        )
        naive_m = g.mase(r["y"][s], r["pred"]["seasonal naive"][s], insample)
        sig_rows.append(g.forecast_row(f"market × day ({cc})", y, best, best_m, naive_m, best_p))
        examples[(cc, y)] = (d.local_date.to_numpy(), r)
skill = pd.DataFrame(rows)
skill.to_csv(OUT / "granularity_forecast_skill.csv", index=False)
piv = skill[~skill.model.str.contains("coverage")].pivot_table(
    index=["market", "series"], columns="model", values="MASE"
)
show(piv.round(3), paging=False)
cov = skill[skill.model.str.contains("coverage")].pivot_table(
    index="series", columns="market", values="MASE"
)
show((100 * cov).round(1).rename_axis("80 % interval coverage (%)"), paging=False)

# %%
dts, r = examples[("MX", "n_tx")]
s = r["scored"]
fig = go.Figure()
fig.add_trace(
    go.Scatter(
        x=dts[-TEST_DAYS - 56 :], y=r["y"][-TEST_DAYS - 56 :], name="actual", line=dict(width=1)
    )
)
for m in ["seasonal naive", "calendar regression", "boosting"]:
    p = np.where(s, r["pred"][m], np.nan)
    fig.add_trace(go.Scatter(x=dts, y=p, name=m, mode="markers", marker=dict(size=4)))
fig.update_layout(
    title="Mexico, transactions per day: 7-day-ahead forecasts at each origin",
    height=360,
    xaxis_title=None,
)
fig.update_xaxes(range=[dts[-TEST_DAYS - 56], dts[-1]])
fig.show()
sig = pd.DataFrame(sig_rows).reindex(columns=g.TARGET_COLUMNS)
best_by = piv.min(axis=1)
naive_by = piv["seasonal naive"]
gain = (1 - best_by / naive_by).groupby(level="series").mean()
display(
    Markdown(
        f"**Across {len(piv)} market series the best model's MASE averages {best_by.mean():.3f} against "
        f"{naive_by.mean():.3f} for the seasonal naive** (mean error reduction "
        + ", ".join(f"{k} {100 * v:.0f} %" for k, v in gain.items())
        + f"). {int(sig.verdict.str.startswith('forecastable').sum())} of {len(sig)} series are forecastable (better "
        "than the seasonal naive by over 10 %, Diebold–Mariano p < 0.05). "
        f"The calendar regression's 80 % intervals cover {100 * cov.stack().mean():.0f} % of the actual days. "
        + (
            "Volumes follow the weekly cycle and little else: a model that knows the weekday and the recent level is "
            "all the planning a market-day needs, and the gain over repeating last week is in the noise it averages "
            "out."
            if best_by.mean() > 0.6
            else "There is structure beyond the weekly cycle to exploit."
        )
    )
)

# %% [markdown]
# ## 3 · Channel × day: where volume moves between channels
# Channel capacity (ATM fleet, tellers, app servers) is planned per channel. Two questions: are the channel shares
# stable (is volume migrating to digital?), and is each channel's daily volume as forecastable as the market's?

# %%
ch = star.q("""select f.*, d.iso_weekday from {fct_channel_day} f join {dim_data_day} d using (country_code, local_date)
               where not d.is_edge""")
ch["local_date"] = pd.to_datetime(ch.local_date)
ch["month"] = ch.local_date.dt.to_period("M").dt.to_timestamp()
share = ch.groupby(["country_code", "month", "channel"]).n_tx.sum().reset_index()
share["share"] = share.n_tx / share.groupby(["country_code", "month"]).n_tx.transform("sum")
fig = px.line(
    share[share.country_code == "MX"],
    x="month",
    y="share",
    color="channel",
    title="Mexico: monthly channel share of transactions",
)
fig.update_layout(height=320, yaxis_tickformat=".0%", xaxis_title=None)
fig.show()
trend = []
for (cc, c), d in share.groupby(["country_code", "channel"]):
    t = (d.month - d.month.min()).dt.days / 365.25
    fit = smf.ols("share ~ t", data=d.assign(t=t)).fit()
    trend.append(
        {
            "market": cc,
            "channel": c,
            "mean share %": 100 * d.share.mean(),
            "trend points/year": 100 * fit.params["t"],
            "p": fit.pvalues["t"],
        }
    )
trend = pd.DataFrame(trend)
show(trend.round(4), paging=False)
mig = trend[(trend.p < 0.01) & (trend["trend points/year"].abs() > 0.5)]
display(
    Markdown(
        f"**{len(mig)} market-channel shares move by more than half a point a year (p < 0.01).** "
        + (
            "The channel mix is frozen: no migration to digital, no decline of branches. A real bank's channel strategy is "
            "built on that migration; here capacity per channel can be planned as a fixed share of the market forecast."
            if not len(mig)
            else "Migrating: "
            + ", ".join(
                f"{r.market} {r.channel} ({r['trend points/year']:+.2f})" for r in mig.itertuples()
            )
        )
    )
)

# %% [markdown]
# ## 4 · Granger causality between processes
# On calendar-adjusted residuals (log daily count minus the calendar regression fit), does the past of one process
# improve the forecast of another beyond its own past? Tested with lags 1 to 7 days; the smallest p-value over lags is
# reported and every test enters the false-discovery control of notebook 09.

# %%
PAIRS = [
    ("digital_errors", "contacts"),
    ("contacts", "complaints_opened"),
    ("n_declined", "contacts"),
    ("sends", "n_tx"),
    ("escalations", "complaints_opened"),
]
gr = []
for cc, d in day.groupby("country_code"):
    x = design(d.reset_index(drop=True))
    res = {}
    for col in {c for p in PAIRS for c in p}:
        fit = smf.ols(
            "y ~ C(iso_weekday) + is_holiday + is_long_weekend + payday_window + is_month_end + t",
            data=x.assign(y=np.log1p(d[col].astype(float).to_numpy())),
        ).fit()
        res[col] = fit.resid.to_numpy()
    for a, b in PAIRS:
        out = grangercausalitytests(np.column_stack([res[b], res[a]]), maxlag=7)
        ps = {lag: v[0]["ssr_ftest"][1] for lag, v in out.items()}
        lag = min(ps, key=ps.get)
        gr.append(
            {"market": cc, "cause": a, "effect": b, "best lag (days)": lag, "p_value": ps[lag]}
        )
gr = pd.DataFrame(gr)
gr["significant (FDR 5 %)"], gr["p_adjusted"] = g.bh_fdr(
    gr.p_value * 7
)  # Bonferroni over the 7 lags, then BH
gr.to_csv(OUT / "granularity_granger.csv", index=False)
show(gr.round(4), paging=False)
display(
    Markdown(
        f"**{int(gr['significant (FDR 5 %)'].sum())} of {len(gr)} process links survive the false-discovery control.** "
        + (
            "No process leads another: digital errors do not raise tomorrow's contacts, contacts do not raise tomorrow's "
            "complaints, campaign sends do not lift tomorrow's transactions. Each process is generated independently "
            "of the others, so an operations copilot that explains a spike in one process by a rise in another would "
            "have nothing true to say on this data."
            if not gr["significant (FDR 5 %)"].any()
            else "Significant links: "
            + ", ".join(
                f"{r.market} {r.cause} → {r.effect}"
                for r in gr[gr["significant (FDR 5 %)"]].itertuples()
            )
        )
    )
)

# %% [markdown]
# ## 5 · Control charts: how often would operations be alerted?
# An EWMA chart (λ = 0.2) on the calendar-adjusted log residuals of daily contacts and complaints, with 3σ limits, and a
# p-chart of the daily decline rate (binomial limits from each day's volume). A well-calibrated chart on stable data
# fires about 0.3 % of days; more means real special causes (or a mis-specified baseline).

# %%
alerts = []
for cc, d in day.groupby("country_code"):
    d = d.reset_index(drop=True)
    x = design(d)
    for col in ["contacts", "complaints_opened", "n_tx"]:
        fit = smf.ols(
            "y ~ C(iso_weekday) + is_holiday + is_long_weekend + payday_window + is_month_end + t",
            data=x.assign(y=np.log1p(d[col].astype(float))),
        ).fit()
        e = fit.resid.to_numpy()
        lam, sd = 0.2, e.std()
        z = np.zeros_like(e)
        for i in range(len(e)):
            z[i] = lam * e[i] + (1 - lam) * (z[i - 1] if i else 0)
        lim = 3 * sd * np.sqrt(lam / (2 - lam))
        alerts.append(
            {
                "market": cc,
                "KPI": col,
                "chart": "EWMA",
                "days": len(e),
                "alerts": int((np.abs(z) > lim).sum()),
            }
        )
    p_bar = d.n_declined.sum() / d.n_tx.sum()
    lim = 3 * np.sqrt(p_bar * (1 - p_bar) / d.n_tx)
    rate = d.n_declined / d.n_tx
    alerts.append(
        {
            "market": cc,
            "KPI": "decline rate",
            "chart": "p-chart",
            "days": len(d),
            "alerts": int(((rate - p_bar).abs() > lim).sum()),
        }
    )
al = pd.DataFrame(alerts)
al["alert rate %"] = (100 * al.alerts / al.days).round(2)
show(al, paging=False)
display(
    Markdown(
        f"**{int(al.alerts.sum())} alerts in {int(al.days.sum()):,} chart-days ({100 * al.alerts.sum() / al.days.sum():.2f} %).** "
        + (
            "At or below the false-alarm rate of a 3σ chart: the bank has no special-cause days. Control charts are still "
            "the right operational KPI layer (they are what would catch an outage, a fraud wave or a data-delivery "
            "gap on real data), and their baseline is the calendar regression above."
            if al.alerts.sum() / al.days.sum() < 0.01
            else "More alerts than chance: inspect the days flagged."
        )
    )
)

# %%
sig.to_csv(OUT / "granularity_targets_day.csv", index=False)
show(sig, paging=False)

# %% [markdown]
# ## Findings, decisions and what they mean downstream
# * **Capacity planning:** the market-day forecast is a calendar regression (or simply last week) plus the weekly
#   cycle; it needs no machine learning. The deliverable is a 7-day forecast with intervals per market and channel,
#   refreshed daily, which the contact-centre staffing of notebook 06 consumes.
# * **Operations monitoring:** the KPIs of this notebook (volume, outflow, decline rate, contacts, complaints,
#   escalation rate) with calendar-adjusted control limits are the content of an **operations copilot**: an agent that
#   answers "was yesterday normal, and if not, where" from `fct_country_day`, never from free text. Its value on real
#   data is in the special causes this synthetic data does not contain.
# * **Downstream:** `fct_country_day` and `fct_channel_day` are small (thousands of rows), cheap to build and to serve;
#   the streaming layer should produce their intraday counterpart (the same measures, per hour) with a parity test
#   against the batch day, as the fraud features already do.

# %%
pl.close()
print(f"notebook time {time.time() - t0:.0f}s")
