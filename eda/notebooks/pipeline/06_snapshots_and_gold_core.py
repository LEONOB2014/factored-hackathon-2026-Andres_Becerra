# %% [markdown]
# # 06 · Snapshots and the gold core: history, keys and the star schema
# **Pipeline series** · task groups `snapshots` and `gold` (core): `snapshots/`, `models/gold/core`
#
# ## What happens here
# Silver describes the source; gold describes the **business**, in Kimball's dimensional form:
# * **SCD Type 2 snapshots** keep the history of the mutable dimensions (customers, products, agents, branches): a
#   change never overwrites, it closes the current version and opens a new one.
# * **Dimensions** (`dim_*`) give each version a **surrogate key** and a validity interval.
# * **Facts** (`fct_*`) record events at a declared **grain** and point to the dimension version that was valid when
#   the event happened (a point-in-time join).
#
# The snapshots run in their own task group, after silver and before gold, because they read the freshly built
# staging views and gold reads the snapshots.

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
pl.ensure_until("silver")
SNAPS = ["snap_branches", "snap_customers", "snap_products", "snap_service_agents"]
CORE = sorted(
    n for n in pl.catalog().query("layer == 'gold'")["node"] if n.startswith(("dim_", "fct_"))
)
print("snapshots:")
pl.build_set(SNAPS)
print("gold core:")
built = pl.build_set(CORE)

# %% [markdown]
# ## 1 · How an SCD2 snapshot works
# The snapshots use dbt's **check strategy** on `row_hash` (notebook 04): on each run, a key whose hash changed gets
# its current row closed (`dbt_valid_to = now`) and a new row opened; a key that disappeared from the source is closed
# (`hard_deletes: invalidate`); a new key opens its first row. The timestamp strategy was rejected because
# `last_updated` is in the future for 6 % of rows (R06, R07).
#
# The walkthrough builds once, so every key has exactly one version. To see the mechanics, the cell below replays a
# **second run** on six customers in temporary tables: two change segment, one disappears, three stay the same.

# %%
pl.con.sql(
    """
    create or replace temp table run1 as
    select customer_id, segment, credit_score, row_hash, registration_date
    from (select * from {stg} order by customer_id limit 6)""".format(
        stg=pl.relation(pl.key("stg_customers"))
    )
)
pl.con.sql("""
    create or replace temp table snap as
    select *, timestamp '2026-10-01 02:00' as dbt_valid_from, null::timestamp as dbt_valid_to from run1""")
# run 2: customers 1 and 2 change segment, customer 3 disappears
pl.con.sql("""
    create or replace temp table run2 as
    with r as (select *, row_number() over (order by customer_id) as i from run1)
    select customer_id,
           case when i in (1, 2) then 'Premium' else segment end as segment, credit_score,
           case when i in (1, 2) then md5(row_hash || 'changed') else row_hash end as row_hash, registration_date
    from r where i <> 3""")
# dbt's merge, written out: close changed and deleted rows, insert new versions
pl.con.sql("""
    update snap set dbt_valid_to = timestamp '2026-10-02 02:00'
    where dbt_valid_to is null and (customer_id not in (select customer_id from run2)
          or row_hash <> (select r.row_hash from run2 r where r.customer_id = snap.customer_id))""")
pl.con.sql("""
    insert into snap select r.*, timestamp '2026-10-02 02:00', null from run2 r
    join snap s on s.customer_id = r.customer_id and s.dbt_valid_to = timestamp '2026-10-02 02:00'""")
scd = pl.con.sql("""
    select customer_id, segment,
           row_number() over (partition by customer_id order by dbt_valid_from) as version_no,
           dbt_valid_from, dbt_valid_to, dbt_valid_to is null as is_current, registration_date
    from snap order by customer_id, version_no""").df()
scd["customer_sk"] = scd.apply(lambda r: f"md5({r.customer_id}|{r.version_no})", axis=1)
scd["valid_from (dim)"] = scd.apply(
    lambda r: r.registration_date if r.version_no == 1 else r.dbt_valid_from, axis=1
)
show(scd, paging=False)

# %% [markdown]
# **Reading the result.**
# * Customers 1 and 2 now have **two versions**: version 1 closed on 2 October, version 2 open (`is_current`).
# * Customer 3 has one **closed** version and no open one: it no longer exists in the source, but its history stays
#   (facts dated before the deletion still find it).
# * The surrogate key hashes the **version number**, not the snapshot time, so rebuilding the dimension from the same
#   snapshot table gives the same keys (notebook 11 of the model-risk series: reproducibility).
# * `dim_customer` sets version 1's `valid_from` to the **registration date**, not the snapshot time: before the
#   first snapshot the platform has no history, and the earliest knowledge it has is "this is how the customer was
#   registered". Section 4 shows what that convention costs in this data.

# %% [markdown]
# ## 2 · The snapshots and dimensions as built

# %%
snaps = pd.DataFrame(
    [
        {
            "snapshot": s,
            "rows": pl.rows(s),
            "keys": pl.q(
                f"select count(distinct {pl.nodes[pl.key(s)]['config']['unique_key']}) from {{{s}}}"
            ).iloc[0, 0],
            "open versions": pl.q(f"select count(*) from {{{s}}} where dbt_valid_to is null").iloc[
                0, 0
            ],
        }
        for s in SNAPS
    ]
)
show(snaps, paging=False)
dims = pl.q("""
    select 'dim_customer' as dimension, count(*) as n_rows, count(distinct customer_id) as natural_keys,
           count(distinct customer_sk) as surrogate_keys, min(valid_from) as earliest_valid_from,
           max(valid_from) as latest_valid_from from {dim_customer}
    union all
    select 'dim_product', count(*), count(distinct product_id), count(distinct product_sk), min(valid_from),
           max(valid_from) from {dim_product}""")
show(dims, paging=False)

# %% [markdown]
# One version per key: this lakehouse has observed the source once. **History accumulates only from the first
# snapshot onward**; each daily run that sees a changed hash adds a version. This is why the collections mart cannot
# compute roll rates yet: days-past-due history starts the day the platform starts.

# %% [markdown]
# ## 3 · The other dimensions

# %%
show(
    pl.q("""select 'dim_merchant' as dimension, count(*) as n_rows, 'derived from transactions (no merchant master)' as note
            from {dim_merchant}
            union all select 'dim_date', count(*), '2020-01-01 to 2026-12-31, weekday, weekend, historical zone' from {dim_date}
            union all select 'dim_country', count(*), 'ISO code, currency, offset, data-residency region' from {dim_country}
            union all select 'dim_agent', count(*), 'agents without names or contacts' from {dim_agent}
            union all select 'dim_branch', count(*), 'branches without contacts' from {dim_branch}
            union all select 'dim_campaign', count(*), 'marketing campaigns' from {dim_campaign}"""),
    paging=False,
)
show(pl.q("select * from {dim_country} order by country_code"), paging=False)

# %% [markdown]
# * `dim_merchant` has **24 merchants** derived from transactions, keyed by `md5(merchant_name)`. Only 23 % of
#   transactions name a merchant (purchases), so merchant analytics cover a quarter of the activity.
# * `dim_country.residency_region` encodes where each country's personal data may be stored in the cloud layer
#   (Mexico in `northamerica-south1`; Colombia and Argentina in São Paulo pending legal sign-off, see ADR-006). The
#   BigQuery publish uses it to route rows: data residency is a column, not a convention.

# %% [markdown]
# ## 4 · Facts and their keys: the point-in-time join
# `fct_transaction` attaches the customer and product **version valid at the transaction time**:
# `t.ts >= dim.valid_from and t.ts < dim.valid_to`. Count how often that finds a version.

# %%
cov = pl.q("""
    select count(*) as transactions,
           count(customer_sk) as with_customer_sk, count(product_sk) as with_product_sk,
           count(*) filter (where customer_sk is null) as missing_customer_sk,
           count(*) filter (where product_sk is null) as missing_product_sk,
           count(*) filter (where customer_sk is null or product_sk is null) as missing_either
    from {fct_transaction}""")
show(cov, paging=False)
why = pl.q("""
    select count(*) filter (where t.customer_sk is null) as missing_customer_sk,
           count(*) filter (where t.customer_sk is null and t.transaction_ts_utc < c.registration_date)
             as of_which_before_registration,
           count(*) filter (where t.product_sk is null) as missing_product_sk,
           count(*) filter (where t.product_sk is null and t.dq_r01_before_product_open) as of_which_before_opening
    from {fct_transaction} t join {int_customer_profile} c using (customer_id)""")
show(why, paging=False)
yr = pl.q("""select year(transaction_ts_utc) as year, count(*) as transactions,
                    round(100 * avg((customer_sk is null)::int), 1) as missing_customer_sk_pct,
                    round(100 * avg((product_sk is null)::int), 1) as missing_product_sk_pct
             from {fct_transaction} group by 1 order by 1""")
fig = px.bar(
    yr.melt(id_vars="year", value_vars=["missing_customer_sk_pct", "missing_product_sk_pct"]),
    x="year",
    y="value",
    color="variable",
    barmode="group",
    title="Transactions whose point-in-time join finds no dimension version (%)",
)
fig.update_layout(height=320, yaxis_title="%", legend_title=None)
fig.show()

# %% [markdown]
# **Finding: one transaction in five has no customer version and one in five no product version (a third have at
# least one key missing).** Every one of them is dated **before** the customer registered or the product was opened,
# so it falls before version 1's `valid_from`. The share falls from 34 % of 2023 transactions to 3 % of 2026 ones:
# registration dates are spread over 2018–2026 and transaction dates over 2023–2026 independently, so recently
# registered customers carry "earlier" activity. It is a generator artefact (rules R01 and R02 measure its cousins),
# but the platform's **validity convention turns it into dangling keys**.
#
# **Why it has not hurt yet.** No mart joins through `customer_sk` or `product_sk`: they read
# `int_customer_profile` and `int_products_enriched` (current state) by natural key. An analyst or a BI tool using the
# star schema as designed (`fct_transaction join dim_customer using (customer_sk)`) would silently lose 19 % of
# transactions and a third of 2023.
#
# **What to do (recommended).** Change the convention for version 1 to **valid from the beginning of time**
# (`timestamp '1900-01-01'`), the standard Kimball choice for the first observed version: before the first snapshot,
# the earliest known state is the best available description. Keep `registration_date` and `opening_date` as
# attributes for anyone who needs them, and add a `not_null` test on `fct_transaction.customer_sk` and
# `product_sk` (severity `error`). The cost is a one-line change in two dimensions and a full rebuild; the surrogate
# keys do not change (they hash the version number).

# %% [markdown]
# ## 5 · Every fact against its dimensions
# Grain checks (is the declared key unique?) and foreign-key coverage for each fact.

# %%
checks = [
    ("fct_transaction", "transaction_id", "customer_id", "dim_customer", "customer_id"),
    ("fct_transaction", "transaction_id", "merchant_id", "dim_merchant", "merchant_id"),
    ("fct_transaction", "transaction_id", "date_key", "dim_date", "date_key"),
    ("fct_interaction", "interaction_id", "agent_id", "dim_agent", "agent_id"),
    ("fct_interaction", "interaction_id", "customer_id", "dim_customer", "customer_id"),
    ("fct_campaign_send", "send_id", "campaign_id", "dim_campaign", "campaign_id"),
    ("fct_campaign_send", "send_id", "customer_id", "dim_customer", "customer_id"),
    ("fct_complaint", "complaint_id", "customer_id", "dim_customer", "customer_id"),
    ("fct_complaint", "complaint_id", "related_branch_id", "dim_branch", "branch_id"),
    ("fct_digital_session", "session_id", "customer_id", "dim_customer", "customer_id"),
]
rows = []
for fact, grain, fk, dim, pk in checks:
    r = pl.q(f"""
        select count(*) as fact_rows, count(distinct {grain}) as distinct_grain, count(f.{fk}) as fk_not_null,
               count(*) filter (where f.{fk} is not null and not exists
                   (select 1 from {{{dim}}} d where d.{pk} = f.{fk})) as fk_orphans
        from {{{fact}}} f""").iloc[0]
    rows.append(
        {
            "fact": fact,
            "grain unique": r.fact_rows == r.distinct_grain,
            "foreign key": f"{fk} → {dim}",
            "rows": r.fact_rows,
            "fk filled %": round(100 * r.fk_not_null / r.fact_rows, 2),
            "orphans": r.fk_orphans,
        }
    )
star = pd.DataFrame(rows)
show(star, paging=False)

# %% [markdown]
# **Every grain is unique and every filled foreign key in the facts finds its dimension** (0 orphans). The broken
# branch references live in the dimensions themselves: customers' registration branches and agents' assigned branches
# do not exist (R23, R24), while the branches that complaints name do. Fill rates tell the rest: 23 % of transactions
# name a merchant, 80 % of sessions are identified, 29 % of complaints name a branch.

# %% [markdown]
# ## 6 · Facts that carry a data-quality flag or a privacy decision

# %%
show(
    pl.q("""select count(*) as complaints, count(affected_product_id) as name_a_product,
                   count(*) filter (where dq_r25_product_not_owned) as product_of_another_customer
            from {fct_complaint}"""),
    paging=False,
)
show(
    pl.q("""select count(*) as sessions, count(customer_id) as identified, round(avg(n_events), 2) as avg_events,
                   max(n_events) as max_events, count(distinct ip_token) as distinct_ip_tokens
            from {fct_digital_session}"""),
    paging=False,
)
show(
    pl.q("""select count(*) as interactions, count(accent_matched) as accent_known,
                   round(100 * avg(accent_matched::int), 1) as matched_pct_of_known,
                   round(100 * avg(was_escalated::int), 1) as escalated_pct
            from {fct_interaction}"""),
    paging=False,
)

# %% [markdown]
# * **Complaints:** every complaint that names a product names **someone else's** product (43,345 of 43,345, R25).
#   The fact keeps the column (it is what the source said) and the flag `dq_r25_product_not_owned`; the disputes mart
#   (notebook 07) must never use it to find the disputed transaction.
# * **Sessions:** 1.79 M sessions built from 15.2 M events (grain: session). The IP address becomes a token, because an
#   IP is personal data under the LGPD and the Mexican and Argentine laws. IPs are almost unique per session
#   (1,785,698 distinct tokens for 1,786,403 sessions), so "shared device" signals are rare; notebook 10 counts the IPs
#   that link different customers in the graph.
# * **Interactions:** the **customer's** detected accent is removed (a proxy for region and ethnicity, kept only in the
#   fairness table); the agent's accent and the match flag stay as operational quality attributes. Where both accents
#   are known (70 % of calls), 81 % are accent-matched. Whether matching affects resolution is a fairness question the CX journey mart can answer.

# %% [markdown]
# ## 7 · Explorer: any gold core model

# %%
w_g = w.Dropdown(options=CORE, value="fct_transaction", description="model")
out_g = w.Output()


def draw_core(*_):
    with out_g:
        out_g.clear_output()
        p = pl.profile(w_g.value)
        display(
            Markdown(
                f"**{w_g.value}** · {pl.rows(w_g.value):,} rows · "
                f"{pl.nodes[pl.key(w_g.value)].get('description', '')[:200]}"
            )
        )
        show(
            p[["column_name", "data_type", "null_pct", "distinct_approx", "min", "max"]],
            paging=False,
        )
        show(pl.safe(pl.q(f"select * from {{{w_g.value}}} limit 5")), paging=False)


w_g.observe(draw_core, "value")
draw_core()
display(w.VBox([w_g, out_g]))

# %% [markdown]
# ## Findings and what to do
# 1. **The snapshots work as designed** (check strategy on business hashes, deletes invalidate), with one version per
#    key today. History starts with the platform: every use case that needs change over time (roll rates, consent at
#    send time, score migration) gains a day of history per run from now on. **Keep the daily schedule running** in
#    any environment meant to demonstrate history.
# 2. **Fix the validity convention of version 1** (high priority, small change). 19 % of transactions find no customer
#    version and 19 % no product version because they predate registration or opening. Make version 1 valid from the
#    beginning of time and test the keys `not_null`.
# 3. **Grains are unique and fact keys resolve.** Only the customers' and agents' branch references are broken (R23,
#    R24), so branch analytics by registration or assignment are not possible on this data.
# 4. **Privacy decisions are visible in the gold columns**: no direct identifiers, IPs tokenised, the customer's accent
#    removed, and residency region carried by the country dimension.
# 5. **Marts use current state, not the star's point-in-time keys.** That is correct for questions about "now"
#    (balances, eligibility, next action). Any historical analysis (what segment was this customer in when they were
#    declined?) must join through the surrogate keys, after fix 2.

# %%
pl.close()
print(f"notebook time {time.time() - t0:.0f}s")
