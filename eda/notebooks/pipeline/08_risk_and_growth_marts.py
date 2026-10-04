# %% [markdown]
# # 08 · Risk and growth marts: credit, collections, AML, campaigns
# **Pipeline series** · task group `gold`, part 3: the marts of bundles B2 (financial crime), B3 (credit lifecycle)
# and B4 (responsible growth)
#
# ## What these marts are
# Each one turns policy into **transparent rules with reason codes**: no model yet, because the data cannot train one
# (the atlas explains why). Rules are the right first release in regulated decisions: every outcome has a reason a
# customer, an auditor and a regulator can read, and the logged outcomes become the labels a later model needs.
#
# | mart | grain | rules |
# |---|---|---|
# | `mart_credit_eligibility` | customer | 7 adverse-action reasons + score cut-offs → eligible for card / loan |
# | `mart_collections_early_warning` | credit product | a 0–100 additive early-warning score |
# | `mart_aml_customer_month` | customer × month | 6 typologies + robust peer deviations |
# | `mart_campaign_compliance_uplift` | send | consent at send, contact pressure, product already held, treatment and outcome |
#
# All thresholds are **illustrative policy parameters** written as Jinja variables at the top of each model. In a
# bank they would come from the credit, collections and AML policies, owned and signed off by those functions.

# %%
import sys
import time

sys.path.insert(0, "../../src")
import ipywidgets as w
import pandas as pd
import plotly.express as px
from IPython.display import Markdown, display
from itables import show

from latam_eda import pipeline as pipe
from latam_eda import theme

theme.register()
t0 = time.time()
pl = pipe.session()
pl.ensure_until("snapshots")
MARTS = [
    "mart_credit_eligibility",
    "mart_collections_early_warning",
    "mart_aml_customer_month",
    "mart_campaign_compliance_uplift",
]
built = pl.build_set(MARTS)
show(built[["node", "rows", "seconds", "pulled_forward"]], paging=False)

# %% [markdown]
# Note `pulled_forward` above: if the feature table `feat_credit_eligibility_pit` had not been built yet, the emulator
# would have built it first and marked it, because **in Airflow this mart runs before its input** (notebook 01).

# %% [markdown]
# ## 1 · `mart_credit_eligibility`: reason codes first
# The mart reads the point-in-time credit features of the latest month-end and lists every reason that blocks credit:
#
# | code | rule |
# |---|---|
# | R01 | customer not active |
# | R02 | any product more than 30 days past due |
# | R03 | no credit score |
# | R04 | fewer than 3 months with inflows in the last 6 |
# | R05 | payments above 40 % of average inflows (3 months) |
# | R06 | 3+ insufficient-funds declines in 3 months |
# | R07 | tenure under 180 days |
#
# Then card eligibility needs no reason and a score ≥ 650 (and no card yet); loan eligibility needs no reason and a
# score ≥ 680.

# %%
el = pl.q("""select count(*) as customers, count(*) filter (where eligible_credit_card) as eligible_card,
                    count(*) filter (where eligible_personal_loan) as eligible_loan,
                    count(*) filter (where len(decline_reasons) = 0) as no_adverse_reason
             from {mart_credit_eligibility}""")
show(el, paging=False)
reasons = pl.q("""select r as reason, count(*) as customers
                  from (select unnest(decline_reasons) as r from {mart_credit_eligibility}) group by 1 order by 2 desc""")
fig = px.bar(
    reasons,
    x="customers",
    y="reason",
    orientation="h",
    title="Adverse-action reasons (a customer can have several)",
)
fig.update_layout(height=320, yaxis_title=None, yaxis=dict(autorange="reversed"))
fig.show()
nr = pl.q(
    "select len(decline_reasons) as reasons, count(*) as customers from {mart_credit_eligibility} group by 1 order by 1"
)
show(nr, paging=False)

# %% [markdown]
# **Reading.** 96.5 % of customers fail **R04** (fewer than 3 months with inflows in 6), which is notebook 05's thin
# monthly grid seen from the credit side. Only 2,823 customers have no adverse reason, and after the score cut-offs
# **649 are eligible for a card and 835 for a loan** out of 150,000.
#
# **Is the policy wrong or the data thin?** The data. R04 is a standard income-stability rule. With 0.8 transactions a
# month and only deposits counted as inflows (the direction assumption, notebook 05), almost nobody can show regular
# income. Do not lower the rule to make the demo look generous: an eligibility demo that approves on thin evidence
# teaches the wrong lesson. Show the reasons instead; that is the product.
#
# **Two caveats from the pipeline.**
# * `credit_score_current` and income are **current state**, not point-in-time (the feature table says so in its
#   column names). Eligibility for *today* is fine; training a model on past months with them would leak the future.
# * This mart is the one with the **ordering defect** (notebook 01): in Airflow it reads the previous run's features.

# %% [markdown]
# ## 2 · `mart_collections_early_warning`: an additive score
# One row per loan and credit card, scored 0–100 by transparent terms: +25 if 1–30 days past due, +40 if more than 30,
# +15 if utilisation ≥ 90 %, +10 for repeated insufficient-funds declines, +10 if payments fell below half their
# average, +10 if the last payment is more than 45 days old **or unknown** (`coalesce(…, true)`).

# %%
ews = pl.q("""select coalesce(dpd_bucket, '(none)') as dpd_bucket, count(*) as products,
                     round(avg(early_warning_score), 1) as avg_score
              from {mart_collections_early_warning} group by 1 order by 1""")
show(ews, paging=False)
sc = pl.q(
    "select early_warning_score, count(*) as products from {mart_collections_early_warning} group by 1 order by 1"
)
fig = px.bar(sc, x="early_warning_score", y="products", title="Early-warning score distribution")
fig.update_layout(height=300)
fig.show()

# %% [markdown]
# **Reading.** The score is dominated by two terms. **Days past due** separates the buckets (≈10 current, 35 at 1–30,
# 50 beyond). **"No payment in 45 days or unknown"** gives 10 points to almost every current product (94,787 products
# score exactly 10): with 0.8 transactions a month, most products have no recent payment, so the term carries little
# information here. Treating *unknown* as risky is the prudent choice in collections (absence of evidence of payment is
# a warning), but it should be a separate flag so an analyst can tell "late" from "never seen".
#
# Products without days past due (`(none)`, 6,622) score like current ones: they are **unknown**, not current, and the
# mart should say so (`dpd_bucket = 'unknown'`) rather than let them blend in.
#
# **What unlocks a model:** history. Roll rates (current → 30 → 60 → 90 days) need a time series of days past due per
# product, which the SCD2 snapshot of products accumulates from the first run onward (notebook 06).

# %% [markdown]
# ## 3 · `mart_aml_customer_month`: typologies on a thin, counterparty-less feed
# One row per customer and month with activity (2.6 M), six typologies:
#
# | typology | rule |
# |---|---|
# | `RAPID_IN_OUT` | inflow and outflow within 10 % of each other and inflow ≥ 10,000 USD |
# | `INFLOW_INCONSISTENT_WITH_INCOME` | monthly inflow ≥ 5 × declared monthly income |
# | `NEAR_THRESHOLD_STRUCTURING` | 2+ transactions of 9,000–9,999 USD in the month |
# | `MULTI_JURISDICTION` | transactions in 3+ foreign countries |
# | `CASH_INTENSIVE` | cash ≥ 80 % of the volume and volume ≥ 10,000 USD |
# | `PEER_OUTLIER_INFLOW` | inflow ≥ 6 robust standard deviations above the peer group (segment × country × month) |

# %%
typ = pl.q("""select t as typology, count(*) as customer_months, count(distinct customer_id) as customers
              from (select customer_id, unnest(typology_hits) as t from {mart_aml_customer_month}) group by 1 order by 2 desc""")
show(typ, paging=False)
show(
    pl.q("""select count(*) as customer_months, round(100 * avg((inflow_usd > 0)::int), 1) as months_with_inflow_pct,
                   count(inflow_robust_z_vs_peers) as months_with_a_defined_peer_z
            from {mart_aml_customer_month}"""),
    paging=False,
)

# %% [markdown]
# **Finding: `PEER_OUTLIER_INFLOW` can never fire.** Only 19 % of active customer-months contain an inflow, so in every
# peer group the median inflow is 0 and the median absolute deviation is 0. The robust z divides by `nullif(MAD, 0)`
# and is NULL for **all 2.6 M rows**. The rule is structurally dead, and nothing reports it, because a typology with
# zero hits looks like good news.
#
# **Recommendation.** Compute peer statistics on the **months with inflow** (the conditional distribution), on a log
# scale (`ln(1 + inflow)`), or replace the z-score by a peer **quantile** rule (inflow above the group's 99.5th
# percentile). Add a test that every typology fires at least once on a planted positive (as the anomaly detectors
# have), so a dead rule fails CI.
#
# **The other typologies, read critically.**
# * `INFLOW_INCONSISTENT_WITH_INCOME` dominates (≈13 k customer-months). Deposits in this data are drawn independently
#   of income, so a large deposit by a low-income customer fires it: plausible as a rule, uninformative as a signal
#   here.
# * `NEAR_THRESHOLD_STRUCTURING` uses a 10,000 USD threshold, the United States' cash-reporting line. The thresholds
#   that matter are Mexico's, Colombia's and Argentina's, in local currency or in UMA, and they differ by product and
#   cash versus non-cash. **Recommendation:** a per-country threshold seed, owned by compliance. And remember notebook
#   05: imputed USD amounts carry ±2 %, enough to move a transaction across the band; flag them.
# * Network typologies (fan-in, fan-out, mule chains) are impossible: transfers have no counterparty.

# %% [markdown]
# ## 4 · `mart_campaign_compliance_uplift`: consent, pressure and a causal question the data cannot answer

# %%
camp = pl.q("""select count(*) as sends, round(100 * avg(sent_without_current_consent::int), 2) as without_consent_pct,
                      round(100 * avg(already_held_promoted_product::int), 2) as already_held_pct,
                      round(avg(prior_sends_30d), 2) as avg_prior_sends_30d, max(prior_sends_30d) as max_prior_sends_30d
               from {mart_campaign_compliance_uplift}""")
show(camp, paging=False)
conv = pl.q("""
    select 'consent' as split, sent_without_current_consent::varchar as value_, count(*) as delivered_sends,
           round(100 * avg(outcome_converted::int), 3) as conversion_pct
    from {mart_campaign_compliance_uplift} where treatment_delivered group by all
    union all
    select 'product already held', already_held_promoted_product::varchar, count(*),
           round(100 * avg(outcome_converted::int), 3)
    from {mart_campaign_compliance_uplift} where treatment_delivered group by all""")
show(conv, paging=False)

# %% [markdown]
# **Reading.**
# * **Half of all sends (50.06 %) went to customers whose current flag says no marketing** (R21). The flag is current
#   state: without consent history the bank cannot prove whether consent existed *at send time*, which is itself a
#   compliance gap. The SCD2 snapshot of customers fixes that going forward (`accepts_marketing` is in the row hash).
# * Customers **without** consent convert at the same rate as those with it (0.60 % against 0.59 %): consent carries no
#   behavioural signal in this data, so suppressing those sends costs nothing measurable. **Recommendation:** a
#   consent gate in the send pipeline, now.
# * **26 % of sends promote a product the customer already holds**, and those sends still record conversions (0.57 %).
#   Conversions are therefore **not attributable** to the promoted product; any uplift estimate built on them is wrong
#   before it starts.
# * There is **no randomised holdout**: every eligible customer could be treated, so treated and untreated customers
#   differ by whatever drove targeting. Uplift is **not identifiable**. **Recommendation:** design a holdout (for
#   example 10 % of each campaign's audience, randomised by a hash of customer id and campaign) before any uplift
#   model.

# %% [markdown]
# ## 5 · The gold task group's tests
# Cosmos runs the gold tests (core and marts, including the mart unit-test fixtures' data counterparts) after the group.

# %%
pl.ensure_until("gold")
tests = pl.run_tests("gold")
show(tests[["test", "attached_to", "severity", "failures", "status"]], paging=False)

# %% [markdown]
# All gold data tests pass. Note what they do **not** cover, from this notebook and the two before: a dead typology
# (zero hits), NULL surrogate keys in `fct_transaction`, dispute candidates discarded by an unowned product. Each
# finding above comes with the test that would have caught it.

# %% [markdown]
# ## 6 · Explorer: rule sensitivity
# Change a policy parameter and see how many customers or customer-months the rule would flag. The queries re-run the
# rule on the mart's own columns.

# %%
w_rule = w.Dropdown(
    options=[
        "credit: minimum months with inflow (of 6)",
        "credit: card score cut-off",
        "AML: inflow / income multiple",
        "AML: structuring band lower bound (USD)",
    ],
    description="rule",
    layout=w.Layout(width="420px"),
)
w_val = w.FloatText(value=3, description="value")
out_r = w.Output()
DEFAULTS = {
    "credit: minimum months with inflow (of 6)": 3,
    "credit: card score cut-off": 650,
    "AML: inflow / income multiple": 5,
    "AML: structuring band lower bound (USD)": 9000,
}


def draw_rule(*_):
    with out_r:
        out_r.clear_output()
        r, v = w_rule.value, w_val.value
        if r.startswith("credit: minimum"):
            n = pl.q(f"""select count(*) from {{feat_credit_eligibility_pit}}
                         where snapshot_date = (select max(snapshot_date) from {{feat_credit_eligibility_pit}})
                           and months_with_inflow_6m_pit < {v}""").iloc[0, 0]
            msg = f"{n:,} of 150,000 customers would get R04"
        elif r.startswith("credit: card"):
            n = pl.q(f"""select count(*) from {{mart_credit_eligibility}}
                         where len(decline_reasons) = 0 and credit_score_current >= {v}
                           and not has_credit_card_pit""").iloc[0, 0]
            msg = f"{n:,} customers eligible for a card"
        elif r.startswith("AML: inflow"):
            n = pl.q(
                f"select count(*) from {{mart_aml_customer_month}} where inflow_to_declared_income >= {v}"
            ).iloc[0, 0]
            msg = f"{n:,} customer-months flagged INFLOW_INCONSISTENT_WITH_INCOME"
        else:
            n = pl.q(f"""select count(*) from (select customer_id, date_trunc('month', transaction_ts_utc) as m,
                         count(*) as k from {{int_transactions_enriched}}
                         where amount_usd >= {v} and amount_usd < 10000 group by all) where k >= 2""").iloc[
                0, 0
            ]
            msg = f"{n:,} customer-months with 2+ transactions in [{v:,.0f}, 10,000) USD"
        display(Markdown(f"**{msg}** (default parameter: {DEFAULTS[r]})"))


def _reset(*_):
    w_val.value = DEFAULTS[w_rule.value]


w_rule.observe(_reset, "value")
w_val.observe(draw_rule, "value")
draw_rule()
display(w.VBox([w.HBox([w_rule, w_val]), out_r]))

# %%
sens = []
for v in (1, 2, 3, 4):
    n = pl.q(f"""select count(*) from {{feat_credit_eligibility_pit}}
                 where snapshot_date = (select max(snapshot_date) from {{feat_credit_eligibility_pit}})
                   and months_with_inflow_6m_pit < {v}""").iloc[0, 0]
    sens.append({"rule": "R04: months with inflow below", "parameter": v, "flagged": n})
for v in (3, 5, 10):
    n = pl.q(
        f"select count(*) from {{mart_aml_customer_month}} where inflow_to_declared_income >= {v}"
    ).iloc[0, 0]
    sens.append({"rule": "AML: inflow ≥ k × income", "parameter": v, "flagged": n})
show(pd.DataFrame(sens), paging=False)

# %% [markdown]
# Even requiring a **single** month with inflow in six would decline most customers: the thin feed, not the threshold,
# drives the outcome.

# %% [markdown]
# ## Findings and what to do
# 1. **Eligibility is almost universally declined (649 card, 835 loan approvals)** because of thin, deposit-only
#    inflows. Keep the policy; show the reasons. Fix the ordering defect so the mart reads this run's features.
# 2. **The early-warning score works on days past due** and spends most of its other points on "no payment seen",
#    which is uninformative here. Separate *unknown* from *late*, and label products without DPD as unknown.
# 3. **`PEER_OUTLIER_INFLOW` is dead** (peer MAD = 0 everywhere). Recompute peers on months with inflow or use a
#    quantile rule, and add a planted-positive test per typology.
# 4. **AML thresholds should be per country and in local units**, from a compliance-owned seed; flag imputed USD
#    amounts near thresholds.
# 5. **Campaigns:** gate on consent now (no measurable cost), stop promoting held products, and design a randomised
#    holdout before any uplift work.

# %%
pl.close()
print(f"notebook time {time.time() - t0:.0f}s")
