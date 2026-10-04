# %% [markdown]
# # 05 · Currency, conversion, imputation and the monthly grid (All countries)
# **Backup-as-main series · All countries** · *generated from `notebooks/country_template`: edit the template*
#
# Conformed silver converts every amount to USD, fills missing USD amounts with the daily rate, assumes a direction
# for money, converts incomes and builds a dense monthly grid (pipeline series, notebook 05). Each of those decisions
# is re-examined here on All countries's currencies.
#
# **Rule for this country: analyse in the account's currency, compare in USD.** Statistics such as medians, outlier
# thresholds and structuring bands are computed per currency; only cross-country comparisons use USD.

# %%
import sys
import time

sys.path.insert(0, "../../src")
import pandas as pd
import plotly.express as px
from IPython.display import Markdown, display
from itables import show

from latam_eda import country, theme

COUNTRY = "ALL"
DATASET = "backup"
PREFIX = "backup"
CTRY = country.SCOPES[COUNTRY]
theme.register()
t0 = time.time()
pl = country.session(COUNTRY, DATASET)
country.prepare(pl, "seeds")
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
# ## 1 · The country's exchange rate

# %%
HOME = [country.COUNTRIES[c].home_currency for c in country.scope_codes(COUNTRY)]
fx = pl.q(f"""select currency, rate_date, usd_per_unit, 1 / usd_per_unit as units_per_usd
              from {{int_fx_usd}} where currency in ({", ".join(f"'{c}'" for c in HOME)}) order by 1, 2""")
fx["index_first_day_100"] = (
    100 * fx.units_per_usd / fx.groupby("currency").units_per_usd.transform("first")
)
fig = px.line(
    fx,
    x="rate_date",
    y="index_first_day_100" if len(HOME) > 1 else "units_per_usd",
    color="currency",
    title=f"{' / '.join(HOME)} per USD" + (" (first day = 100)" if len(HOME) > 1 else ""),
)
fig.update_layout(height=300, xaxis_title=None)
fig.show()
fxs = fx.groupby("currency").units_per_usd.agg(
    move_pct=lambda x: 100 * (x.iloc[-1] / x.iloc[0] - 1), cv_pct=lambda x: 100 * x.std() / x.mean()
)
show(fxs.round(2), paging=False)
move, cv = fxs.move_pct.iloc[0], fxs.cv_pct.iloc[0]
real = {
    "MX": "the peso moved between about 16.5 and 20.5 per dollar (2023–2025)",
    "CO": "the peso moved between about 3,800 and 4,500 per dollar (2023–2025)",
    "AR": "the official peso went from about 260 to over 1,000 per dollar (2023–2025), including a devaluation of "
    "more than 50 % in December 2023",
}
display(
    Markdown(
        (
            f"**{CTRY.home_currency} per USD moves {move:+.1f} % over three years (coefficient of variation {cv:.1f} %).** "
            f"In reality {real[COUNTRY]}. Every USD figure in this country is therefore "
            if COUNTRY != "ALL"
            else "**The three rates move "
            + ", ".join(f"{c} {r.move_pct:+.1f} %" for c, r in fxs.iterrows())
            + " over three years.** In reality "
            + "; ".join(real.values())
            + ". Every USD figure of the bank is therefore "
        )
        + "stable by construction; any feature meant to capture devaluation, inflation or real income cannot be validated "
        "here."
        + (
            " For Argentina this matters most: a real Argentine model must work in inflation-adjusted terms."
            if COUNTRY in ("AR", "ALL")
            else ""
        )
    )
)

# %% [markdown]
# ## 2 · Amounts per currency

# %%
amt = pl.q("""select currency, count(*) as transactions, round(median(amount), 2) as median_amount,
                     round(quantile_cont(amount, 0.99), 2) as p99_amount, round(median(amount_usd), 2) as median_usd,
                     round(quantile_cont(amount_usd, 0.99), 2) as p99_usd
              from {int_transactions_enriched} group by 1 order by 2 desc""")
show(amt, paging=False)
dist = pl.q("""select currency, floor(log10(greatest(amount, 0.01)) * 4) / 4 as log10_amount_bin, count(*) as n_tx
               from {int_transactions_enriched} group by all order by 1, 2""")
fig = px.bar(
    dist,
    x="log10_amount_bin",
    y="n_tx",
    color="currency",
    barmode="overlay",
    title=f"{CTRY.title}: distribution of log10(amount) per currency",
)
fig.update_layout(height=320)
fig.show()
lo_usd, hi_usd = amt.median_usd.min(), amt.median_usd.max()
display(
    Markdown(
        (
            f"**In USD every currency has about the same median ({lo_usd:,.0f} to {hi_usd:,.0f}): amounts were "
            "generated in dollars and converted.** "
            if hi_usd <= 1.05 * lo_usd
            else f"**The USD medians differ by currency ({lo_usd:,.0f} to {hi_usd:,.0f}):** the currencies carry "
            "different behaviour, not only different units. "
        )
        + "Per-currency statistics are still the right default: a threshold in pesos and one in dollars cannot share a "
        "number, and a model fed raw `amount` across currencies would learn the currency, not the behaviour."
    )
)

# %% [markdown]
# ## 3 · The USD imputation in this country
# `amount_usd` is missing for some non-USD transactions and is filled with amount × the published daily rate
# (`dq_r18_amount_usd_imputed`). Its error, measured where the source gives the value:

# %%
mix = pl.q("""
    select case when currency = 'USD' then 'USD, no conversion'
                when not dq_r18_amount_usd_imputed then 'source amount_usd' else 'imputed' end as origin,
           count(*) as transactions
    from {int_transactions_enriched} group by 1 order by 2 desc""")
mix["share %"] = (100 * mix.transactions / mix.transactions.sum()).round(2)
show(mix, paging=False)
err = pl.q("""
    with e as (select t.currency, 100 * (t.amount * f.usd_per_unit / t.amount_usd_source - 1) as rel_err_pct
               from {stg_transactions} t asof left join {int_fx_usd} f
                 on f.currency = t.currency and f.rate_date <= t.process_date
               where t.currency <> 'USD' and t.amount_usd_source is not null and t.amount <> 0)
    select currency, count(*) as n, round(avg(rel_err_pct), 3) as mean_pct, round(stddev(rel_err_pct), 3) as sd_pct,
           round(min(rel_err_pct), 2) as min_pct, round(max(rel_err_pct), 2) as max_pct
    from e group by 1""")
show(err, paging=False)
imp = mix.set_index("origin")["share %"].get("imputed", 0.0)
display(
    Markdown(
        (
            f"**{imp:.2f} % of {CTRY.name}'s transactions carry an imputed USD amount; where the source gives the "
            f"value, the rate reproduces it within {err.min_pct.min():+.1f} % to {err.max_pct.max():+.1f} % "
            f"(mean {err.mean_pct.mean():+.2f} %).** "
            if len(err)
            else f"**{CTRY.title} has no non-USD transactions: nothing is converted or imputed.** "
        )
        + (
            "Decision: keep the imputation (unbiased; dropping or zeroing would understate USD totals for exactly the "
            "rows missing the field) and keep the flag in every mart; treat imputed amounts within 2 % of any regulatory "
            "threshold as uncertain."
            if len(err)
            else "Every USD figure here is exact; the R18 rule cannot fire in this country."
        )
    )
)

# %% [markdown]
# ## 4 · Incomes: the currency trap in reverse

# %%
inc = pl.q("""select home_currency, count(*) as customers, round(median(monthly_income_local), 0) as median_income_local,
                     round(median(monthly_income_usd), 0) as median_income_usd,
                     round(quantile_cont(monthly_income_usd, 0.9), 0) as p90_income_usd
              from {int_customer_profile} group by 1""")
show(inc, paging=False)
display(
    Markdown(
        (
            f"Incomes are reported in **{CTRY.home_currency}**, converted with the {CTRY.home_currency} rate to a "
            f"median of about {inc.median_income_usd.iloc[0]:,.0f} USD a month. "
            if COUNTRY != "ALL"
            else "Incomes are reported in each country's currency and converted with its rate: median "
            + ", ".join(
                f"{r.home_currency} {r.median_income_usd:,.0f} USD" for r in inc.itertuples()
            )
            + " a month. "
        )
        + (
            "Mexican accounts are all in USD while incomes are in pesos: comparing an amount with an income without "
            "converting the income would make every Mexican look 17 times richer than they are. The special case in "
            "`int_customer_profile` is what keeps every income ratio right."
            if COUNTRY in ("MX", "ALL")
            else "Accounts mix the home currency and USD, so every income ratio must compare USD with USD."
        )
    )
)

# %% [markdown]
# ## 5 · Direction and the monthly grid

# %%
show(
    pl.q("""select direction, transaction_type, count(*) as transactions,
                    round(100 * count(*) / sum(count(*)) over (), 2) as share_pct
             from {int_transactions_enriched} group by all order by 1, 2"""),
    paging=False,
)
grid = pl.q("""select count(*) as customer_months, round(100 * avg((n_tx = 0)::int), 2) as zero_month_pct,
                      round(100 * avg((inflow_usd > 0)::int), 2) as months_with_inflow_pct, round(avg(n_tx), 3) as avg_tx
               from {int_customer_month_tx}""")
show(grid, paging=False)
last_month = pl.q("select max(month_start) as m from {int_customer_month_tx}").m.iloc[0]
first_month = (pd.Timestamp(last_month) - pd.DateOffset(months=6)).date()
recent = pl.q(f"""select months_with_inflow, count(*) as customers from (
                   select customer_id, count(*) filter (where inflow_usd > 0) as months_with_inflow
                   from {{int_customer_month_tx}} where month_start >= date '{first_month}' group by 1)
                 group by 1 order by 1""")
fig = px.bar(
    recent,
    x="months_with_inflow",
    y="customers",
    title=f"Months with any inflow, {first_month:%b %Y} – {pd.Timestamp(last_month):%b %Y}",
)
fig.update_layout(height=300)
fig.show()
reg = recent[recent.months_with_inflow >= 4].customers.sum() / recent.customers.sum()
tx_end = pd.Timestamp(
    pl.q("select max(transaction_ts_utc) as d from {int_transactions_enriched}").d.iloc[0]
).date()
display(
    Markdown(
        f"**{grid.zero_month_pct.iloc[0]:.1f} % of customer-months are empty and {100 * reg:.1f} % of customers had an "
        "inflow in four or more of the last seven months.** The zero-filled grid is the right imputation (no transaction "
        "is zero activity); "
        + (
            f"but here the grid runs to {pd.Timestamp(last_month):%B %Y} while the last transaction is dated {tx_end}: "
            "every recent month is empty because the **data stops**, not because customers did. The grid cannot tell "
            "the two apart, and every credit rule of notebook 08 will read an inactive bank."
            if pd.Timestamp(tx_end) < pd.Timestamp(first_month)
            else "the thinness is the data's, and it decides the credit outcomes of notebook 08."
        )
    )
)

# %% [markdown]
# ## 6 · Silver tests for the country

# %%
pl.ensure_until("silver")
tests = pl.run_tests("silver")
show(
    tests[tests.status != "pass"][["test", "attached_to", "severity", "failures", "status"]],
    paging=False,
)
dangling = tests[tests.test.str.contains("affected_product_id")]
if len(dangling) and dangling.failures.iloc[0]:
    display(
        Markdown(
            f"**New in the country cut: {int(dangling.failures.iloc[0]):,} complaints name a product that is not in "
            f"{CTRY.name}'s product table.** Bank-wide, every named product belonged to *another customer* (R25); the "
            "country cut shows most of those customers live in **another country**. The product link of a complaint is "
            "not just wrong, it crosses borders: no country team could ever have resolved it."
            if COUNTRY != "ALL"
            else f"**{int(dangling.failures.iloc[0]):,} complaints name a product that is not in the product table "
            "at all**: a dangling reference, beyond the R25 defect (a product owned by another customer)."
        )
    )

# %% [markdown]
# ## Findings for All countries and what to do
# The computed statements above are the findings; the method holds for every country: per-currency statistics,
# converted incomes, flagged imputations, a zero-filled grid, and the direction assumption stated in every model card.

# %%
pl.close()
print(f"notebook time {time.time() - t0:.0f}s")
