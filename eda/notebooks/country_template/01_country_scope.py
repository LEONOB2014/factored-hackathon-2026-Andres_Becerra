# %% [markdown]
# # 01 · Country scope and the country lake (__COUNTRY_NAME__)
# **Country series · __COUNTRY_NAME__** · *generated from `notebooks/country_template` by
# `scripts/build_country_notebooks.py`: edit the template, not this file*
#
# ## Why analyse one country at a time
# A bank that operates in Mexico, Colombia and Argentina runs three businesses: three currencies, three regulators,
# three calendars, three time zones, and customers who behave differently. Averages over the three hide all of it: an
# Argentine amount in pesos is about 350 times a dollar amount, a Mexican holiday is a working day in Colombia, and a
# rule calibrated on the blend can be wrong in every country at once. This series rebuilds the **entire platform on
# __COUNTRY_NAME__ alone**, from lossless bronze to the audit gates, and takes every decision (contract baselines,
# imputations, anomaly thresholds, model choices) on that country's own data.
#
# | notebook | question for __COUNTRY_NAME__ |
# |---|---|
# | 01 | what is in the country lake, and what is shared with the other countries |
# | 02 | which contract findings does the country's data have |
# | 03 | does the global contract fit the country; how did its schema and distributions evolve |
# | 04 | local time, the country's calendar (holidays, paydays), and what they explain |
# | 05 | currencies, conversion, imputation and the monthly grid in this country |
# | 06 | history, keys and the star schema |
# | 07–08 | the marts: service, credit, collections, AML, campaigns |
# | 09 | point-in-time features plus calendar features |
# | 10–11 | graph, knowledge, privacy and serving |
# | 12 | the integrity rules against global and country SLOs, and the gates |
# | 13 | anomalies and change points in the country's activity |
# | 14 | which targets are learnable: out-of-time evaluation of the candidate models |

# %%
import sys
import time

sys.path.insert(0, "../../src")
import plotly.express as px
from IPython.display import Markdown, display
from itables import show

from latam_eda import country, theme
from latam_eda import pipeline as pipe

COUNTRY = "__COUNTRY__"
CTRY = country.COUNTRIES[COUNTRY]
theme.register()
t0 = time.time()
pl = country.session(COUNTRY)
print(
    f"{CTRY.name}: home currency {CTRY.home_currency}, UTC{CTRY.utc_offset:+d}, scratch lakehouse data/tmp/country/{COUNTRY.lower()}/"
)

# %% [markdown]
# ## 1 · How the country lake is cut
# The country lake is a **lossless subset** of bronze: rows are copied unchanged, lineage included. The rules:
# * `customers` by their country; every customer-owned table by `customer_id`, so every join stays complete inside
#   the country;
# * digital events of identified customers by `customer_id`; **anonymous** events by IP country (their only country
#   signal);
# * enterprise reference data (branches, agents, campaigns, exchange rates) is **shared**, not cut;
# * the quarantined backup copy is cut the same way; the correction log and the proof manifests are shared.

# %%
cut = country.build_country_lake(COUNTRY, pipe.default_lake(pl.repo), pl.lake)
show(cut, paging=False)
share = cut[(cut.zone == "bronze_raw") & (cut.table == "customers")].kept_pct.iloc[0]
display(
    Markdown(
        f"**{CTRY.name} holds {share:.1f} % of the bank's customers.** Customer-owned tables keep about the same "
        "share; digital events keep a little more or less depending on the anonymous traffic attributed by IP."
    )
)

# %%
fig = px.bar(
    cut[cut.zone == "bronze_raw"].sort_values("kept_pct"),
    x="kept_pct",
    y="table",
    orientation="h",
    color="rule",
    title=f"Share of each bronze table kept for {CTRY.name} (%)",
)
fig.update_layout(height=420, yaxis_title=None, legend_title=None)
fig.show()

# %% [markdown]
# **Decision: anonymous events by IP country.** An anonymous event has no customer, so the only way to place it is the
# IP's country. The alternative (dropping anonymous traffic) would bias digital funnels towards logged-in users. The
# cost: anonymous traffic labelled with the other spelling of a country name, or with a VPN country, lands elsewhere.
# Notebook 02 measures what the attribution brought in.

# %% [markdown]
# ## 2 · The pipeline is the same; the data is not
# The country lakehouse is built by the same compiled dbt SQL as the bank-wide one (pipeline series), compiled against
# the country lake. One step differs, and it is a decision taken in notebook 03: the contract's drift baselines are
# re-estimated on the country's own reference window.

# %%
pl.build_layer("seeds", verbose=False)
cat = pl.catalog()
show(
    cat.groupby(["layer", "materialized"], observed=True).size().unstack(fill_value=0), paging=False
)
fwd = pl.forward_dependencies()
show(fwd, paging=False)

# %% [markdown]
# The forward-dependency defect of the bank-wide pipeline (credit eligibility built before its features) exists here
# too: it is in the DAG, not in the data.

# %% [markdown]
# ## 3 · The country at a glance (raw bronze)

# %%
glance = pl.con.sql(f"""
    with c as (select * from read_parquet('{pl.lake}/bronze_raw/customers/*/*.parquet', union_by_name = true)),
         p as (select * from read_parquet('{pl.lake}/bronze_raw/products/*/*.parquet', union_by_name = true)),
         t as (select * from read_parquet('{pl.lake}/bronze_raw/transactions/*/*.parquet', union_by_name = true))
    select (select count(*) from c) as customers, (select count(*) from p) as products,
           (select count(*) from t) as transactions,
           round((select count(*) from t) / (select count(*) from c) / 35.0, 3) as tx_per_customer_month
    """).df()
show(glance, paging=False)
cur = pl.con.sql(f"""
    select 'products' as entity, currency, count(*) as n_rows
    from read_parquet('{pl.lake}/bronze_raw/products/*/*.parquet', union_by_name = true) group by all
    union all
    select 'transactions', currency, count(*)
    from read_parquet('{pl.lake}/bronze_raw/transactions/*/*.parquet', union_by_name = true) group by all
    order by 1, 3 desc""").df()
fig = px.bar(
    cur,
    x="entity",
    y="n_rows",
    color="currency",
    barmode="stack",
    title=f"Currencies of {CTRY.name}'s products and transactions",
)
fig.update_layout(height=320, xaxis_title=None)
fig.show()
loc = cur[(cur.entity == "transactions")].set_index("currency")["n_rows"]
local_share = 100 * loc.get(CTRY.home_currency, 0) / loc.sum()
display(
    Markdown(
        f"**{local_share:.1f} % of {CTRY.name}'s transactions are in {CTRY.home_currency}**, the rest in "
        + ", ".join(
            f"{k} ({100 * v / loc.sum():.1f} %)" for k, v in loc.items() if k != CTRY.home_currency
        )
        + ". "
        + (
            "There are no peso accounts at all: Mexican customers bank in US dollars, while their incomes are reported in "
            "pesos. Every income-based ratio must convert incomes, never amounts."
            if local_share == 0
            else "Amounts must be analysed per currency (or converted): pooling pesos and dollars mixes two scales that differ "
            "by orders of magnitude."
        )
    )
)

# %% [markdown]
# ## Findings for __COUNTRY_NAME__ and what to do
# The computed statements above are the findings of this notebook; the cross-country comparison
# (`notebooks/country_compare`) puts them side by side. The method decisions taken here hold for all countries:
# * cut by customer, anonymous traffic by IP country, reference data shared;
# * analyse amounts per currency, convert incomes, never pool scales.

# %%
pl.close()
print(f"notebook time {time.time() - t0:.0f}s")
