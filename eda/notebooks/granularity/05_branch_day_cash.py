# %% [markdown]
# # 05 · Branch × day: cash logistics
# **Granularity series** · grain: one branch (with its ATMs) and local day (`agg.fct_branch_day`, 350 branches)
#
# **Stakeholders.** Treasury and cash operations: every branch and ATM must hold enough cash for the day's withdrawals
# (a stock-out turns a customer away and forces an emergency cash-in-transit run), but every unit of idle cash costs
# money (the funding rate, insurance, security). The decision is taken per branch and day: how much cash to load.
#
# **What this grain adds.** At the market-day grain, cash demand is smooth and easy to forecast (notebook 04). At the
# branch-day grain it is a handful of withdrawals per branch per day, noisy and lumpy, and that noise is exactly what
# decides how much buffer cash a branch needs. Aggregation hides the cost.
#
# **Methods.**
# 1. **Demand profile** per branch: level, dispersion, zero days, concentration across branches.
# 2. **Forecasts 7 days ahead** by rolling origin (every 28 days over the last 26 weeks): the seasonal naive (same
#    weekday last week), a 28-day moving average, a **multiplicative seasonal index** (the branch's 28-day level times
#    its market's weekday index), and pooled **gradient boosting** on lags, levels and the calendar. Skill: MASE and
#    the Diebold–Mariano test against the seasonal naive.
# 3. **Hierarchical coherence:** branch forecasts summed to the market (bottom-up) against the market forecast split by
#    historical branch shares (top-down), judged at both levels.
# 4. **From forecast to cash: the newsvendor.** Load the forecast plus a buffer equal to the q-quantile of past
#    forecast errors, with q = Cu / (Cu + Co) set by the cost of a stock-out (Cu, per unit short) and the cost of idle
#    cash (Co, per unit left over). The backtest reports the service level achieved and the cash held, against the
#    common rule of thumb of loading last month's busiest day.

# %%
import sys
import time
from pathlib import Path

sys.path.insert(0, "../../src")
import numpy as np
import pandas as pd
import plotly.express as px
from IPython.display import Markdown, display
from itables import show
from sklearn.ensemble import HistGradientBoostingRegressor

from latam_eda import country, theme
from latam_eda import granularity as g

OUT = Path("../../reports/tables")
OUT.mkdir(parents=True, exist_ok=True)
theme.register()
t0 = time.time()
pl = country.session("ALL", "main")
country.prepare(pl, "gold")
star = g.open_star(pl)
star.build(["fct_branch_day", "dim_data_day"], verbose=False)
bd = star.q("""
    select f.branch_id, f.local_date, f.country_code, f.atm_count, f.n_withdrawals, f.withdrawals_usd, f.n_tx,
           d.iso_weekday, d.is_holiday, coalesce(d.days_since_payday, 99) <= 2 as payday_window, d.is_month_end
    from {fct_branch_day} f
    join (select distinct local_date, country_code, iso_weekday, is_holiday, days_since_payday, is_month_end, is_edge
          from {dim_data_day}) d using (local_date, country_code)
    where not d.is_edge order by branch_id, local_date""")
bd["local_date"] = pd.to_datetime(bd.local_date)
print(f"{bd.branch_id.nunique()} branches × {bd.local_date.nunique()} days = {len(bd):,} rows")

# %% [markdown]
# ## 1 · How much cash does a branch dispense in a day?

# %%
per = (
    bd.groupby(["branch_id", "country_code", "atm_count"])
    .agg(
        withdrawals_per_day=("n_withdrawals", "mean"),
        usd_per_day=("withdrawals_usd", "mean"),
        usd_sd=("withdrawals_usd", "std"),
        zero_days=("n_withdrawals", lambda x: (x == 0).mean()),
    )
    .reset_index()
)
per["cv"] = per.usd_sd / per.usd_per_day
fig = px.histogram(
    per,
    x="usd_per_day",
    color="country_code",
    nbins=50,
    title="Average daily cash withdrawn per branch (USD)",
)
fig.update_layout(height=320)
fig.show()
show(
    per.groupby("country_code")[["withdrawals_per_day", "usd_per_day", "cv", "zero_days"]]
    .median()
    .round(3),
    paging=False,
)
shares = per.usd_per_day / per.usd_per_day.sum()
display(
    Markdown(
        f"**A median branch dispenses {per.withdrawals_per_day.median():.1f} withdrawals and "
        f"{per.usd_per_day.median():,.0f} USD a day, with a day-to-day coefficient of variation of "
        f"{per.cv.median():.2f} and no withdrawal on {100 * per.zero_days.median():.1f} % of days.** Cash demand is "
        f"spread across branches (HHI {g.hhi(shares):,.0f} on a 0–10,000 scale; an even split over {len(per)} "
        f"branches would be {10_000 / len(per):,.0f}). "
        + (
            "The day-to-day variation is as large as the level itself: the buffer, not the forecast, is where the cash "
            "goes."
            if per.cv.median() > 0.7
            else "Daily demand is steady relative to its level."
        )
    )
)
corr = per[["atm_count", "usd_per_day"]].corr(method="spearman").iloc[0, 1]
display(
    Markdown(
        f"Branches with more ATMs do {'not ' if abs(corr) < 0.1 else ''}dispense more cash (Spearman "
        f"{corr:.2f} between ATM count and daily cash): "
        + (
            "the fleet size carries no information about demand here, so it cannot size the cash load."
            if abs(corr) < 0.1
            else "fleet size is a usable prior for new branches."
        )
    )
)

# %% [markdown]
# ## 2 · Forecasting each branch's daily cash, 7 days ahead

# %%
Y = bd.pivot(index="local_date", columns="branch_id", values="withdrawals_usd").fillna(0)
dates = Y.index
cal = bd.drop_duplicates(["local_date", "country_code"]).set_index(["country_code", "local_date"])[
    ["iso_weekday", "is_holiday", "payday_window", "is_month_end"]
]
br_cc = per.set_index("branch_id").country_code.reindex(Y.columns)
H, STEP, TEST = 7, 28, 182
n = len(dates)
origins = list(range(n - TEST, n - H + 1, STEP))
P = {
    m: np.full(Y.shape, np.nan)
    for m in ["seasonal naive", "28-day average", "seasonal index", "boosting"]
}
Yv = Y.to_numpy()
long = bd[
    [
        "branch_id",
        "local_date",
        "withdrawals_usd",
        "country_code",
        "iso_weekday",
        "is_holiday",
        "payday_window",
        "is_month_end",
        "atm_count",
    ]
].copy()
long = long.sort_values(["branch_id", "local_date"])
grp = long.groupby("branch_id").withdrawals_usd
for k in (7, 14, 21, 28):
    long[f"lag{k}"] = grp.shift(k)
long["ma28_lag7"] = grp.transform(lambda s: s.shift(7).rolling(28).mean())
long["cc"] = long.country_code.map({"MX": 0, "CO": 1, "AR": 2})
for c in ["is_holiday", "payday_window", "is_month_end"]:
    long[c] = long[c].astype(int)
FEAT = [
    "lag7",
    "lag14",
    "lag21",
    "lag28",
    "ma28_lag7",
    "iso_weekday",
    "is_holiday",
    "payday_window",
    "is_month_end",
    "atm_count",
    "cc",
]
for o in origins:
    tgt = np.arange(o, min(o + H, n))
    P["seasonal naive"][tgt] = Yv[tgt - 7]
    lvl = Yv[o - 28 : o].mean(axis=0)
    P["28-day average"][tgt] = lvl
    # weekday index per market: mean of each weekday over the last 26 weeks / overall mean, from training days only
    hist = Y.iloc[max(0, o - 182) : o]
    wd = pd.Series(dates[max(0, o - 182) : o].weekday + 1, index=hist.index)
    idx = {}
    for cc in ["MX", "CO", "AR"]:
        cols = br_cc.index[br_cc == cc]
        m = hist[cols].sum(axis=1)
        idx[cc] = (m.groupby(wd.to_numpy()).mean() / m.mean()).to_dict()
    for j, t in enumerate(tgt):
        w = dates[t].weekday() + 1
        P["seasonal index"][t] = lvl * br_cc.map(lambda c: idx[c][w]).to_numpy()
    train = long[(long.local_date < dates[o])].dropna(subset=FEAT)
    train = train[train.local_date >= dates[o] - pd.Timedelta(days=365)]
    gb = HistGradientBoostingRegressor(max_iter=200, learning_rate=0.05, random_state=7).fit(
        train[FEAT], np.log1p(train.withdrawals_usd)
    )
    test = long[long.local_date.isin(dates[tgt])]
    pr = pd.Series(
        np.expm1(gb.predict(test[FEAT].fillna(0))), index=[test.local_date, test.branch_id]
    )
    P["boosting"][tgt] = pr.unstack().reindex(index=dates[tgt], columns=Y.columns).to_numpy()
scored = np.zeros(n, dtype=bool)
for o in origins:
    scored[o : o + H] = True
ins = Yv[: origins[0]]
scale = np.mean(np.abs(ins[7:] - ins[:-7]), axis=0)
rows = []
err_naive = (Yv - P["seasonal naive"])[scored]
for m, p in P.items():
    e = (Yv - p)[scored]
    mase_b = np.mean(np.abs(e), axis=0) / scale
    stat, pv = (
        (np.nan, np.nan)
        if m == "seasonal naive"
        else g.diebold_mariano(e.ravel(), err_naive.ravel())
    )
    rows.append(
        {
            "model": m,
            "median branch MASE": np.median(mase_b),
            "pooled MAE (USD)": np.mean(np.abs(e)),
            "DM stat vs naive": stat,
            "DM p": pv,
        }
    )
fs = pd.DataFrame(rows)
show(fs.round(4), paging=False)
best = fs.iloc[1:].sort_values("pooled MAE (USD)").iloc[0]
naive_m = fs.iloc[0]["median branch MASE"]
display(
    Markdown(
        f"**Best branch-day forecaster: {best.model}, median MASE {best['median branch MASE']:.3f} against "
        f"{naive_m:.3f} for the seasonal naive** (pooled MAE {best['pooled MAE (USD)']:,.0f} USD a branch-day against "
        f"{fs.iloc[0]['pooled MAE (USD)']:,.0f}). At this grain last week's value is a poor forecast: a single week of "
        "a few withdrawals is mostly noise, and every method that smooths over a month (the 28-day average "
        f"{fs.set_index('model').loc['28-day average', 'median branch MASE']:.3f}, the seasonal index "
        f"{fs.set_index('model').loc['seasonal index', 'median branch MASE']:.3f}) beats it. Boosting is fitted on "
        "log values, so it forecasts each branch's typical (median) day, which is what the absolute-error metric "
        "rewards; section 3 shows the price of that."
    )
)

# %% [markdown]
# ## 3 · Hierarchical coherence: forecast the branch, or split the market?
# Treasury plans at two levels: the market (how much cash to order from the central bank) and the branch (where to
# send it). Bottom-up sums the branch forecasts; top-down forecasts the market total (seasonal index on the total)
# and splits it by each branch's share of the last 28 days. Errors are compared at both levels.

# %%
best_name = best.model
bu_branch = P[best_name]
lvl_rows = []
for cc in ["MX", "CO", "AR"]:
    cols = np.flatnonzero((br_cc == cc).to_numpy())
    tot = Yv[:, cols].sum(axis=1)
    bu = bu_branch[:, cols].sum(axis=1)
    td_tot = P["seasonal index"][:, cols].sum(
        axis=1
    )  # the seasonal index is linear in the level: its sum is the total's
    sh = np.vstack(
        [Yv[o - 28 : o, cols].sum(axis=0) / max(Yv[o - 28 : o, cols].sum(), 1) for o in origins]
    )
    td_branch = np.full((n, len(cols)), np.nan)
    for i, o in enumerate(origins):
        td_branch[o : o + H] = td_tot[o : o + H, None] * sh[i]
    s = scored
    lvl_rows.append(
        {
            "market": cc,
            "market MAE bottom-up": np.mean(np.abs(tot[s] - bu[s])),
            "market MAE top-down": np.mean(np.abs(tot[s] - td_tot[s])),
            "branch MAE bottom-up": np.mean(np.abs(Yv[s][:, cols] - bu_branch[s][:, cols])),
            "branch MAE top-down": np.mean(np.abs(Yv[s][:, cols] - td_branch[s])),
        }
    )
hier = pd.DataFrame(lvl_rows)
show(hier.round(1), paging=False)
display(
    Markdown(
        f"**Bottom-up {best_name} forecasts each branch {'better' if (hier['branch MAE bottom-up'] < hier['branch MAE top-down']).all() else 'no better'} "
        f"than the top-down split (branch MAE {hier['branch MAE bottom-up'].mean():,.0f} against "
        f"{hier['branch MAE top-down'].mean():,.0f} USD), but its sum misses the market total by "
        f"{(hier['market MAE bottom-up'] / hier['market MAE top-down']).mean():.1f}× the top-down error.** "
        + (
            "This is retransformation bias: a model fitted on log values forecasts each branch's median, medians of "
            "skewed demand sit below the means, and the shortfalls add up across 350 branches. Medians do not "
            "aggregate; means do. **Use two forecasts for two decisions:** the mean-based market forecast (seasonal "
            "index) for the cash ordered from the central bank, split top-down by branch share, and a branch-level "
            "quantile (section 4) for each branch's load. Never sum log-model forecasts into a total."
            if (hier["market MAE bottom-up"] > 1.5 * hier["market MAE top-down"]).all()
            else "Both methods give coherent totals: one market forecast and a share table is enough."
        )
    )
)

# %% [markdown]
# ## 4 · From forecast to cash loaded: the newsvendor
# **Assumptions, stated so they can be changed:** idle cash costs the funding rate (10 % a year) plus 2 % a year for
# insurance and security, so Co ≈ 0.12 / 365 per USD per day; a stock-out costs an emergency cash-in-transit run and a
# lost customer interaction, set at Cu = 0.02 per USD short. Then q = Cu / (Cu + Co) ≈ 0.98: load the forecast plus the
# 98th percentile of the branch's past forecast errors. The backtest compares this with the rule of thumb "load last
# month's busiest day".

# %%
Co = 0.12 / 365
Cu = 0.02
q_star = g.newsvendor_quantile(Cu, Co)
# the loading forecast and its errors come from one method, known at each origin: the 28-day average lagged 7 days
MA = pd.DataFrame(Yv).shift(7).rolling(28).mean().to_numpy()
RESID = Yv - MA
pol = []
for q in [0.80, 0.90, 0.95, q_star, 0.995]:
    held, short, served = [], [], []
    for o in origins:
        buf = np.nanquantile(RESID[o - 182 : o], q, axis=0)  # each branch's own past errors
        load = np.clip(MA[o : o + H] + buf, 0, None)
        dem = Yv[o : o + H]
        held.append(np.clip(load - dem, 0, None).sum())
        short.append(np.clip(dem - load, 0, None).sum())
        served.append((dem <= load).mean())
    pol.append(
        {
            "policy": f"28-day average + q{q:.3f} buffer",
            "service level %": 100 * np.mean(served),
            "idle cash USD·days": np.sum(held),
            "shortfall USD": np.sum(short),
        }
    )
held, short, served = [], [], []
for o in origins:
    load = np.tile(Yv[o - 28 : o].max(axis=0), (H, 1))
    dem = Yv[o : o + H]
    held.append(np.clip(load - dem, 0, None).sum())
    short.append(np.clip(dem - load, 0, None).sum())
    served.append((dem <= load).mean())
pol.append(
    {
        "policy": "rule of thumb: last month's busiest day",
        "service level %": 100 * np.mean(served),
        "idle cash USD·days": np.sum(held),
        "shortfall USD": np.sum(short),
    }
)
pol = pd.DataFrame(pol)
pol["total cost (USD)"] = pol["idle cash USD·days"] * Co + pol["shortfall USD"] * Cu
show(pol.round(2), paging=False)
opt = pol.iloc[3]
rot = pol.iloc[-1]
display(
    Markdown(
        f"**At the cost-optimal service level ({100 * q_star:.1f} %), the forecast-plus-buffer policy serves "
        f"{opt['service level %']:.1f} % of branch-days and holds {opt['idle cash USD·days'] / rot['idle cash USD·days'] - 1:+.0%} "
        f"idle cash against the rule of thumb ({rot['service level %']:.1f} % served); total cost "
        f"{opt['total cost (USD)']:,.0f} against {rot['total cost (USD)']:,.0f} USD over the backtest.** "
        "The saving comes from sizing each branch's buffer to its own error distribution instead of to its worst day; "
        "the forecast model matters less than the buffer rule (the simplest smoother is enough)."
    )
)
cash = pd.concat(
    [fs.assign(table="forecast"), hier.assign(table="hierarchy"), pol.assign(table="policy")]
)
cash.to_csv(OUT / "granularity_cash.csv", index=False)
sig = pd.DataFrame(
    [
        g.forecast_row(
            "branch × day",
            "cash withdrawn (USD)",
            best.model,
            best["median branch MASE"],
            naive_m,
            best["DM p"],
            note="median MASE over 350 branches",
        )
    ]
).reindex(columns=g.TARGET_COLUMNS)
sig.to_csv(OUT / "granularity_targets_branch.csv", index=False)

# %% [markdown]
# ## Findings, decisions and what they mean downstream
# * **Business problem solved at this grain: cash loading.** A transparent **cash planner** (market forecast, branch
#   shares, a per-branch buffer from the newsvendor quantile) answers treasury's daily question with a measurable
#   cost; it is a deterministic service, not a learned model, and an agent can explain each load ("Branch X: forecast
#   4,200, buffer 2,900 for a 98 % service level").
# * **KPIs:** service level (share of branch-days without a stock-out), idle cash (USD·days), emergency runs, forecast
#   MASE per branch, the cost per USD dispensed.
# * **What the data cannot tell:** real cash demand has paydays, holidays and month ends; none moves this data
#   (notebook 04). The cost parameters are assumptions to be replaced by treasury's actual funding and CIT costs.
# * **Downstream:** `fct_branch_day` is 374 k rows over three years, cheap to build daily; the planner reads it after
#   the day closes. Small cells (a branch-day with one withdrawal) identify individuals' behaviour: serve branch-day
#   figures internally only, and aggregate before any external release.

# %%
pl.close()
print(f"notebook time {time.time() - t0:.0f}s")
