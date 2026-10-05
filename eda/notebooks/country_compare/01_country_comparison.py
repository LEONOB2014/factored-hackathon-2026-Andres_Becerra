# %% [markdown]
# # 01 · Mexico, Colombia and Argentina side by side
# **Country comparison** · the three country series (`notebooks/country_mx`, `country_co`, `country_ar`) read
# together
#
# Each country series rebuilt the whole platform on one country and took its decisions on that country's data. This
# notebook puts the results next to each other to separate what is **common** (a property of the bank, the platform
# or the generator) from what is **national** (currency, calendar, regulation, mix). Inputs: only the summary tables
# each series wrote to `eda/reports/tables/country_*.csv` (no lakehouse is needed), with the whole-bank scope
# (`notebooks/country_all`) as the reference column.

# %%
import sys
from pathlib import Path

sys.path.insert(0, "../../src")
import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from itables import show

from latam_eda import country, theme

theme.register()
T = Path("../../reports/tables")
CODES = ["MX", "CO", "AR"]
NAME = {c: country.COUNTRIES[c].name for c in CODES} | {"ALL": "whole bank"}


def read(kind: str, codes: list[str] = CODES) -> pd.DataFrame:
    return pd.concat(
        [pd.read_csv(T / f"country_{c.lower()}_{kind}.csv").assign(country=c) for c in codes],
        ignore_index=True,
    )


# %% [markdown]
# ## 1 · Three banks in one dataset

# %%
size = read("profile", [*CODES, "ALL"]).assign(country=lambda d: d.country.map(NAME))
show(size.drop(columns="dataset").set_index("country").T, paging=False)

# %% [markdown]
# ## 2 · The contract: one blend, three populations

# %%
ctr = read("contract")
show(ctr, paging=False)
fig = px.bar(
    ctr.assign(country=ctr.country.map(NAME)),
    x="country",
    y=["partitions_held_global_contract", "partitions_held_country_contract"],
    barmode="group",
    title="Partitions the circuit breaker holds: global contract against country contract",
)
fig.update_layout(height=320, xaxis_title=None, legend_title=None)
fig.show()

# %% [markdown]
# ## 3 · What the calendar explains in each country

# %%
cal = read("calendar_effects")
keep = {
    "C(iso_weekday)[T.6]": "Saturday",
    "C(iso_weekday)[T.7]": "Sunday",
    "is_holiday": "holiday",
    "is_long_weekend": "long weekend",
    "payday_window": "payday window",
    "is_month_end": "month end",
    "is_bonus_month": "bonus month",
    "t": "trend per year",
}
cal = cal[cal.term.isin(keep)].assign(
    effect=lambda d: d.term.map(keep), country=lambda d: d.country.map(NAME)
)
cal["lo"] = 100 * (np.exp(cal.ci_low) - 1)
cal["hi"] = 100 * (np.exp(cal.ci_high) - 1)
fig = go.Figure()
for c in cal.country.unique():
    d = cal[cal.country == c]
    fig.add_trace(
        go.Scatter(
            x=d["effect %"],
            y=d.effect,
            mode="markers",
            name=c,
            error_x=dict(
                type="data",
                symmetric=False,
                array=d.hi - d["effect %"],
                arrayminus=d["effect %"] - d.lo,
            ),
        )
    )
fig.add_vline(x=0, line_dash="dot")
fig.update_layout(
    title="Calendar effects on daily volume (%, 95 % CI)", height=420, yaxis_title=None
)
fig.show()
show(cal.pivot_table(index="effect", columns="country", values="effect %"), paging=False)

# %% [markdown]
# ## 4 · Integrity rules by country

# %%
slo = read("rule_slo")
heat = slo.pivot_table(index="rule_id", columns="country", values="country_rate_pct").rename(
    columns=NAME
)
heat["whole bank"] = read("rule_slo", ["ALL"]).set_index("rule_id").country_rate_pct
heat["SLO baseline"] = slo.groupby("rule_id").global_baseline_pct.first()
fig = px.imshow(
    heat.round(1),
    text_auto=True,
    aspect="auto",
    color_continuous_scale="Blues",
    title="Rule violation rate (%) per country and bank-wide",
)
fig.update_layout(height=640)
fig.show()

# %% [markdown]
# ## 5 · Anomalies

# %%
show(read("anomalies").assign(country=lambda d: d.country.map(NAME)), paging=False)

# %% [markdown]
# ## 6 · Learnability of the candidate targets

# %%
lrn = read("learnability").assign(country=lambda d: d.country.map(NAME))
fig = go.Figure()
for c in lrn.country.unique():
    d = lrn[(lrn.country == c) & np.isfinite(lrn.auc)]
    fig.add_trace(
        go.Scatter(
            x=d.auc,
            y=d.name,
            mode="markers",
            name=c,
            marker=dict(size=9),
            error_x=dict(
                type="data", symmetric=False, array=d.auc_hi - d.auc, arrayminus=d.auc - d.auc_lo
            ),
        )
    )
fig.add_vline(x=0.5, line_dash="dot")
fig.update_layout(
    title="Out-of-time test AUC per target and country (95 % CI)",
    height=460,
    yaxis_title=None,
    xaxis_range=[0.3, 1.0],
)
fig.show()
show(
    lrn.pivot_table(index="name", columns="country", values="verdict", aggfunc="first"),
    paging=False,
)
show(lrn.pivot_table(index="name", columns="country", values="ap_lift").round(2), paging=False)

# %% [markdown]
# ## 7 · Synthesis
# ### What is common: the generator draws one bank and relabels it three times
# * **Behaviour is identical.** 0.79–0.80 transactions per customer-month, a median transaction of 466–467 USD and a
#   median income of 2,280–2,304 USD in every country; weekends 39 % below weekdays in every country, measured on the
#   delivery day (`process_date`, the timestamp −6 h in every market; ADR-014); **no** holiday, payday, month-end,
#   long-weekend or bonus-month effect significant at 1 % anywhere; no abnormal day, no change point and a largest
#   monthly PSI below 0.005 in three years. The countries differ in labels (currency, calendar, regulator), not in
#   behaviour. Pooled over the whole bank (`country_all`), the three days after a payday come out 1.3 % quieter
#   (p = 0.03, not significant at 1 %), and the backup shows no such dip (`dataset_compare`). Measured on each
#   country's legal time instead, Colombia's and Argentina's weekends looked weaker and Argentine Mondays looked about
#   7 % quieter: both were artefacts of the wrong clock (`granularity_time/01`), and no national pattern remains.
# * **The learnability map is identical.** In all three countries, out of time:
#   * **dormancy in the next 90 days is learnable** (AUC 0.72–0.73, AP about 1.9× the base rate), but the
#     transaction count of the previous six months **alone** reaches 0.72–0.73: the "model" is the customer's own
#     activity rate. Each customer behaves like a Poisson process with a personal rate, and dormancy is the chance of
#     zero events in 90 days. The right champion is a transparent rate model (a negative-binomial per customer, or the
#     rule "fewer than k transactions in 6 months"), and boosting adds nothing measurable;
#   * **campaign conversion is weak** (AUC 0.63–0.64, AP 1.4–1.5× base) and comes from the channel × segment
#     interaction (the model adds about 0.08 over the best single feature): a contact rule by channel, not a model;
#   * **fraud, complaint in 90 days, delinquency and contact escalation show no evidence of signal**; the leaking
#     `fraud_score` alone reaches 0.82–0.86, the control that proves the protocol finds signal when it exists.
# * **The pipeline defects are bank-wide**: NULL-token supernode, first-version SCD2 validity, eligibility built before
#   its features, dispute candidates discarded, dead peer typology. They are in the code, so they are in every country.
# * **R25 is a uniform random draw.** The share of complaints whose wrong product is still a same-country product is
#   13 % in Argentina, 20 % in Colombia and 33 % in Mexico: exactly 66.4 % × each country's share of the bank's products
#   (20 %, 30 %, 50 %). The "affected product" was drawn at random from all products, so it carries no information at
#   all; R26 behaves the same way.
#
# ### What is national, and must be configured per country
# * **Currency.** Mexico's accounts are all in USD; Colombia's and Argentina's are 90 % in pesos. The typical amount is
#   0.09× (Mexico), 307× (Colombia) and 27× (Argentina) the blended contract baseline, so **the bank-wide contract
#   would hold every transaction day of every country** (1,097 of 1,097). Country baselines on a 180-day reference
#   window hold none. Production must key contracts by (table, country), or scale checks by currency.
# * **Rule rates.** R17 is a Mexican rule (100 % there, 0 % elsewhere); R18 (imputed USD) exists only where pesos do
#   (4.5 % in Colombia and Argentina, 0 % in Mexico); anonymous digital traffic is 19 % / 26 % / 33 % (Mexico /
#   Colombia / Argentina) of events. A bank-wide SLO describes no country: **SLOs per country**, zero-tolerance policies
#   shared.
# * **Regulation.** AML reporting lines (USD 7,500 in cash in Mexico, COP 10 million in cash in Colombia, an
#   inflation-indexed UIF threshold in Argentina), complaint deadlines (CONDUSEF, SFC, BCRA) and marketing-consent law
#   (LFPDPPP and REUS, Ley 1581, Ley 25.326 and No Llame) are national: they belong in compliance-owned seeds per country.
# * **Calendar.** Mexico has 7 statutory holidays plus 4 bank closures, Colombia 17–18, Argentina about 20 (with
#   bridge "feriados puente"). The data does not react to any of them, but real data will: the calendar enrichment
#   stays, and its effects become the first thing to re-measure on real data.
# * **Scale for statistics.** Validation periods hold 320 frauds in Mexico, 209 in Colombia and 147 in Argentina: country-level
#   supervised models, when labels exist, will be feasible first in Mexico; small countries need pooled models with a
#   country feature, or coarser DP releases (notebook 11).
#
# ### Decisions taken, and what they mean for the next stages
# 1. **Country-aware platform, one code base**: contracts, SLOs, AML lines, deadlines and calendars become
#    country-keyed seeds; the dbt models stay the same. The series proves it works: the same compiled SQL ran three times.
# 2. **Gates per country**: one country's data must never block another's run; the drift and quality gates are
#    evaluated per (table, country).
# 3. **First model to build: dormancy**, as a transparent per-customer rate model with a one-feature rule as the
#    benchmark it must beat; monitor it with AP on recent quarters and the PSI of its inputs.
# 4. **Campaigns: a channel rule and a randomised holdout** per country, before any uplift work.
# 5. **Fraud, complaints, delinquency, escalation: rules and data collection**, not models: confirmed fraud labels,
#    real transcripts and complaint–contact keys, and days-past-due history from the SCD2 snapshots.
# 6. **Fix the bank-wide pipeline defects once**: every country benefits from each fix.
