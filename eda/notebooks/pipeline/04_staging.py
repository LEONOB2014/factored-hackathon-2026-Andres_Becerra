# %% [markdown]
# # 04 · Staging: names, vocabularies, hashes and the restricted zone
# **Pipeline series** · task group `silver`, part 3: `models/silver/staging`
#
# ## What happens here
# Staging is the last step that looks like the source. Each `stg_*` view takes its typed view and:
# 1. **removes held partitions** (`not_held`, notebook 03) — the only rows silver ever drops;
# 2. **renames** columns into the platform's vocabulary (`transaction_date` → `transaction_ts_utc`,
#    `estimated_monthly_income` → `monthly_income_local`) and drops lineage and finding columns;
# 3. **normalises vocabularies by joining seeds** (`country_codes`: raw spelling → ISO code, currency, UTC offset);
# 4. adds a **`row_hash`** of the business columns of each mutable dimension, which the SCD2 snapshots compare;
# 5. keeps **personal data** (names, documents, contacts, IPs, free text) in a restricted schema: nothing after
#    staging may carry it (the governance test `assert_no_restricted_pii_outside_silver`).
#
# It deliberately does **not** repair values or derive business logic: that happens in conformed silver
# (notebook 05), where every repair carries a data-quality flag.

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
pl.ensure_until("seeds")
STG = sorted(n for n in pl.catalog()["node"] if n.startswith("stg_"))
built = pl.build_set(STG)

# %% [markdown]
# ## 1 · From typed to staged: what each table keeps, renames and adds
# Column sets compared per table. *Dropped* columns are lineage (`_source_file`, `_record_no`, …) and the finding
# list `_dq_issues`: findings live on in `audit.dq_cell_findings` with full lineage, so staging can be lean.

# %%
rows = []
for s in STG:
    t = "typed_" + s.removeprefix("stg_")
    tc = set(pl.columns(t)["column_name"])
    sc = set(pl.columns(s)["column_name"])
    rows.append(
        {
            "table": s.removeprefix("stg_"),
            "typed cols": len(tc),
            "staged cols": len(sc),
            "dropped": ", ".join(sorted(tc - sc)),
            "added or renamed": ", ".join(sorted(sc - tc)),
        }
    )
show(pd.DataFrame(rows), paging=False, maxBytes=0)

# %% [markdown]
# ## 2 · Vocabulary joins: why a `left join` to a seed, and what it would lose
# Four staging models join `country_codes`. A **left** join keeps a row whose spelling is not in the seed (its code
# becomes NULL) instead of dropping it, and a `not_null` test on the code turns the NULL into a visible failure.
# An inner join would silently remove the rows of any new spelling: the most dangerous kind of data loss, because
# every downstream count would still look plausible.

# %%
cov = pl.q("""
    select 'stg_customers.country_code' as joined_column, count(*) as n_rows, count(country_code) as matched
    from {stg_customers}
    union all select 'stg_branches.country_code', count(*), count(country_code) from {stg_branches}
    union all select 'stg_transactions.transaction_country_code', count(*), count(transaction_country_code)
    from {stg_transactions}
    union all select 'stg_digital_events.ip_country_code', count(*), count(ip_country_code) from {stg_digital_events}
""")
cov["unmatched"] = cov["n_rows"] - cov["matched"]
show(cov, paging=False)
show(
    pl.q("""select transaction_country_code, count(*) as transactions from {stg_transactions}
            group by 1 order by 2 desc"""),
    paging=False,
)

# %% [markdown]
# Every spelling maps: **0 unmatched rows** in 21 M joined rows. `México` and `Mexico` both become `MX`
# (notebook 02 showed `Mexico` is the generator's foreign-destination label), and the cross-border destinations
# `US`, `ES`, `BR` carry their own currency and offset for later conversions.

# %% [markdown]
# ## 3 · Timestamps: what the `_utc` suffix assumes, and what the data says
# The source timestamps carry no time zone. Staging names them `*_ts_utc`, and conformed silver derives local time
# with each country's fixed offset. Is that right? The batch window gives the answer: compare each transaction's
# timestamp with its `process_date` (the delivery day).

# %%
lag = pl.q("""select date_diff('hour', process_date::timestamp, transaction_ts_utc) as hours_after_midnight,
                     count(*) as transactions
              from {stg_transactions} group by 1 order by 1""")
fig = px.bar(
    lag,
    x="hours_after_midnight",
    y="transactions",
    title="Transaction time minus process_date midnight (hours)",
)
fig.update_layout(height=320)
fig.show()
hours = pl.q("""select hour(transaction_ts_utc) as hour_utc, count(*) as transactions
                from {stg_transactions} group by 1 order by 1""")
dows = pl.q("""select isodow(transaction_ts_utc) as iso_weekday, count(*) as transactions
               from {stg_transactions} group by 1 order by 1""")
fig = px.bar(hours, x="hour_utc", y="transactions", title="Transactions by hour of day (UTC)")
fig.update_layout(height=300)
fig.show()
fig = px.bar(dows, x="iso_weekday", y="transactions", title="Transactions by weekday (1 = Monday)")
fig.update_layout(height=300)
fig.show()
cv = hours["transactions"].std() / hours["transactions"].mean()
print(f"hour-of-day coefficient of variation: {cv:.4f} (a real bank: 0.6–0.9)")
print(
    f"weekend / weekday volume: {dows.iloc[5:].transactions.mean() / dows.iloc[:5].transactions.mean():.2f}"
)

# %% [markdown]
# **Three facts in three charts.**
# 1. Every transaction lies **6 to 30 hours after midnight of its `process_date`**: each daily file is a 24-hour
#    window starting at 06:00 (51 records spill a few minutes past it). 06:00 UTC is midnight in Mexico City
#    (UTC−6), so the window is exactly the Mexican **business day**, if the timestamps are UTC. The staging naming is
#    the reading that makes the delivery convention coherent; rules R15/R16 (notebook 12) measure the rows that
#    break it.
# 2. **The hour of day is uniform**: about 179 k transactions in every hour (coefficient of variation 0.002). Real
#    card activity has a strong daily cycle, with few transactions at 3 a.m. and peaks at noon and in the evening. The
#    generator draws a uniform time inside the window.
# 3. **The weekday is not uniform**: weekends carry about a third less volume and Mondays a little less than other
#    weekdays. That weekly seasonality is real signal (the AML and forecasting marts use it).
#
# **Implications.**
# * Features such as `local_hour`, "night transaction" or "unusual hour for this customer" (`feat_fraud_realtime_pit`,
#   notebook 09) **carry no information** in this data. Keep them, because a real bank needs them, but do not read
#   anything into their importance or their absence of importance here.
# * The local-time conversion cannot be validated from the data: a uniform distribution looks the same in any time
#   zone. The UTC reading rests on the batch-window convention, which is the strongest evidence available.
#   **Recommendation:** in a real integration, the source contract must state the time zone explicitly
#   (`timestamps: UTC` with an offset in the value). The contract already records the gap (`timestamps: naive`).

# %% [markdown]
# ## 4 · `row_hash`: how the snapshots will recognise a change
# Each mutable dimension (customers, products, agents, branches) gets
# `md5(concat_ws('|', coalesce(cast(col as varchar), '<null>'), …))` over its **business columns**. The SCD2 snapshot
# (notebook 06) opens a new version only when the hash changes.
#
# Two choices matter:
# * `last_updated` is **excluded**: it lies in the future for 6.2 % of customers and 6.3 % of products (R06, R07), so
#   it cannot drive change detection, and a source that bumps it without a business change must not create versions.
# * NULL is encoded as `'<null>'`, so a value that becomes empty is a change (without it, `concat_ws` would skip the
#   NULL and `a|NULL|b` would hash like `a|b`).

# %%
hashes = pl.q("""
    select 'customers' as dimension, count(*) as n_rows, count(distinct customer_id) as keys,
           count(distinct row_hash) as hashes from {stg_customers}
    union all select 'products', count(*), count(distinct product_id), count(distinct row_hash) from {stg_products}
    union all select 'service_agents', count(*), count(distinct agent_id), count(distinct row_hash)
    from {stg_service_agents}
    union all select 'branches', count(*), count(distinct branch_id), count(distinct row_hash) from {stg_branches}""")
show(hashes, paging=False)
hash_expr = [ln.strip() for ln in pl.sql("stg_customers").splitlines() if "md5(" in ln][0]
print("row_hash expression (first 200 characters):\n", hash_expr[:200], "…")

# %% [markdown]
# One hash per key, and every key distinct: the dimensions have no duplicate rows to collapse, and the first
# snapshot will hold exactly one version per entity.

# %% [markdown]
# ## 5 · Personal data stays here
# The restricted columns (seed `restricted_pii_columns`) present in each staging model. These views live in the
# restricted silver schema; conformed silver replaces direct identifiers with tokens (notebook 05), and the
# governance tests fail any model outside silver that exposes one.

# %%
pii = []
for s in STG:
    cols = [c for c in pl.columns(s)["column_name"] if c.lower() in pl.restricted]
    if cols:
        pii.append({"staging model": s, "restricted columns": ", ".join(cols)})
show(pd.DataFrame(pii), paging=False)
show(pl.safe(pl.q("select * from {stg_customers} limit 3")), paging=False)

# %% [markdown]
# ## 6 · The holdout: history versus the replayed stream
# Facts dated on or after `stream_cutoff` (2026-05-18) are **not** in the main bronze zone: they sit in a holdout zone
# replayed through Redpanda and Flink in the streaming demo. Separate staging models read them; the conformed
# transaction model unions both (notebook 05). Training never sees the holdout: it is the "future" a deployed model
# meets.

# %%
show(
    pl.q("""
    select 'transactions' as fact, 'history' as zone, count(*) as n_rows, min(process_date) as first_day,
           max(process_date) as last_day from {stg_transactions}
    union all select 'transactions', 'holdout', count(*), min(process_date), max(process_date)
    from {stg_transactions_holdout}
    union all select 'digital_events', 'history', count(*), min(process_date), max(process_date)
    from {stg_digital_events}
    union all select 'digital_events', 'holdout', count(*), min(process_date), max(process_date)
    from {stg_digital_events_holdout}"""),
    paging=False,
)

# %% [markdown]
# ## 7 · Explorer: any staging model
# Columns with their documentation, a null profile and a masked sample.

# %%
w_s = w.Dropdown(options=STG, value="stg_complaints", description="model")
out_s = w.Output()


def draw_stg(*_):
    with out_s:
        out_s.clear_output()
        prof = pl.profile(w_s.value).merge(
            pl.columns(w_s.value)[["column_name", "description"]], on="column_name"
        )
        display(Markdown(f"**{w_s.value}** · {pl.rows(w_s.value):,} rows"))
        show(
            prof[["column_name", "data_type", "null_pct", "distinct_approx", "description"]],
            paging=False,
        )
        show(pl.safe(pl.q(f"select * from {{{w_s.value}}} limit 5")), paging=False)


w_s.observe(draw_stg, "value")
draw_stg()
display(w.VBox([w_s, out_s]))

# %% [markdown]
# ## Findings and what to do
# 1. **Staging drops nothing** in this data (0 held partitions) and its vocabulary joins match every row (0
#    unmatched among 21 M joined rows). The left-join-plus-test pattern is the right default: keep the row, fail
#    the test.
# 2. **Timestamps are UTC by convention, not by declaration.** The 06:00 batch window equals the Mexican business day
#    only under the UTC reading, which is the platform's choice and the best-supported one. Ask the source owner
#    for an explicit zone in the contract before production.
# 3. **There is no time-of-day signal** (uniform hours), but there **is** weekly seasonality. Time-of-day fraud
#    features are kept for design completeness and must not be judged on this data.
# 4. **Row hashes exclude `last_updated` and encode NULL explicitly**, so the snapshots version real business changes
#    only. Every key has one row and one hash.
# 5. **Personal data is contained in six staging views** (customers, digital events and their holdout, transcripts,
#    surveys, complaints). Branch and agent contact details and campaign subjects are already dropped at staging.
#    Everything after this point uses tokens or nothing; notebook 12 runs the governance tests that prove it.

# %%
pl.close()
print(f"notebook time {time.time() - t0:.0f}s")
