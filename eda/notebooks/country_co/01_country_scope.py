# %% [markdown]
# # 01 · Scope and lake (Colombia)
# **Country series · Colombia** · *generated from `notebooks/country_template` by
# `scripts/build_country_notebooks.py`: edit the template, not this file*
#
# ## Why analyse one country at a time
# A bank that operates in Mexico, Colombia and Argentina runs three businesses: three currencies, three regulators,
# three calendars, three time zones, and customers who behave differently. Averages over the three hide all of it: an
# Argentine amount in pesos is about 350 times a dollar amount, a Mexican holiday is a working day in Colombia, and a
# rule calibrated on the blend can be wrong in every country at once. This series rebuilds the **entire platform on
# Colombia alone**, from lossless bronze to the audit gates, and takes every decision (contract baselines,
# imputations, anomaly thresholds, model choices) on that country's own data.
#
# | notebook | question for Colombia |
# |---|---|
# | 01 | what is in the lake, and how big it is |
# | 02 | which contract findings does the data have |
# | 03 | does the global contract fit; how did the schema and distributions evolve |
# | 04 | local time, the calendar (holidays, paydays), and what they explain |
# | 05 | currencies, conversion, imputation and the monthly grid |
# | 06 | history, keys and the star schema |
# | 07–08 | the marts: service, credit, collections, AML, campaigns |
# | 09 | point-in-time features plus calendar features |
# | 10–11 | graph, knowledge, privacy and serving |
# | 12 | the integrity rules against global and scoped SLOs, and the gates |
# | 13 | anomalies and change points in the activity |
# | 14 | which targets are learnable: out-of-time evaluation of the candidate models |

# %%
import sys
import time
from pathlib import Path

sys.path.insert(0, "../../src")
import duckdb
import pandas as pd
import plotly.express as px
from IPython.display import Markdown, display
from itables import show

from latam_eda import country, theme
from latam_eda import pipeline as pipe

COUNTRY = "CO"
DATASET = "main"
PREFIX = "country"
CTRY = country.SCOPES[COUNTRY]
OUT = Path("../../reports/tables")
OUT.mkdir(parents=True, exist_ok=True)
theme.register()
t0 = time.time()
pl = country.session(COUNTRY, DATASET)
print(
    f"{CTRY.title} ({DATASET} dataset): "
    + (
        "home currency, time zone and calendar per customer's country"
        if COUNTRY == "ALL"
        else f"home currency {CTRY.home_currency}, UTC{CTRY.utc_offset:+d}"
    )
    + f"; scratch data/tmp/{DATASET}/{COUNTRY.lower()}/"
)

# %% [markdown]
# ## 0 · The dataset
# Main's lake, as landed and proven byte-exact. The same template runs on the quarantined backup in the
# backup-as-main series (`notebooks/backup_*`).

# %%
if DATASET == "backup":
    bk = country.build_backup_lake(pipe.default_lake(pl.repo), pl.source_lake)
    show(bk, paging=False)
    gone = bk[bk.rule.str.startswith("missing")].table.unique()
    tx_b = bk[(bk.zone == "bronze_raw") & (bk.table == "transactions")].iloc[0]
    display(
        Markdown(
            f"**Bank-wide, the backup lacks {len(gone)} of main's tables ({', '.join(gone)})** and holds "
            f"{int(tx_b.rows_backup):,} transactions in its bronze zone against main's {int(tx_b.rows_main):,} "
            f"({100 * tx_b.rows_backup / tx_b.rows_main:.0f} %). Every model reading the missing tables builds empty "
            "below; every notebook says what that costs."
        )
    )

# %% [markdown]
# ## 1 · How the country lake is cut
# The country lake is a **lossless subset** of bronze: rows are copied unchanged, lineage included. The rules:
# * `customers` by their country; every customer-owned table by `customer_id`, so every join stays complete inside
#   the country;
# * digital events of identified customers by `customer_id`; **anonymous** events by IP country (their only country
#   signal);
# * enterprise reference data (branches, agents, campaigns, exchange rates) is **shared**, not cut;
# * the quarantined copy is cut the same way; the correction log and the proof manifests are shared.

# %%
cut = country.scope_summary(pl)
show(cut, paging=False)
share = cut[(cut.zone == "bronze_raw") & (cut.table == "customers")].kept_pct.iloc[0]
display(
    Markdown(
        f"**{CTRY.title} holds {share:.1f} % of the bank's customers.** Customer-owned tables keep about the same "
        "share; digital events keep a little more or less depending on the anonymous traffic attributed by IP."
        if COUNTRY != "ALL"
        else f"**The whole bank: {int(cut[cut.zone == 'bronze_raw'].rows_kept.sum()):,} bronze rows in "
        f"{int((cut.zone == 'bronze_raw').sum())} tables, {int(cut[cut.zone == 'holdout_raw'].rows_kept.sum()):,} "
        "holdout rows.**"
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
# The scope's lakehouse is built by the same compiled dbt SQL as the bank-wide one (pipeline series), compiled against
# the scope's lake. One step differs, and it is a decision taken in notebook 03: the contract's drift baselines are
# re-estimated on the scope's own reference window.

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
# ## 3 · Size and time coverage (raw bronze)
# Rows and the first and last partition of every table: the coverage a model, a mart or a drift check can rely on.
# This table is written to `reports/tables` so the comparisons never need a lakehouse.

# %%
con = duckdb.connect()
size = []
for r in cut.itertuples():
    zone_dir = country.BACKUP_DIR if r.zone == "backup" else r.zone
    glob = f"{pl.lake}/{zone_dir}/{r.table}/*/*.parquet"
    first, last, days = con.sql(f"""
        select min(_partition_date)::date, max(_partition_date)::date, count(distinct _partition_date)
        from read_parquet('{glob}', union_by_name = true, hive_partitioning = false)""").fetchone()
    size.append(
        {
            "dataset": DATASET,
            "country": COUNTRY,
            "zone": r.zone,
            "table": r.table,
            "rows": int(r.rows_kept),
            "first_partition": first,
            "last_partition": last,
            "partitions": int(days),
        }
    )
con.close()
size = pd.DataFrame(size)
size.to_csv(OUT / f"{PREFIX}_{COUNTRY.lower()}_size.csv", index=False)
show(size, paging=False)
events = size[(size.zone == "bronze_raw") & (size.partitions > 1)]
fig = px.timeline(
    events.assign(
        first_partition=pd.to_datetime(events.first_partition),
        last_partition=pd.to_datetime(events.last_partition),
    ),
    x_start="first_partition",
    x_end="last_partition",
    y="table",
    title=f"{CTRY.title}: time span of each event table (bronze)",
)
fig.update_layout(height=320, yaxis_title=None)
fig.show()
spans = events.set_index("table")
short = spans[spans.last_partition < spans.last_partition.max()]
display(
    Markdown(
        f"**Event tables run from {spans.first_partition.min()} to {spans.last_partition.max()}.** "
        + (
            "Every event table covers the same window."
            if not len(short)
            else "Tables that stop early: "
            + ", ".join(
                f"`{t}` (last partition {r.last_partition}, {r.partitions} days)"
                for t, r in short.iterrows()
            )
            + ". Every window-based feature, label and mart computed after that date sees no activity from them: "
            "the notebooks below report the consequences."
        )
    )
)

# %% [markdown]
# ## 4 · The scope at a glance (raw bronze)

# %%
glance = pl.con.sql(f"""
    with c as (select * from read_parquet('{pl.lake}/bronze_raw/customers/*/*.parquet', union_by_name = true)),
         p as (select * from read_parquet('{pl.lake}/bronze_raw/products/*/*.parquet', union_by_name = true)),
         t as (select * from read_parquet('{pl.lake}/bronze_raw/transactions/*/*.parquet', union_by_name = true))
    select (select count(*) from c) as customers, (select count(*) from p) as products,
           (select count(*) from t) as transactions,
           (select count(distinct date_trunc('month', _partition_date)) from t) as months_with_transactions,
           round((select count(*) from t) / (select count(*) from c)
                 / greatest((select count(distinct date_trunc('month', _partition_date)) from t), 1), 3)
             as tx_per_customer_month
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
if COUNTRY == "ALL":
    display(
        Markdown(
            "**The bank's transactions by currency:** "
            + ", ".join(f"{k} {100 * v / loc.sum():.1f} %" for k, v in loc.items())
            + ". Three scales in one column: every amount statistic is computed per currency (or in USD), never "
            "pooled. The country scopes show where each currency lives."
        )
    )
else:
    local_share = 100 * loc.get(CTRY.home_currency, 0) / loc.sum()
    display(
        Markdown(
            f"**{local_share:.1f} % of {CTRY.name}'s transactions are in {CTRY.home_currency}**, the rest in "
            + ", ".join(
                f"{k} ({100 * v / loc.sum():.1f} %)"
                for k, v in loc.items()
                if k != CTRY.home_currency
            )
            + ". "
            + (
                "There are no peso accounts at all: Mexican customers bank in US dollars, while their incomes are "
                "reported in pesos. Every income-based ratio must convert incomes, never amounts."
                if local_share == 0
                else "Amounts must be analysed per currency (or converted): pooling pesos and dollars mixes two scales "
                "that differ by orders of magnitude."
            )
        )
    )

# %% [markdown]
# ## Findings for Colombia and what to do
# The computed statements above are the findings of this notebook; the comparisons (`notebooks/country_compare`,
# `notebooks/dataset_compare`) put them side by side. The method decisions taken here hold for every scope:
# * cut by customer, anonymous traffic by IP country, reference data shared;
# * analyse amounts per currency, convert incomes, never pool scales;
# * know each table's time coverage before trusting any window computed on it.

# %%
pl.close()
print(f"notebook time {time.time() - t0:.0f}s")
