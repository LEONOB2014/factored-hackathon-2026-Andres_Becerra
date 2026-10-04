# %% [markdown]
# # 13 · Anomalies and change points (All countries)
# **Country series · All countries** · *an additional component of the series; generated from
# `notebooks/country_template`: edit the template*
#
# Three levels of "unusual", each with the method that suits it:
# 1. **Days**: is any day's volume abnormal once the weekly and calendar pattern is removed? (regression residuals,
#    robust z-scores)
# 2. **Periods**: did the level of activity change at some date? (change-point detection with a penalised cost)
# 3. **Customers and transactions**: which customer-months look unlike the rest, and do they agree with the AML
#    rules? (Isolation Forest on the monthly grid; robust z-scores of amounts per currency)

# %%
import sys
import time
from pathlib import Path

sys.path.insert(0, "../../src")
import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import ruptures as rpt
import statsmodels.formula.api as smf
from IPython.display import Markdown, display
from itables import show
from sklearn.ensemble import IsolationForest

from latam_eda import country, theme

COUNTRY = "ALL"
DATASET = "main"
PREFIX = "country"
CTRY = country.SCOPES[COUNTRY]
OUT = Path("../../reports/tables")
OUT.mkdir(parents=True, exist_ok=True)
theme.register()
t0 = time.time()
pl = country.session(COUNTRY, DATASET)
country.prepare(pl, "gold")
country.enrich_transactions(pl)

# %% [markdown]
# ## 1 · Abnormal days
# Daily transaction counts (local date) are modelled as in notebook 04 (weekday, holiday, long weekend, payday window,
# month end, trend; OLS on log counts). A day is abnormal when its residual is more than 4 robust standard deviations
# (1.4826 × MAD) from zero: robust, because the abnormal days themselves must not inflate the yardstick.

# %%
daily = pl.q("""
    select k.country_code, t.local_date, count(*) as n_tx, sum(t.amount_usd) as usd,
           any_value(k.iso_weekday) as iso_weekday,
           any_value(k.is_holiday::int) as is_holiday, any_value(k.is_long_weekend::int) as is_long_weekend,
           any_value((coalesce(k.days_since_payday, 99) <= 2)::int) as payday_window,
           any_value(k.is_month_end::int) as is_month_end, any_value(k.holiday_name) as holiday_name
    from main.tx_local t join main.calendar_local k
      on k.country_code = t.customer_country_code and k.local_date = t.local_date
    group by 1, 2 order by 1, 2""")
daily["local_date"] = pd.to_datetime(daily.local_date)
daily = country.full_months(daily)
FE = " + C(country_code)" if daily.country_code.nunique() > 1 else ""
daily["log_n"] = np.log(daily.n_tx)
daily["t"] = (daily.local_date - daily.local_date.min()).dt.days / 365.25
m = smf.ols(
    "log_n ~ C(iso_weekday) + is_holiday + is_long_weekend + payday_window + is_month_end + t" + FE,
    data=daily,
).fit()
daily["resid"] = m.resid
mad = 1.4826 * np.median(np.abs(daily.resid - daily.resid.median()))
daily["z"] = (daily.resid - daily.resid.median()) / mad
out = daily[daily.z.abs() > 4]
fig = go.Figure()
fig.add_trace(
    go.Scatter(
        x=daily.local_date,
        y=daily.z,
        mode="lines",
        name="robust z of the residual",
        line=dict(width=1),
    )
)
fig.add_trace(
    go.Scatter(x=out.local_date, y=out.z, mode="markers", name="|z| > 4", marker=dict(size=8))
)
fig.add_hline(y=4, line_dash="dot")
fig.add_hline(y=-4, line_dash="dot")
fig.update_layout(
    title=f"{CTRY.title}: daily volume after removing the calendar (robust z)",
    height=340,
    xaxis_title=None,
)
fig.show()
show(
    out[["country_code", "local_date", "n_tx", "iso_weekday", "holiday_name"]].assign(
        z=out.z.round(2)
    ),
    paging=False,
)
display(
    Markdown(
        f"**{len(out)} abnormal days in {len(daily):,}** (a normal distribution would give about "
        f"{len(daily) * 6.3e-5:.2f} beyond 4σ). "
        + (
            "None: once weekdays are removed, daily volume is pure noise around a flat level, another sign of a generator "
            "with no shocks (no outages, no payroll days, no Hot Sale or Buen Fin)."
            if not len(out)
            else "Inspect them: a real day like this is an outage, a campaign or a data delivery problem."
        )
    )
)

# %% [markdown]
# ## 2 · Change points in the level of activity
# **Method.** PELT (pruned exact linear time) on the weekly mean of the calendar-adjusted log volume, with an RBF cost
# and a penalty of 3·log(n) (BIC-like): it finds the dates where the series' level shifts, and the penalty decides how
# much shift is worth a break. Weekly aggregation removes the daily noise that would otherwise force many small breaks.

# %%
wk = daily.set_index("local_date").resid.resample("W").mean().dropna()
algo = rpt.Pelt(model="rbf", min_size=6).fit(wk.to_numpy().reshape(-1, 1))
bkps = algo.predict(pen=3 * np.log(len(wk)))
dates = [wk.index[b - 1] for b in bkps[:-1]]
fig = px.line(
    x=wk.index,
    y=wk.values,
    title=f"{CTRY.title}: weekly calendar-adjusted log volume and change points",
)
for d in dates:
    fig.add_vline(x=d, line_dash="dash")
fig.update_layout(height=320, xaxis_title=None, yaxis_title="residual (log)")
fig.show()
display(
    Markdown(
        f"**{len(dates)} change point(s)** "
        + (
            f"at {', '.join(str(d.date()) for d in dates)}."
            if dates
            else f"in {len(wk)} weeks: the level of activity never shifts."
        )
    )
)

# %% [markdown]
# ## 3 · Amount outliers, per currency and transaction type
# A robust z-score of log(amount) inside each (currency, transaction type): the scale of a peso purchase and a dollar
# transfer differ, so a single threshold would flag a currency, not an outlier.

# %%
amt = pl.q("""
    with x as (select currency, transaction_type, is_fraud, ln(greatest(amount, 0.01)) as la from main.tx_local),
    med as (select currency, transaction_type, median(la) as med from x group by 1, 2),
    s as (select x.currency, x.transaction_type, any_value(med.med) as med, median(abs(x.la - med.med)) as mad
          from x join med using (currency, transaction_type) group by 1, 2),
    z as (select x.*, (x.la - s.med) / nullif(1.4826 * s.mad, 0) as rz from x join s using (currency, transaction_type))
    select currency, transaction_type, count(*) as transactions,
           count(*) filter (where rz > 4.5) as high_outliers, count(*) filter (where rz < -4.5) as low_outliers,
           round(100 * avg(is_fraud::int) filter (where abs(rz) > 4.5), 3) as fraud_pct_among_outliers
    from z group by all order by 1, 2""")
amt["beyond_4_5_sd"] = amt.high_outliers + amt.low_outliers
amt["share %"] = (100 * amt.beyond_4_5_sd / amt.transactions).round(3)
show(amt, paging=False)
hi, lo = int(amt.high_outliers.sum()), int(amt.low_outliers.sum())
display(
    Markdown(
        f"**{hi:,} high and {lo:,} low outliers beyond 4.5 robust standard deviations "
        f"({100 * (hi + lo) / amt.transactions.sum():.3f} % of transactions).** "
        + (
            "They are almost all on the **low** side: the smallest amounts of a type (a floor of small purchases, deposits "
            "and transfers), not large unusual payments. In this data, extreme amounts do not exist above the bulk, which "
            "is why amount-based detectors found only planted spikes in the anomaly benchmark. On real data the low side "
            "matters too: bursts of tiny purchases are the signature of card testing."
            if lo > 2 * hi
            else "High-side outliers dominate: large unusual amounts exist and deserve an amount rule per currency and type."
        )
    )
)

# %% [markdown]
# ## 4 · Unusual customer-months, and agreement with the AML rules
# **Isolation Forest** on the monthly grid: random trees isolate a point in fewer splits the more it differs from the
# rest; the average path length is the anomaly score. Features (log-scaled where skewed): transactions, inflow,
# outflow, cash in and out, cross-border volume, foreign countries, declines for funds, near-threshold and round
# amounts. Only months with activity. The top 0.5 % are compared with the months the AML typologies flagged.

# %%
cm = pl.q("""select m.*, coalesce(len(a.typology_hits), 0) > 0 as aml_hit
             from {int_customer_month_tx} m left join {mart_aml_customer_month} a using (customer_id, month_start)
             where m.n_tx > 0""")
F = [
    "n_tx",
    "inflow_usd",
    "outflow_usd",
    "cash_in_usd",
    "cash_out_usd",
    "cross_border_usd",
    "n_foreign_countries",
    "insufficient_funds_declines",
    "near_threshold_tx",
    "round_amount_tx",
    "max_outflow_usd",
]
# a fixed row order: the forest's subsamples are drawn by position, so the database's row order must not matter
cm = cm.sort_values(["customer_id", "month_start"], kind="mergesort").reset_index(drop=True)
X = np.log1p(cm[F].clip(lower=0).astype(float))
iso = IsolationForest(n_estimators=300, max_samples=4096, random_state=7).fit(X)
cm["score"] = -iso.score_samples(X)
k = int(0.005 * len(cm))
top = cm.nlargest(k, "score")
prec = top.aml_hit.mean()
base = cm.aml_hit.mean()
show(
    pd.DataFrame(
        {
            "customer-months": [len(cm)],
            "flagged by the forest (top 0.5 %)": [k],
            "AML hit rate overall %": [round(100 * base, 2)],
            "AML hit rate in the top 0.5 % %": [round(100 * prec, 2)],
            "enrichment ×": [round(prec / base, 1) if base else np.nan],
        }
    ),
    paging=False,
)
pd.DataFrame(
    [
        {
            "country": COUNTRY,
            "dataset": DATASET,
            "days": len(daily),
            "abnormal_days": len(out),
            "change_points": len(dates),
            "amount_outlier_share_pct": round(
                100 * amt.beyond_4_5_sd.sum() / amt.transactions.sum(), 4
            ),
            "forest_top_aml_rate_pct": round(100 * prec, 2),
            "aml_rate_overall_pct": round(100 * base, 2),
            "enrichment": round(prec / base, 2) if base else np.nan,
        }
    ]
).to_csv(OUT / f"{PREFIX}_{COUNTRY.lower()}_anomalies.csv", index=False)
prof = pd.concat(
    [cm[F].median().rename("all months (median)"), top[F].median().rename("top 0.5 % (median)")],
    axis=1,
)
show(prof.round(1), paging=False)
display(
    Markdown(
        f"**The unsupervised forest and the AML rules agree {prec / base:.1f}× more than chance** (AML hit rate "
        f"{100 * prec:.1f} % in the forest's top 0.5 % against {100 * base:.1f} % overall). "
        "Agreement means both see the same unusual volume; disagreement is the interesting part: forest-only months are "
        "unusual without matching a typology (candidates for a new rule), rule-only months match a typology without being "
        "unusual (candidates for a threshold review). This is the analyst queue a monitoring system should start from."
    )
)

# %% [markdown]
# ## Findings for All countries and what to do
# The computed statements above. Method decisions for every country: remove the calendar before judging a day, judge
# amounts within currency and type, use robust scales, and pair rules with an unsupervised score so each checks the
# other.

# %%
pl.close()
print(f"notebook time {time.time() - t0:.0f}s")
