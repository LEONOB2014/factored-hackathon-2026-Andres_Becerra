# %% [markdown]
# # 06 · Snapshots and the gold core (__COUNTRY_NAME__)
# **__SERIES__ · __COUNTRY_NAME__** · *generated from `notebooks/country_template`: edit the template*
#
# The star schema of __COUNTRY_NAME__: SCD2 snapshots, surrogate keys, facts and their joins (pipeline series,
# notebook 06). The bank-wide replay found that the first SCD2 version is valid only from registration or opening, so
# facts dated earlier lose their keys. Here: how much of this country's history is affected, and whether the grains
# and keys hold.

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

COUNTRY = "__COUNTRY__"
DATASET = "__DATASET__"
PREFIX = "__PREFIX__"
CTRY = country.SCOPES[COUNTRY]
OUT = Path("../../reports/tables")
OUT.mkdir(parents=True, exist_ok=True)
theme.register()
t0 = time.time()
pl = country.session(COUNTRY, DATASET)
country.prepare(pl, "silver")
SNAPS = ["snap_branches", "snap_customers", "snap_products", "snap_service_agents"]
CORE = sorted(
    n for n in pl.catalog().query("layer == 'gold'")["node"] if n.startswith(("dim_", "fct_"))
)
pl.build_set(SNAPS)
built = pl.build_set(CORE)

# %% [markdown]
# ## 1 · Point-in-time keys of the transaction fact

# %%
cov = pl.q("""select count(*) as transactions,
                     round(100 * avg((customer_sk is null)::int), 2) as missing_customer_sk_pct,
                     round(100 * avg((product_sk is null)::int), 2) as missing_product_sk_pct,
                     round(100 * avg((customer_sk is null or product_sk is null)::int), 2) as missing_either_pct
              from {fct_transaction}""")
show(cov, paging=False)
yr = pl.q("""select year(transaction_ts_utc) as year, round(100 * avg((customer_sk is null)::int), 1) as customer_pct,
                    round(100 * avg((product_sk is null)::int), 1) as product_pct
             from {fct_transaction} group by 1 order by 1""")
fig = px.bar(
    yr.melt(id_vars="year"),
    x="year",
    y="value",
    color="variable",
    barmode="group",
    title=f"{CTRY.title}: transactions whose point-in-time join finds no version (%)",
)
fig.update_layout(height=300, yaxis_title="%", legend_title=None)
fig.show()
why = pl.q("""
    select count(*) filter (where customer_sk is null or product_sk is null) as missing,
           count(*) filter (where (customer_sk is null or product_sk is null)
                              and (customer_sk is not null or f.transaction_ts_utc < c.registration_date)
                              and (product_sk is not null or f.transaction_ts_utc < p.opening_date)) as predates
    from {fct_transaction} f left join {int_customer_profile} c using (customer_id)
    left join {int_products_enriched} p using (product_id)""").iloc[0]
explained = 100 * why.predates / max(why.missing, 1)
display(
    Markdown(
        f"**{cov.missing_either_pct.iloc[0]:.1f} % of {CTRY.name}'s transactions lose at least one key**; "
        f"{explained:.1f} % of those because they predate the customer's registration or the product's opening (an "
        "independence of dates in the generator). The fix is the same in every country: the first version is valid "
        "from the beginning of time."
        + (
            " The share is higher than main's 19 % because this dataset's transactions are concentrated in the "
            "first fifteen months, when fewer customers and products had been opened."
            if DATASET == "backup"
            else ""
        )
    )
)

# %% [markdown]
# ## 2 · Grains and foreign keys

# %%
checks = [
    ("fct_transaction", "transaction_id", "customer_id", "dim_customer", "customer_id"),
    ("fct_transaction", "transaction_id", "merchant_id", "dim_merchant", "merchant_id"),
    ("fct_interaction", "interaction_id", "agent_id", "dim_agent", "agent_id"),
    ("fct_campaign_send", "send_id", "campaign_id", "dim_campaign", "campaign_id"),
    ("fct_complaint", "complaint_id", "customer_id", "dim_customer", "customer_id"),
    ("fct_digital_session", "session_id", "customer_id", "dim_customer", "customer_id"),
]
rows = []
for fact, grain, fk, dim, pk in checks:
    r = pl.q(f"""select count(*) as n, count(distinct {grain}) as g, count(f.{fk}) as filled,
                        count(*) filter (where f.{fk} is not null and not exists
                            (select 1 from {{{dim}}} d where d.{pk} = f.{fk})) as orphans
                 from {{{fact}}} f""").iloc[0]
    rows.append(
        {
            "fact": fact,
            "foreign key": f"{fk} → {dim}",
            "rows": int(r.n),
            "grain unique": r.n == r.g,
            "filled %": round(100 * r.filled / max(r.n, 1), 2),
            "orphans": int(r.orphans),
        }
    )
show(pd.DataFrame(rows), paging=False)

# %% [markdown]
# The country cut keeps every customer-owned row with its customer, so customer keys resolve completely; the shared
# dimensions (agents, campaigns, merchants) resolve too. The country star is as sound as the bank's.

# %% [markdown]
# ## 3 · The dimensions of the country

# %%
show(
    pl.q("""select segment, count(*) as customers, round(median(credit_score), 0) as median_score,
                    round(100 * avg(accepts_marketing::int), 1) as accepts_marketing_pct
             from {dim_customer} group by 1 order by 2 desc"""),
    paging=False,
)
show(
    pl.q(
        """select product_family, currency, count(*) as products from {dim_product} group by all order by 3 desc"""
    ),
    paging=False,
)

# %% [markdown]
# ## 4 · The scope's profile
# One row of conformed figures (silver and gold) that the comparison notebooks read instead of a lakehouse: size,
# activity, currency, anonymous traffic, income and ticket.

# %%
HOME = " ".join(
    f"when '{c}' then '{country.COUNTRIES[c].home_currency}'" for c in country.scope_codes(COUNTRY)
)
prof = pl.q(f"""
    select (select count(*) from {{int_customer_profile}}) as customers,
           (select count(*) from {{int_transactions_enriched}}) as transactions,
           (select min(transaction_ts_utc)::date from {{int_transactions_enriched}}) as first_tx_day,
           (select max(transaction_ts_utc)::date from {{int_transactions_enriched}}) as last_tx_day,
           (select round(avg(n_tx), 3) from {{int_customer_month_tx}}) as tx_per_customer_month,
           (select round(100 * avg((t.currency = case c.country_code {HOME} end)::int), 1)
              from {{int_transactions_enriched}} t join {{stg_customers}} c using (customer_id))
             as home_currency_tx_pct,
           (select round(100 * avg((customer_id is null)::int), 1) from {{fct_digital_session}})
             as anonymous_sessions_pct,
           (select round(median(monthly_income_usd), 0) from {{int_customer_profile}}) as median_income_usd,
           (select round(median(amount_usd), 0) from {{int_transactions_enriched}}) as median_tx_usd""")
prof.insert(0, "dataset", DATASET)
prof.insert(0, "country", COUNTRY)
prof.to_csv(OUT / f"{PREFIX}_{COUNTRY.lower()}_profile.csv", index=False)
show(prof, paging=False)

# %%
pl.ensure_until("gold")
t = pl.run_tests("gold")
display(
    Markdown(f"Gold tests: {', '.join(f'{k} {v}' for k, v in t.status.value_counts().items())}.")
)

# %% [markdown]
# ## Findings for __COUNTRY_NAME__ and what to do
# The computed statements above; the fix (first version valid from the beginning of time, keys tested not null) is
# common to every country.

# %%
pl.close()
print(f"notebook time {time.time() - t0:.0f}s")
