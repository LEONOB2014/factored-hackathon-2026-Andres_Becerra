# %% [markdown]
# # 05 · Conformed silver: conversion, imputation, repairs and flags
# **Pipeline series** · task group `silver`, part 4: `models/silver/conformed`
#
# ## What happens here
# Conformed silver is where the platform starts **interpreting** the data, so it is where most judgement lives.
# Every model here makes decisions a reviewer must be able to see:
#
# | model | grain | decisions it encodes |
# |---|---|---|
# | `int_fx_usd` | currency × day | USD value of one unit of each currency, from the daily rate table |
# | `int_transactions_enriched` | transaction | joins to product and customer, FX by an ASOF join, USD amount (source or imputed), assumed direction, local time, cash and cross-border flags, seven data-quality flags |
# | `int_products_enriched` | product | balances and limits in USD at today's rate, utilisation, delinquency bucket, product DQ flags |
# | `int_customer_profile` | customer | tokens instead of identifiers, income in USD, age, tenure, customer DQ flags |
# | `int_customer_fairness_attributes` | customer | protected and proxy attributes, split off from everything else |
# | `int_customer_month_tx` | customer × month | a dense monthly grid with inflow, outflow, cash, cross-border, AML counters |
# | `int_transactions_enriched_with_holdout` | transaction | history plus the replayed holdout, for serving and stream parity |
#
# The guiding rule: **a repair never hides.** A value that is imputed or assumed gets a flag column (`dq_r18_…`),
# and `audit.dq_integrity_findings` (notebook 12) counts every flag against its SLO.

# %%
import sys
import time

sys.path.insert(0, "../../src")
import ipywidgets as w
import plotly.express as px
from IPython.display import Markdown, display
from itables import show

from latam_eda import pipeline as pipe
from latam_eda import theme

theme.register()
t0 = time.time()
pl = pipe.session()
pl.ensure_until("seeds")
CONFORMED = [
    "int_fx_usd",
    "int_customer_profile",
    "int_customer_fairness_attributes",
    "int_products_enriched",
    "int_transactions_enriched",
    "int_customer_month_tx",
    "int_transactions_enriched_with_holdout",
]
built = pl.build_set(CONFORMED)

# %% [markdown]
# ## 1 · `int_fx_usd`: the exchange-rate backbone
# The source delivers a full cross-rate table (12 pairs a day). Conformed silver keeps one direction: USD per unit of
# each currency, plus USD = 1. Every USD amount in the platform goes through this table.

# %%
fx = pl.q("select * from {int_fx_usd} where currency <> 'USD' order by rate_date")
fx["index (day 1 = 100)"] = fx.groupby("currency")["usd_per_unit"].transform(
    lambda s: 100 * s / s.iloc[0]
)
fig = px.line(
    fx,
    x="rate_date",
    y="index (day 1 = 100)",
    color="currency",
    title="USD value of each currency, indexed to the first day",
)
fig.update_layout(height=340, xaxis_title=None)
fig.show()
show(
    pl.q("""select currency, count(*) as days, min(usd_per_unit) as min_rate, max(usd_per_unit) as max_rate,
                    round(100 * stddev(usd_per_unit) / avg(usd_per_unit), 2) as cv_pct
             from {int_fx_usd} group by 1 order by 1"""),
    paging=False,
)

# %% [markdown]
# **Every currency moves inside a ±2 % band for three years, with no trend.** In reality the Argentine peso lost more
# than 90 % of its value against the dollar between mid-2023 and mid-2026, and the Colombian and Mexican pesos moved
# by double digits. Consequences:
# * USD conversions here are **stable by construction**; any feature that depends on inflation or devaluation
#   (real income, purchasing power, "spend growth in USD") is invalid on this data and must be validated elsewhere.
# * The design is still right: daily rates by an ASOF join (next section) work unchanged on real, volatile rates.

# %% [markdown]
# ## 2 · `int_transactions_enriched`: the conformed transaction fact
# ### 2a · Joins: does anything get lost?
# The model **inner-joins** each transaction to its product and its customer, so a transaction pointing at an unknown
# product or customer would silently disappear. Count before and after.

# %%
recon = pl.q("""
    select (select count(*) from {stg_transactions}) as staged,
           (select count(*) from {int_transactions_enriched}) as enriched,
           (select count(*) from {stg_transactions} t
             where not exists (select 1 from {stg_products} p where p.product_id = t.product_id)) as orphan_product,
           (select count(*) from {stg_transactions} t
             where not exists (select 1 from {stg_customers} c where c.customer_id = t.customer_id))
               as orphan_customer,
           (select count(*) from {stg_transactions} t join {stg_products} p using (product_id)
             where p.customer_id <> t.customer_id) as product_of_another_customer""")
show(recon, paging=False)

# %% [markdown]
# **0 rows lost**: every transaction finds its product and its customer, and the product always belongs to the
# transacting customer. Here the inner join is safe. It is still a latent risk: the day the source sends a
# transaction for a product created later, it vanishes without a test failing.
#
# **Recommendation:** add a row-count reconciliation test (`count(stg_transactions) = count(int_transactions_enriched)`)
# or switch to left joins with a `dq_orphan_*` flag. The cost is one test; the protection is against silent loss in
# the most important table of the platform.

# %% [markdown]
# ### 2b · FX by an ASOF join
# `asof left join int_fx_usd f on f.currency = tx.currency and f.rate_date <= tx.process_date` attaches **the latest
# rate on or before the transaction's business day**. A plain equality join would fail on any day without a rate
# (weekends and holidays in real feeds); ASOF falls back to the last known rate, which is what a bank's accounting does.

# %%
print(
    "\n".join(
        ln
        for ln in pl.sql("int_transactions_enriched").splitlines()
        if "asof" in ln.lower() or "rate_date" in ln
    )
)
show(
    pl.q("""select currency, count(*) as transactions, count(amount_usd) as with_usd
             from {int_transactions_enriched} group by 1 order by 2 desc"""),
    paging=False,
)

# %% [markdown]
# ### 2c · The USD amount: source, recomputed or imputed
# `amount_usd = amount` for USD rows; otherwise the source's `amount_usd` when present, else **`amount × rate`**
# (an imputation, flagged `dq_r18_amount_usd_imputed`). How good is the imputation? On the rows where the source
# *does* give a USD amount, compute both and compare.

# %%
mix = pl.q("""
    select case when currency = 'USD' then '1 · USD, no conversion'
                when not dq_r18_amount_usd_imputed then '2 · source amount_usd'
                else '3 · imputed: amount × daily rate' end as origin,
           count(*) as transactions
    from {int_transactions_enriched} group by 1 order by 1""")
mix["share %"] = (100 * mix.transactions / mix.transactions.sum()).round(2)
show(mix, paging=False)
err = pl.q("""
    with e as (
        select t.currency, 100 * (t.amount * f.usd_per_unit / t.amount_usd_source - 1) as rel_err_pct
        from {stg_transactions} t
        asof left join {int_fx_usd} f on f.currency = t.currency and f.rate_date <= t.process_date
        where t.currency <> 'USD' and t.amount_usd_source is not null and t.amount <> 0)
    select currency, round(rel_err_pct * 10) / 10 as rel_err_bin, count(*) as transactions
    from e group by all order by 1, 2""")
fig = px.bar(
    err,
    x="rel_err_bin",
    y="transactions",
    color="currency",
    barmode="overlay",
    title="Imputation check: (amount × daily rate) / source amount_usd − 1, in % (all rows with both)",
)
fig.update_layout(height=340, xaxis_title="relative error %")
fig.show()
show(
    pl.q("""
    with e as (
        select t.currency, 100 * (t.amount * f.usd_per_unit / t.amount_usd_source - 1) as rel_err_pct
        from {stg_transactions} t
        asof left join {int_fx_usd} f on f.currency = t.currency and f.rate_date <= t.process_date
        where t.currency <> 'USD' and t.amount_usd_source is not null and t.amount <> 0)
    select currency, count(*) as transactions, round(avg(rel_err_pct), 3) as mean_pct,
           round(stddev(rel_err_pct), 3) as std_pct, round(quantile_cont(rel_err_pct, 0.01), 3) as p01_pct,
           round(quantile_cont(rel_err_pct, 0.99), 3) as p99_pct
    from e group by 1"""),
    paging=False,
)

# %% [markdown]
# **The source does not use the daily rate the rate table publishes.** Its USD amounts differ from amount × rate by
# up to ±2 %, **uniformly** (standard deviation 1.15 %, exactly that of a uniform draw on ±2 %): the generator
# applies its own noisy rate. So:
# * the 2.25 % imputed rows carry a **±2 % uncertainty** that the other 97.75 % do not;
# * for most uses (spend totals, segment averages) this is negligible;
# * for **threshold rules** it is not: an imputed 9,900 USD could really be 10,100. The AML near-threshold typology
#   (notebook 08) should treat imputed amounts within 2 % of a threshold as uncertain. Keep `dq_r18` in the mart and
#   exclude or flag those rows in threshold logic.
#
# **Why impute rather than leave NULL.** A NULL amount would drop the transaction from every USD aggregate (customer
# 360, AML, credit inflows) and bias them downwards for exactly the customers whose rows lack the field. Imputing
# with the published rate is the least-biased fill, and the flag keeps it auditable.

# %% [markdown]
# ### 2d · Are Mexican "USD" transactions really dollars? (rule R17)
# Half of all transactions are Mexican customers' transactions labelled USD, and no MXN product exists. If those
# amounts were pesos mislabelled as dollars, they would be about 17 times larger than everyone else's in USD.

# %%
scale = pl.q("""select customer_country_code, currency, count(*) as transactions,
                       round(median(amount), 2) as median_amount, round(median(amount_usd), 2) as median_usd,
                       round(quantile_cont(amount_usd, 0.99), 0) as p99_usd
                from {int_transactions_enriched} group by all order by 1, 2""")
show(scale, paging=False)

# %% [markdown]
# **They are dollars.** The median transaction is about 467 USD in every country and currency, Mexican USD rows
# included. The amounts were generated in USD and converted. R17 is a *labelling* oddity of the synthetic bank (a
# Mexican retail bank would hold MXN accounts), not a unit error, so no conversion is needed. Customer **incomes**,
# however, are in MXN for Mexicans; `int_customer_profile` converts them with the MXN rate (section 4).

# %% [markdown]
# ### 2e · Direction: an assumption, made explicit
# The source has no sign and no counterparty: a "Transfer" could be in or out. The model assumes
# `Deposit = +1`, `Adjustment = 0`, everything else `−1`.

# %%
show(
    pl.q("""select direction, transaction_type, count(*) as transactions,
                    round(100 * count(*) / sum(count(*)) over (), 2) as share_pct
             from {int_transactions_enriched} group by all order by 1, 2"""),
    paging=False,
)

# %% [markdown]
# Under this assumption **82 % of transactions are outflows and only deposits (13.8 %) are inflows.** Every inflow-based
# metric (income verification, cash-flow underwriting, AML "inflow inconsistent with income", collections cash-flow
# stress) rests on deposits alone. Incoming transfers, salary credits and refunds cannot be told apart from outgoing
# ones.
#
# **Implication.** Credit and AML marts under-count inflows for anyone paid by transfer. This is the single most
# consequential assumption in conformed silver. **Recommendation:** ask the source for a signed amount or a debit /
# credit indicator. Until then, keep the assumption in one place (this macro) and name it in every model card that
# uses inflows.

# %% [markdown]
# ### 2f · Derived flags and the data-quality columns
# Rates of every boolean the model adds. The `dq_*` columns are counted again in `audit.dq_integrity_findings`
# against their SLOs.

# %%
bools = list(pl.columns("int_transactions_enriched").query("data_type == 'BOOLEAN'")["column_name"])
rates = pl.q(
    "select "
    + ", ".join(f'round(100 * avg("{c}"::int), 3) as "{c}"' for c in bools)
    + " from {int_transactions_enriched}"
).T.reset_index()
rates.columns = ["flag", "pct of transactions"]
fig = px.bar(
    rates.sort_values("pct of transactions"),
    x="pct of transactions",
    y="flag",
    orientation="h",
    title="Boolean columns of int_transactions_enriched (% true)",
)
fig.update_layout(height=420, yaxis_title=None)
fig.show()

# %% [markdown]
# | flag | meaning | what it means for use |
# |---|---|---|
# | `dq_r01_before_product_open` (≈19 %) | dated before its product was opened | product-age features are unreliable; never filter these rows out (they are real activity), just do not compute "days since opening" from them |
# | `dq_r03_approved_without_code` (4.6 %) | approved with no authorisation code | the inquiry copilot must not explain these with a code; it says "approved" only |
# | `dq_r17_mx_usd_label` (≈50 %) | Mexican customer, USD label | labelling only (section 2d) |
# | `dq_r18_amount_usd_imputed` (2.25 %) | USD amount imputed | ±2 % uncertainty near thresholds |
# | `dq_r19_no_coordinates` (≈46 %) | ATM/POS without coordinates | distance and "impossible travel" features are missing for half the card-present activity |
# | `is_cross_border` (4.6 %) | transaction country ≠ customer country | the foreign destinations of notebook 02 |
# | `is_cash` (11.7 %) | cash deposit or withdrawal at ATM or branch | input to the AML cash-intensity typology |

# %% [markdown]
# ## 3 · `int_products_enriched`: balances at today's rate
# Balances and limits are converted with the **latest** rate (`fx_now`), not the rate of the opening date: the
# question a product answers is "what is it worth now". With flat rates the choice changes nothing here; with real
# ARS it would change everything, and "now" is the correct reading for balances, exposure and utilisation.

# %%
prod = pl.q("""select product_family, count(*) as products, round(median(balance_usd), 0) as median_balance_usd,
                      count(credit_limit) as with_limit, round(avg(utilization), 3) as avg_utilization,
                      count(days_past_due) as with_dpd,
                      round(100 * avg(dq_r22_active_expired_card::int), 2) as active_expired_pct,
                      round(100 * avg(dq_r02_before_customer_registration::int), 2) as before_customer_pct
               from {int_products_enriched} group by 1 order by 2 desc""")
show(prod, paging=False)
dpd = pl.q("""select coalesce(dpd_bucket, '(none)') as bucket, product_family, count(*) as products
              from {int_products_enriched} where product_family in ('credit_card', 'loan') group by all""")
fig = px.bar(
    dpd,
    x="bucket",
    y="products",
    color="product_family",
    barmode="group",
    category_orders={"bucket": ["current", "01-30", "31-60", "61-90", "90+", "(none)"]},
    title="Delinquency buckets of credit products",
)
fig.update_layout(height=320, xaxis_title=None)
fig.show()

# %% [markdown]
# **Reading.** Only credit cards and loans carry limits and days past due (rules R08 and R09 are 0 %). About 5 % of
# credit products have **no limit and no days past due** (`(none)`): for those, utilisation is NULL and delinquency
# unknown. The collections mart must treat them as "unknown", never as "current". 14 % of all products, 41 % of
# all cards, are active cards past expiry (R22), the reissue population of the card-support mart. Half of all products were opened before
# their customer registered (R02), so product age cannot be trusted.

# %% [markdown]
# ## 4 · `int_customer_profile`: tokens, income in USD, age and tenure
# Direct identifiers (document, e-mail, phone) become **tokens**: `sha256(salt | lower(trim(value)))`. The same
# person always gets the same token, so tokens join across tables, but the value cannot be read back. Locally the salt
# is a development default; the stack injects a secret (`LATAM_PII_SALT`), which is why the tokens in this scratch
# lakehouse differ from the live ones (notebook 12). **In production the macro must become a keyed HMAC from a
# KMS-backed tokenisation service**: a salted SHA-256 of a 10-digit document number can be brute-forced.

# %%
prof = pl.q("""select country_code, home_currency, count(*) as customers,
                      round(median(monthly_income_local), 0) as median_income_local,
                      round(median(monthly_income_usd), 0) as median_income_usd,
                      round(median(age_years), 1) as median_age, round(median(tenure_days) / 365.25, 1) as tenure_years,
                      round(100 * avg(dq_r05_minor_at_registration::int), 2) as minor_at_registration_pct,
                      round(100 * avg(dq_r06_future_last_updated::int), 2) as future_last_updated_pct
               from {int_customer_profile} group by all order by 1""")
show(prof, paging=False)
inc = pl.q("""select country_code, quantile_cont(monthly_income_usd, [0.1, 0.25, 0.5, 0.75, 0.9]) as q
              from {int_customer_profile} group by 1 order by 1""")
inc = inc.assign(
    **{f"p{p}": inc.q.map(lambda q, i=i: q[i]) for i, p in enumerate([10, 25, 50, 75, 90])}
).drop(columns="q")
fig = px.bar(
    inc.melt(id_vars="country_code", var_name="percentile", value_name="usd"),
    x="percentile",
    y="usd",
    color="country_code",
    barmode="group",
    title="Monthly income in USD after conversion, by percentile",
)
fig.update_layout(height=340)
fig.show()

# %% [markdown]
# **The MXN conversion is right.** Incomes are reported in local currency (pesos for Mexicans, although their
# accounts are in USD). After conversion, the median is about 2,300 USD in all three countries. Without the
# special case for MXN (the `mxn` CTE), Mexican incomes would be read as dollars, 17 times too large, and every
# income-based ratio (payment-to-income, inflow-to-income for AML) would be wrong for half the customers.
#
# 2 % of customers were minors at registration (R05) and 6 % have `last_updated` in the future (R06): both are flagged,
# not removed.

# %% [markdown]
# ## 5 · `int_customer_fairness_attributes`: protected attributes, quarantined
# Gender, marital status, age band, detected accent and country live in their own table, readable for fairness
# analysis and nothing else. The governance test `assert_protected_attributes_isolated` fails any feature or mart that
# carries them. This is how the platform makes "the model cannot see gender" a tested fact instead of a promise.

# %%
show(pl.columns("int_customer_fairness_attributes"), paging=False)

# %% [markdown]
# ## 6 · `int_customer_month_tx`: the dense monthly grid
# Every customer gets a row for **every** month, with zeros where nothing happened. This is an **imputation of
# zeros**, and it is the correct one: no transaction in a month means no activity, not an unknown value. Without the
# grid, a rolling average over "the last 6 months" would silently average only the active months and overstate
# activity.

# %%
grid = pl.q("""select count(*) as customer_months, count(distinct customer_id) as customers,
                      count(distinct month_start) as months, min(month_start) as first_month,
                      max(month_start) as last_month, round(100 * avg((n_tx = 0)::int), 2) as zero_month_pct,
                      round(100 * avg((inflow_usd > 0)::int), 2) as months_with_inflow_pct
               from {int_customer_month_tx}""")
show(grid, paging=False)
dist = pl.q(
    "select least(n_tx, 8) as tx_in_month, count(*) as customer_months from {int_customer_month_tx} group by 1"
)
fig = px.bar(
    dist.sort_values("tx_in_month"),
    x="tx_in_month",
    y="customer_months",
    title="Transactions per customer-month (8 = 8 or more)",
)
fig.update_layout(height=300)
fig.show()
recent = pl.q("""select months_with_inflow, count(*) as customers from (
                   select customer_id, count(*) filter (where inflow_usd > 0) as months_with_inflow
                   from {int_customer_month_tx} where month_start >= date '2025-11-01' group by 1)
                 group by 1 order by 1""")
show(recent, paging=False)

# %% [markdown]
# **Half of all customer-months are empty** and only 9 % contain an inflow. In the last seven months, 59 % of
# customers received **no** inflow at all and only about 1 % had inflows in four or more months. Any credit rule of the
# form "income in at least 3 of the last 6 months" declines almost everyone: that is the `R04_INSUFFICIENT_INCOME_HISTORY`
# reason the credit mart gives 96 % of customers (notebook 08). The grid is right; the data is thin (0.8 transactions a
# month).
#
# **Edge months are partial.** The first month (June 2023) starts on the 17th and the last historical month (May
# 2026) ends on the 17th, before the holdout. Monthly totals for those two months are about half of a full month and
# must be excluded or pro-rated in any trend or seasonality analysis.

# %% [markdown]
# ## 7 · `int_transactions_enriched_with_holdout`
# The same enrichment applied to history plus holdout (4,425,008 rows): serving tables and the stream-parity check read
# it, so the online path sees the "future" the batch path never trained on.

# %%
show(
    pl.q("""select process_date >= date '2026-05-18' as holdout, count(*) as transactions
             from {int_transactions_enriched_with_holdout} group by 1"""),
    paging=False,
)

# %% [markdown]
# ## 8 · The silver task group's tests
# Cosmos runs the silver tests once the whole group is built. Here they are, executed against the scratch lakehouse.

# %%
pl.ensure_until("silver")
tests = pl.run_tests("silver")
show(tests["status"].value_counts().rename_axis("status").reset_index(name="tests"), paging=False)
show(
    tests[tests.status != "pass"][["test", "attached_to", "severity", "failures", "status"]],
    paging=False,
)

# %% [markdown]
# Two **warnings**, no failures: 149,995 customers registered at a branch that does not exist and 831 agents assigned
# to one (R23, R24). They are severity WARN on purpose: branch analytics are impossible, but no money or customer
# outcome depends on the branch id. Every other test (keys unique and not null, accepted values, relationships,
# custom checks) passes.

# %% [markdown]
# ## 9 · Explorer: any conformed model

# %%
w_m = w.Dropdown(options=CONFORMED, value="int_customer_profile", description="model")
out_m = w.Output()


def draw_model(*_):
    with out_m:
        out_m.clear_output()
        p = pl.profile(w_m.value).merge(
            pl.columns(w_m.value)[["column_name", "description"]], on="column_name"
        )
        display(Markdown(f"**{w_m.value}** · {pl.rows(w_m.value):,} rows"))
        show(
            p[
                [
                    "column_name",
                    "data_type",
                    "null_pct",
                    "distinct_approx",
                    "min",
                    "max",
                    "description",
                ]
            ],
            paging=False,
        )
        show(pl.safe(pl.q(f"select * from {{{w_m.value}}} limit 5")), paging=False)


w_m.observe(draw_model, "value")
draw_model()
display(w.VBox([w_m, out_m]))

# %% [markdown]
# ## Findings and what to do
# 1. **No row is lost in conformed silver.** The inner joins keep all 4,294,318 transactions, and every transaction's
#    product belongs to its customer. Add a reconciliation test so this stays true.
# 2. **The FX imputation is unbiased but noisy** (±2 % against the source's own USD amounts) and touches 2.25 % of
#    transactions. Keep the flag in every mart and treat imputed amounts near a regulatory threshold as uncertain.
# 3. **Mexican USD amounts are real dollars** (median 467 USD like everyone else); **Mexican incomes are pesos** and are
#    converted correctly. The MXN special case is essential and deserves a unit test of its own.
# 4. **Direction is an assumption** (only deposits are inflows), and it drives every inflow-based use case. It is the
#    first data request to make of a real source: a signed amount or a debit/credit flag.
# 5. **Rates are flat for three years**, so inflation-sensitive features cannot be validated here.
# 6. **The monthly grid correctly imputes zeros**, and shows how thin the data is: half the months empty, 1 % of
#    customers with regular recent income. Exclude the two partial edge months from trends.
# 7. **Tokens are salted SHA-256**: fine for a demo, brute-forceable in production. Replace with keyed HMAC from a
#    tokenisation service before any real data arrives.

# %%
pl.close()
print(f"notebook time {time.time() - t0:.0f}s")
