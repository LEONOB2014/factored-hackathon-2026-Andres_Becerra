# %% [markdown]
# # 02 · The customer at the hour
# **Granularity series III · the bank at the hour** · grains: customer × daypart (`agg.fct_customer_daypart`), each
# customer's transactions in hours
#
# **Stakeholders.** CRM and digital product (when to reach a customer, which customers are "evening" or "night" users),
# retention (does a change in a customer's rhythm signal disengagement), fraud (a transaction at an hour the customer
# never uses).
#
# **Questions.**
# 1. **Does a customer have a preferred hour?** For each customer with at least 30 transactions, a χ² of their 24 hourly
#    counts against a flat profile. Without preferences, about 1 % of customers reject at the 1 % level by chance.
# 2. **The daypart profile as a mini-dimension.** Each customer's shares over night, morning, afternoon and evening,
#    banded (spread, or concentrated in one daypart), compared with what multinomial noise alone would produce.
# 3. **Hourly recency.** The hours between consecutive transactions, against the exponential law of a Poisson customer.
# 4. **Models, executed whatever the signal** (`latam_eda.hour_models.customer`): dormancy in the next 90 days from the
#    time-of-day profile against the six-month count, and the daypart of each customer's next transaction from their own
#    shrunk profile against the bank's shares. Each ends in a readiness gate (notebook 08).

# %%
import sys
import time
import warnings
from pathlib import Path

sys.path.insert(0, "../../src")
import numpy as np
import pandas as pd
import plotly.express as px
from IPython.display import Markdown, display
from itables import show
from scipy import stats

from latam_eda import country, theme
from latam_eda import granularity as g
from latam_eda import hour_models as hm

warnings.filterwarnings("ignore")
OUT = Path("../../reports/tables")
theme.register()
t0 = time.time()
pl = country.session("ALL", "main")
country.prepare(pl, "gold")
star = g.open_star(pl, [g.SQL_DIR_TIME, g.SQL_DIR_HOUR])
star.build(["fct_customer_daypart"], verbose=False)
tests = []

# %% [markdown]
# ## 1 · Does a customer have a preferred hour?

# %%
ch = star.q("""select customer_id, hour(transaction_ts_utc - interval 6 hour) as h, count(*) as n
               from {int_transactions_enriched} group by all order by customer_id, h""")
pv = ch.pivot_table(index="customer_id", columns="h", values="n", fill_value=0)
pv = pv[pv.sum(axis=1) >= 30]
e = pv.sum(axis=1).to_numpy()[:, None] / 24
chi = ((pv.to_numpy() - e) ** 2 / e).sum(axis=1)
p_cust = stats.chi2.sf(chi, 23)
rej = int((p_cust < 0.01).sum())
bt = stats.binomtest(rej, len(p_cust), 0.01, alternative="greater")
tests.append(
    {
        "scenario": "02 customer",
        "test": "customers with a preferred hour (share rejecting flat at 1 %)",
        "statistic": rej / len(p_cust),
        "p_value": bt.pvalue,
        "effect": rej / len(p_cust) - 0.01,
        "n": len(p_cust),
        "reading": "preferences exist" if bt.pvalue < 0.01 else "no more than chance",
    }
)
cnt, edges = np.histogram(p_cust, bins=20, range=(0, 1))
fig = px.bar(
    x=(edges[:-1] + edges[1:]) / 2,
    y=cnt,
    title="Per-customer p-values of 'hours are flat' (uniform = no preferences)",
)
fig.update_layout(height=300, xaxis_title="p-value", yaxis_title="customers")
fig.show()
display(
    Markdown(
        f"**{100 * rej / len(p_cust):.2f} % of {len(p_cust):,} customers reject a flat hourly profile at 1 %** "
        f"(1 % expected by chance; binomial p = {bt.pvalue:.2g}). The p-values are "
        + (
            "uniform: no customer has a preferred hour, so 'reach the customer at their hour' and 'an unusual hour "
            "for this customer' have nothing to learn from."
            if bt.pvalue > 0.01
            else "skewed towards zero: some customers have preferred hours."
        )
    )
)

# %% [markdown]
# ## 2 · The daypart profile as a mini-dimension
# Each customer's share of transactions in their busiest daypart. With 4 equally likely dayparts and n transactions,
# multinomial noise alone produces a maximum share above 1/4; the comparison is against a simulation of the same
# customers with flat hours.

# %%
dp = star.q(
    "select customer_id, daypart, n_tx from {fct_customer_daypart} order by customer_id, daypart"
)
w = dp.pivot_table(index="customer_id", columns="daypart", values="n_tx", fill_value=0)
w = w[w.sum(axis=1) >= 20]
maxshare = (w.max(axis=1) / w.sum(axis=1)).to_numpy()
rng = np.random.default_rng(2)
sim = rng.multinomial(w.sum(axis=1).to_numpy().astype(np.int64), [0.25] * 4)
simshare = sim.max(axis=1) / sim.sum(axis=1)
ks = stats.ks_2samp(maxshare, simshare)
bands = pd.cut(
    maxshare, [0, 0.35, 0.5, 1], labels=["spread", "leaning (35–50 %)", "concentrated (> 50 %)"]
)
band_tab = pd.DataFrame(
    {
        "observed customers": pd.Series(bands).value_counts().sort_index(),
        "under flat hours": pd.Series(pd.cut(simshare, [0, 0.35, 0.5, 1], labels=bands.categories))
        .value_counts()
        .sort_index(),
    }
)
show(band_tab, paging=False)
tests.append(
    {
        "scenario": "02 customer",
        "test": "daypart concentration vs flat-hours simulation (KS)",
        "statistic": ks.statistic,
        "p_value": ks.pvalue,
        "effect": float(np.mean(maxshare) - np.mean(simshare)),
        "n": len(maxshare),
        "reading": "profiles beyond noise"
        if ks.pvalue < 0.01
        else "profiles are multinomial noise",
    }
)
display(
    Markdown(
        f"**The busiest daypart holds {100 * np.mean(maxshare):.1f} % of a customer's transactions on average, against "
        f"{100 * np.mean(simshare):.1f} % under flat hours (KS p = {ks.pvalue:.2g}).** "
        + (
            "The bands a CRM would label 'evening' or 'night' customers are what chance gives: a time-of-day "
            "mini-dimension would store noise. The structure is kept (the fact and its bands are cheap) so that real "
            "data can fill it."
            if ks.pvalue > 0.01
            else "Customers concentrate in dayparts beyond chance: a time-of-day band is a real attribute."
        )
    )
)

# %% [markdown]
# ## 3 · Recency in hours

# %%
gaps = star.q("""with x as (select customer_id, epoch(transaction_ts_utc - lag(transaction_ts_utc)
                     over (partition by customer_id order by transaction_ts_utc, transaction_id)) / 3600.0 as gap_h
                   from {int_transactions_enriched})
                 select gap_h from x where gap_h is not null""").gap_h.to_numpy()
rate = 1 / gaps.mean()
q = np.quantile(gaps, [0.1, 0.25, 0.5, 0.75, 0.9])
qe = stats.expon.ppf([0.1, 0.25, 0.5, 0.75, 0.9], scale=gaps.mean())
rec = pd.DataFrame(
    {"quantile": [0.1, 0.25, 0.5, 0.75, 0.9], "observed hours": q, "pooled exponential hours": qe}
)
show(rec.round(1), paging=False)
display(
    Markdown(
        f"**The median gap between a customer's transactions is {q[2]:,.0f} hours ({q[2] / 24:.0f} days).** The pooled "
        "distribution is wider than one exponential because customers differ in rate (a mixture of exponentials, the "
        "exposure law of series I); each customer is a Poisson process (series II, notebook 03). At the hour grain, "
        "recency is just the customer's rate expressed in hours."
    )
)

# %% [markdown]
# ## 4 · The models, executed

# %%
rows, detail = hm.customer(star)
sc = pd.DataFrame(rows)
show(
    sc[
        [
            "model",
            "metric",
            "value",
            "benchmark",
            "benchmark_value",
            "delta",
            "delta_lo",
            "delta_hi",
            "mde",
            "verdict",
            "root_cause",
        ]
    ].round(4),
    paging=False,
)
pd.DataFrame(tests).to_csv(OUT / "granularity_hour_customer_profile.csv", index=False)
display(
    Markdown(
        "**Readiness:** "
        + "; ".join(
            f"*{r['model']}* is **{r['verdict']}** ({r['root_cause'] or 'ready'})" for r in rows
        )
        + f". Dormancy (base rate {100 * detail['dormancy_base_rate']:.1f} %) is predicted by the six-month count "
        "alone; adding the time-of-day profile and hourly recency changes nothing. A customer's own daypart history "
        "predicts their next daypart worse than the bank's shares: the profile is noise, and shrinking it towards the "
        "bank only limits the damage."
    )
)

# %% [markdown]
# ## What this means downstream
# * **No customer time-of-day attribute** belongs in the customer dimension on this data; `fct_customer_daypart` stays
#   as an aggregate (cheap, reconciled) so the same pipeline measures real habits when they exist.
# * **Fraud and CRM:** "unusual hour for this customer" and "best hour to contact" need customers with habits, which
#   needs true local timestamps (ADR-014) and activity from every channel of the same customer (notebook 08).

# %%
pl.close()
print(f"notebook time {time.time() - t0:.0f}s")
