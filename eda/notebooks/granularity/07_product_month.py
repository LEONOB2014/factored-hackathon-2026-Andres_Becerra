# %% [markdown]
# # 07 · Product × month: the portfolio, its vintages and early credit signs
# **Granularity series** · grain: one product and calendar month (`agg.fct_product_month`, 12.4 M rows)
#
# **Stakeholders.** Product managers (which products stay in use after they are opened), the credit-risk team (does a
# product's monthly behaviour announce delinquency?) and finance (portfolio activity by vintage).
#
# **What this grain adds.** A customer holds 2.7 products on average; the customer grain mixes a savings account that is
# used daily with a credit card that is never used. The product grain separates them, and the months since opening
# place every product on its **vintage curve**, the standard lens of a lending and cards portfolio.
#
# **Methods.**
# 1. **Portfolio activity** by product family and month (share of products with any transaction).
# 2. **Vintage curves**: activity rate by months since opening, per opening quarter, for products opened inside the
#    data window.
# 3. **Product dormancy** (no transaction in the next three months) predicted out of time from the product's own
#    history, the series protocol.
# 4. **Delinquency from payment history**: for credit products, does the payment behaviour of the last six months
#    explain the current days past due? This is the strongest test available of the credit signal, because days past due
#    exists only as today's value (no roll rates can be built: shown below).

# %%
import sys
import time
from pathlib import Path

sys.path.insert(0, "../../src")
import pandas as pd
import plotly.express as px
from IPython.display import Markdown, display
from itables import show

from latam_eda import country, theme
from latam_eda import granularity as g

OUT = Path("../../reports/tables")
OUT.mkdir(parents=True, exist_ok=True)
theme.register()
t0 = time.time()
pl = country.session("ALL", "main")
country.prepare(pl, "gold")
star = g.open_star(pl)
star.build(["fct_product_month"], verbose=False)
FULL = star.q("select month_start from {dim_month} where not is_partial order by 1").month_start
FIRST, LAST = FULL.min(), FULL.max()

# %% [markdown]
# ## 1 · Portfolio activity by product family

# %%
fam = star.q(f"""
    select product_family, month_start, count(*) as products, avg((n_tx > 0)::int) as active_share,
           sum(payments_usd) as payments_usd
    from {{fct_product_month}} where not before_opening and month_start between '{FIRST}' and '{LAST}'
    group by all order by 1, 2""")
fig = px.line(
    fam,
    x="month_start",
    y="active_share",
    color="product_family",
    title="Share of products used in the month",
)
fig.update_layout(height=320, yaxis_tickformat=".0%", xaxis_title=None)
fig.show()
summ = fam.groupby("product_family").agg(
    products=("products", "last"), active_share=("active_share", "mean")
)
show(summ.round(4), paging=False)
pre = star.q(
    "select count(*) as rows_, sum(n_tx) as tx from {fct_product_month} where before_opening"
).iloc[0]
display(
    Markdown(
        "**Monthly use by family:** "
        + ", ".join(f"{k} {100 * v:.1f} %" for k, v in summ.active_share.sort_values().items())
        + f". {int(pre.tx):,} transactions are dated before their product opened (R01) and sit in "
        f"{int(pre.rows_):,} pre-opening rows of the fact, kept so the fact reconciles with the atomic transactions."
    )
)

# %% [markdown]
# ## 2 · Vintage curves

# %%
vin = star.q(f"""
    select vintage_quarter, months_since_open, avg((n_tx > 0)::int) as active_share, count(*) as products
    from {{fct_product_month}}
    where not before_opening and opening_date >= '{FIRST}' and month_start <= '{LAST}' and months_since_open between 0 and 30
    group by all having count(*) >= 200 order by 1, 2""")
fig = px.line(
    vin,
    x="months_since_open",
    y="active_share",
    color=vin.vintage_quarter.astype(str),
    title="Vintage curves: share of products used, by months since opening (quarterly vintages)",
)
fig.update_layout(height=360, yaxis_tickformat=".0%", legend_title="opened")
fig.show()
early = vin[vin.months_since_open <= 2].active_share.mean()
mature = vin[vin.months_since_open >= 12].active_share.mean()
spread = vin[vin.months_since_open == 6].active_share
display(
    Markdown(
        f"**Products are used in {100 * early:.1f} % of their first three months and {100 * mature:.1f} % of months "
        f"after a year; at six months the vintages range from {100 * spread.min():.1f} % to {100 * spread.max():.1f} %.** "
        + (
            "The curves are flat and the vintages overlap: a product is as likely to be used in its first month as "
            "in its twentieth, and no vintage is better than another. Real vintage curves start high and decay "
            "(activation, then attrition), and a deteriorating vintage is the first sign of a loosened origination "
            "policy; here there is no such dynamic to monitor."
            if abs(early - mature) < 0.05
            else "Usage decays with age: an activation programme in the first months is worth testing."
        )
    )
)

# %% [markdown]
# ## 3 · Can roll rates be built? No, and here is why
# A roll rate is the share of accounts moving from one delinquency bucket to the next between two months. It needs the
# days past due of every account **each month**. The source delivers it once, as the current value; the product-month
# fact carries it as a snapshot attribute, constant over the product's rows.

# %%
dpd = star.q("""
    select product_family, count(distinct product_id) as products,
           count(distinct snapshot_days_past_due) as distinct_dpd_values_in_family
    from (select product_id, product_family, snapshot_days_past_due from {fct_product_month}
          where is_credit_product) group by 1""")
var = star.q("""select max(n) as max_distinct_dpd_per_product from (
                  select product_id, count(distinct snapshot_days_past_due) as n from {fct_product_month}
                  where is_credit_product group by 1)""").iloc[0, 0]
show(dpd, paging=False)
display(
    Markdown(
        f"**Every credit product has at most {var} distinct days-past-due value across its months: there is no "
        "delinquency history, so no roll rate, cure rate or transition matrix can be estimated.** Collections and "
        "provisioning (IFRS 9 staging needs the movement between stages) stay blocked until the SCD2 snapshots, now "
        "running daily, accumulate a year of history (`docs/strategy/12_development_path.md` §12.4)."
    )
)

# %% [markdown]
# ## 4 · Product dormancy: will this product go unused for the next three months?
# One row per product and month t (a deterministic 10 % sample of products, used in month t), features from months
# up to t only, target: no transaction in months t+1 to t+3. Snapshot attributes (balance, limit, days past due) are
# today's values and would leak the future into past months, so they are excluded.

# %%
pp = star.q(f"""
    with f as (
        select product_id, month_start, product_family, product_type, currency, months_since_open, n_tx, outflow_usd,
               inflow_usd, payments_usd, n_declined, n_insufficient_funds,
               sum(n_tx) over w3 as tx_3m, sum(n_tx) over w6 as tx_6m, sum(payments_usd) over w6 as payments_6m,
               sum(n_declined) over w6 as declined_6m, sum(n_insufficient_funds) over w6 as nsf_6m,
               count(*) filter (where n_tx > 0) over w6 as active_months_6m,
               coalesce(sum(n_tx) over wf, 0) as tx_next_3m,
               count(*) over wf as months_ahead
        from {{fct_product_month}}
        where not before_opening and hash(product_id) % 10 = 0 and month_start <= '{LAST}'
        window w3 as (partition by product_id order by month_start rows between 2 preceding and current row),
               w6 as (partition by product_id order by month_start rows between 5 preceding and current row),
               wf as (partition by product_id order by month_start rows between 1 following and 3 following))
    select f.*, f.tx_next_3m = 0 as dormant_next_3m
    from f where n_tx > 0 and months_ahead = 3 and month_start >= '{FIRST}'::date + interval 5 month
    order by product_id, month_start""")
PF = [
    "product_family",
    "product_type",
    "currency",
    "months_since_open",
    "n_tx",
    "tx_3m",
    "tx_6m",
    "payments_6m",
    "declined_6m",
    "nsf_6m",
    "active_months_6m",
    "outflow_usd",
    "inflow_usd",
]
rows = []
r = country.evaluate_target(pp, "dormant_next_3m", "month_start", PF)
r["name"] = "product dormant next 3 months (used now)"
rows.append(g.classification_row("product × month", r))
display(
    Markdown(
        f"**Product dormancy: AUC {r['auc']:.3f} [{r['auc_lo']:.3f}, {r['auc_hi']:.3f}], AP lift {r['ap_lift']:.2f} on "
        f"a base rate of {r['base_rate']:.3f} → {country.verdict(r)}; best single feature `{r['best_single_feature']}` "
        f"{r['best_single_auc']:.3f}.**"
    )
)

# %% [markdown]
# ## 5 · Does payment behaviour explain delinquency?
# Credit products (cards and loans) with a known days-past-due value; features from the product's last six full months
# of history (payments, declines, insufficient-funds declines, activity) plus its family and age; the target is days
# past due above 30. The split is by opening date (older products train, newer test), as in the country series, where
# the same target with customer-level features gave AUC 0.50.

# %%
cr = star.q(f"""
    select product_id, any_value(product_family) as product_family, any_value(product_type) as product_type,
           any_value(opening_date) as opening_date, any_value(currency) as currency,
           sum(payments_usd) as payments_6m, count(*) filter (where payments_usd > 0) as months_with_payment_6m,
           sum(n_declined) as declined_6m, sum(n_insufficient_funds) as nsf_6m, sum(n_tx) as tx_6m,
           sum(outflow_usd) as outflow_6m, max(months_since_open) as months_since_open,
           any_value(snapshot_utilization) as utilization, any_value(snapshot_days_past_due) > 30 as dpd_over_30
    from {{fct_product_month}}
    where is_credit_product and not before_opening and snapshot_days_past_due is not null
      and month_start between '{LAST}'::date - interval 5 month and '{LAST}'
    group by product_id order by product_id""")
CF = [
    "product_family",
    "product_type",
    "currency",
    "payments_6m",
    "months_with_payment_6m",
    "declined_6m",
    "nsf_6m",
    "tx_6m",
    "outflow_6m",
    "months_since_open",
]
r2 = country.evaluate_target(cr, "dpd_over_30", "opening_date", CF)
r2["name"] = "credit product more than 30 days past due (payment history)"
rows.append(g.classification_row("product × month", r2))
r3 = country.evaluate_target(cr, "dpd_over_30", "opening_date", [*CF, "utilization"])
r3["name"] = "… adding current utilisation (same-moment, partly caused by delinquency)"
rows.append(g.classification_row("product × month", r3))
tab = pd.DataFrame(rows).reindex(columns=g.TARGET_COLUMNS)
tab.to_csv(OUT / "granularity_targets_product.csv", index=False)
show(tab, paging=False)
display(
    Markdown(
        f"**Delinquency from six months of payment history: AUC {r2['auc']:.3f} [{r2['auc_lo']:.3f}, "
        f"{r2['auc_hi']:.3f}] → {country.verdict(r2)}.** "
        + (
            "Re-graining to the product does not reveal a credit signal that the customer grain hid: whether a card or "
            "loan is delinquent today is independent of how it was paid. "
            if r2["auc_lo"] <= 0.5
            else "The product's own payment history carries delinquency signal that the customer grain missed. "
        )
        + f"Adding today's utilisation gives {r3['auc']:.3f}: "
        + (
            "no better, so balance is not a hidden driver either."
            if r3["auc"] - r2["auc"] < 0.02
            else "higher, but utilisation is measured at the same moment as the delinquency and partly caused by it, "
            "so the gain is not usable for prediction."
        )
    )
)

# %% [markdown]
# ## Findings, decisions and what they mean downstream
# * **KPIs at this grain:** active-product rate by family, vintage activity curves, payments per credit product and
#   the share of transactions predating their product (a data-quality KPI). They belong on the product managers'
#   dashboard.
# * **Credit risk:** neither the product nor the customer grain predicts delinquency on this data; the blocker is the
#   missing history, which the SCD2 snapshots are now accumulating. Roll rates, cure rates and IFRS 9 staging become
#   possible after a year of daily snapshots, and their natural home is a `fct_product_month` with days past due as a
#   true monthly measure (read from the snapshot as of each month end).
# * **Downstream:** the product-month fact is the largest aggregate (12.4 M rows over 36 months, growing with the
#   product base); build it incrementally per month, partition it by month, and keep snapshot attributes out of its
#   measures until they have history.

# %%
pl.close()
print(f"notebook time {time.time() - t0:.0f}s")
