# %% [markdown]
# # 02 · What is in one folder and not in the other?
# **CRISP-DM phase 2 (data understanding)** · set-difference report between `data/` (main) and
# `data_backup_20260831/` (backup).
#
# We compare at four levels, from coarse to fine:
# 1. **Table & partition coverage** (which tables / which days exist)
# 2. **Surrogate-key overlap** (same primary-key value in both)
# 3. **Natural-key overlap** (same real-world identity: document number, e-mail, product number …)
# 4. **Content fingerprint overlap** (same business content under different keys/dates)
#
# Levels 3–4 matter because a different surrogate key does not prove a different entity.

# %%
import sys

sys.path.insert(0, "../src")
import ipywidgets as w
import numpy as np
import pandas as pd
import plotly.graph_objects as go
from IPython.display import display

from latam_eda import theme
from latam_eda.data import DIMS, FACTS, PK, ROOT, connect

theme.register()
con = connect()
OUT = ROOT / "reports" / "tables"
OUT.mkdir(parents=True, exist_ok=True)
has_b = {
    t: con.sql(
        f"select count(*) from information_schema.tables where table_name='b_{t}'"
    ).fetchone()[0]
    > 0
    for t in FACTS + DIMS
}

# %% [markdown]
# ## 1 · Coverage by table and month
# Share of main-folder rows that the backup holds per **process month** (backup rows ÷ main rows).
# 1.0 = same volume, 0 = nothing. This is *volume* coverage, not row identity (that comes next).

# %%
months = pd.period_range("2023-06", "2026-06", freq="M").astype(str)
rows = []
for t in FACTS:
    m = (
        con.sql(f"select strftime(process_date,'%Y-%m') ym, count(*) n from m_{t} group by 1")
        .df()
        .set_index("ym")
        .n
    )
    b = (
        con.sql(f"select strftime(process_date,'%Y-%m') ym, count(*) n from b_{t} group by 1")
        .df()
        .set_index("ym")
        .n
        if has_b[t]
        else pd.Series(dtype=float)
    )
    rows.append((m.reindex(months).fillna(0).rename(t), b.reindex(months).fillna(0).rename(t)))
mm = pd.DataFrame({t: r[0] for t, r in zip(FACTS, rows)}).T
bb = pd.DataFrame({t: r[1] for t, r in zip(FACTS, rows)}).T
cov = (bb / mm.replace(0, np.nan)).fillna(0)

fig = go.Figure(
    go.Heatmap(
        z=cov.values,
        x=cov.columns,
        y=cov.index,
        zmin=0,
        zmax=1.5,
        colorscale=[[0, "#f0efec"], [0.01, "#cde2fb"], [0.66, "#3987e5"], [1, "#0d366b"]],
        colorbar=dict(title="backup ÷ main"),
        hovertemplate="%{y}<br>%{x}<br>ratio %{z:.2f}<extra></extra>",
    )
)
fig.update_layout(
    title="Volume coverage of the backup by month (backup rows ÷ main rows)", height=420
)
fig.show()

# %% [markdown]
# **Reading the chart.** Pale rows are empty. `call_transcripts` and `satisfaction_surveys` are entirely
# absent; `transactions` is covered only from **2023-07 to 2024-09** (June 2023 is also missing). Everything
# else has ratios ≈ 1 in every month, so the backup is a *complete* time series for those tables.

# %% [markdown]
# ## 2 · Surrogate (primary) key overlap

# %%
rows = []
for t in FACTS + DIMS:
    k = PK.get(t)
    if k is None:
        continue
    n_m = con.sql(f"select count(distinct {k}) from m_{t}").fetchone()[0]
    if has_b[t]:
        n_b = con.sql(f"select count(distinct {k}) from b_{t}").fetchone()[0]
        shared = con.sql(
            f"select count(*) from (select distinct {k} from m_{t}) join (select distinct {k} from b_{t}) using({k})"
        ).fetchone()[0]
    else:
        n_b, shared = 0, 0
    rows.append(
        dict(
            table=t,
            main_keys=n_m,
            backup_keys=n_b,
            shared=shared,
            only_main=n_m - shared,
            only_backup=n_b - shared,
            pct_main_shared=100 * shared / n_m,
            pct_backup_shared=(100 * shared / n_b) if n_b else np.nan,
        )
    )
pk_overlap = pd.DataFrame(rows)
pk_overlap.to_csv(OUT / "pk_overlap.csv", index=False)
pk_overlap.style.format(
    dict.fromkeys(["main_keys", "backup_keys", "shared", "only_main", "only_backup"], "{:,.0f}")
    | {"pct_main_shared": "{:.1f}", "pct_backup_shared": "{:.1f}"},
    na_rep="–",
)

# %%
po = pk_overlap[pk_overlap.backup_keys > 0].sort_values("pct_main_shared")
fig = go.Figure()
fig.add_bar(
    y=po.table,
    x=po.pct_main_shared,
    orientation="h",
    name="shared with backup",
    marker_color=theme.BLUE,
)
fig.add_bar(
    y=po.table,
    x=100 - po.pct_main_shared,
    orientation="h",
    name="main only",
    marker_color="#e6e5e1",
)
fig.update_layout(
    barmode="stack",
    title="Share of main primary keys that also exist in the backup (%)",
    xaxis_title="% of main keys",
    height=470,
    bargap=0.35,
)
fig.show()

# %% [markdown]
# **Interpretation.** Only `branches`, `marketing_campaigns` (static dimensions) and `complaints` share
# 100 % of their keys (`daily_exchange_rates` has a composite key and is byte-identical). Every other table
# shares only a thin slice: customers 2.7 %, transactions 1.4 % of main (3.3 % of the backup),
# interactions 5 %, sends 3 %, events 9 %, products 32 %, agents 50 %. A *restore* from this backup would
# therefore replace most primary keys — referential links from any external system would break.

# %% [markdown]
# ## 3 · Natural-key overlap — same real-world identity under a different surrogate key?
# If the backup were simply a re-keyed copy, real-world identifiers (document number, e-mail, product
# number …) would overlap almost completely. We test that directly.

# %%
nat = {
    "customers": [
        "document_number",
        "email",
        "mobile_phone",
        "(first_name,last_name,date_of_birth)",
    ],
    "products": ["product_number"],
    "service_agents": ["employee_code", "email"],
    "branches": ["branch_code"],
}
rows = []
for t, keys in nat.items():
    for k in keys:
        expr = k.strip("()")
        sql_m = f"select distinct {expr} k from m_{t} where {expr.split(',')[0]} is not null"
        sql_b = f"select distinct {expr} k from b_{t} where {expr.split(',')[0]} is not null"
        if "," in expr:
            sql_m = f"select distinct ({expr}) k from m_{t} where {expr.split(',')[0]} is not null"
            sql_b = f"select distinct ({expr}) k from b_{t} where {expr.split(',')[0]} is not null"
        n_m = con.sql(f"select count(*) from ({sql_m})").fetchone()[0]
        n_b = con.sql(f"select count(*) from ({sql_b})").fetchone()[0]
        sh = con.sql(f"select count(*) from ({sql_m}) join ({sql_b}) using(k)").fetchone()[0]
        rows.append(
            dict(
                table=t,
                natural_key=k,
                main_distinct=n_m,
                backup_distinct=n_b,
                shared=sh,
                pct_main_shared=100 * sh / n_m,
            )
        )
natural = pd.DataFrame(rows)
natural.to_csv(OUT / "natural_key_overlap.csv", index=False)
natural.style.format(
    {
        "main_distinct": "{:,.0f}",
        "backup_distinct": "{:,.0f}",
        "shared": "{:,.0f}",
        "pct_main_shared": "{:.1f}",
    }
)

# %% [markdown]
# **Interpretation.** Real-world identity overlaps only weakly: **6.8 %** of document numbers
# (10,219 customers), 6.2 % of (name, birth-date) triples and 3.2 % of mobile phones appear in both
# folders — higher than the 2.7 % of shared customer IDs, so ≈ 6,000 customers exist in both folders
# *under different IDs*, but that is still a small minority of the 150 k. E-mail (38 %) and product number
# (36.6 %) overlap more, yet e-mail is a low-entropy field (only 91 k distinct values for 150 k customers, a
# small pool of common names/domains) so coincidences are expected. **A pure re-keying of the same population
# (H2) is rejected**: ~93 % of customers have no counterpart. A small shared core exists and is used in
# notebooks 04–05.

# %% [markdown]
# ## 4 · Content fingerprint overlap (facts)
# For facts without a natural key we hash business content **excluding IDs and dates** and count how many
# fingerprints exist in both folders. A real re-keyed/re-dated copy would show ≈ 100 % overlap.

# %%
fp = {
    "transactions": "amount, currency, transaction_type, channel, transaction_country, merchant_name, fraud_score",
    "campaign_sends": "send_channel, subject, send_status, send_cost, open_device",
    "call_center_interactions": "interaction_type, channel, contact_reason, duration_seconds, wait_time_seconds, sentiment_score",
    "digital_events": "event_type, channel, platform, page_url, ip_address, duration_seconds",
}
rows = []
for t, cols in fp.items():
    q = lambda p: f"select hash({cols}) h, count(*) c from {p}_{t} group by 1"
    n_m = con.sql(f"select count(*), sum(c) from ({q('m')})").fetchone()
    n_b = con.sql(f"select count(*), sum(c) from ({q('b')})").fetchone()
    sh = con.sql(
        f"select count(*), sum(least(a.c,b.c)) from ({q('m')}) a join ({q('b')}) b using(h)"
    ).fetchone()
    rows.append(
        dict(
            table=t,
            main_rows=n_m[1],
            main_distinct_fp=n_m[0],
            backup_distinct_fp=n_b[0],
            shared_fp=sh[0],
            matched_rows=sh[1],
            pct_main_rows=100 * sh[1] / n_m[1],
            fp_uniqueness=n_m[0] / n_m[1],
        )
    )
fp_overlap = pd.DataFrame(rows)
fp_overlap.to_csv(OUT / "fingerprint_overlap.csv", index=False)
fp_overlap.style.format(
    dict.fromkeys(
        ["main_rows", "main_distinct_fp", "backup_distinct_fp", "shared_fp", "matched_rows"],
        "{:,.0f}",
    )
    | {"pct_main_rows": "{:.2f}", "fp_uniqueness": "{:.3f}"}
)

# %% [markdown]
# **Interpretation.** `fp_uniqueness` (distinct fingerprints ÷ rows) tells which fingerprints are
# informative. Only **transactions** (0.99) and **digital events** (0.89) are discriminating: just **0.65 %**
# of main transactions and 8.6 % of events have an identical-content row in the backup, i.e. the backup's
# facts are **not the same business events under new keys/dates**. For `campaign_sends` (uniqueness 0.011)
# and `call_center_interactions` (0.82 → 12.8 % matched but partly driven by 13 k backup fingerprints)
# the fingerprint is low-entropy, so their high match rates (95.7 %, 12.8 %) are *coincidence of common
# values*, not evidence of copying — we do not use them. The backup facts are new draws from the same
# process; only the ~3 % of rows that keep their key can be paired (notebook 04).

# %% [markdown]
# ## 5 · Summary: what is where
# One consolidated table for the report.

# %%
summary = pk_overlap.merge(
    pd.DataFrame(
        {"table": FACTS + DIMS, "in_backup": ["yes" if has_b[t] else "NO" for t in FACTS + DIMS]}
    ),
    on="table",
)
summary["status"] = np.select(
    [~summary.in_backup.eq("yes"), summary.pct_main_shared.eq(100) & summary.only_backup.eq(0)],
    ["absent from backup", "identical key set"],
    default="partial / diverged",
)
summary.loc[summary.table == "transactions", "status"] = "truncated + diverged"
summary.to_csv(OUT / "set_difference_summary.csv", index=False)
summary[
    [
        "table",
        "in_backup",
        "main_keys",
        "backup_keys",
        "shared",
        "only_main",
        "only_backup",
        "pct_main_shared",
        "status",
    ]
].style.format(
    dict.fromkeys(["main_keys", "backup_keys", "shared", "only_main", "only_backup"], "{:,.0f}")
    | {"pct_main_shared": "{:.1f}"}
)

# %% [markdown]
# ## Interactive explorer
# Pick a table to see the Venn-style decomposition. *(Widgets need a live kernel — they appear blank in the
# static HTML export; the tables above contain the same numbers.)*

# %%
dd = w.Dropdown(
    options=[t for t in FACTS + DIMS if PK.get(t)], value="transactions", description="table"
)
out = w.Output()


def draw(_=None):
    out.clear_output(wait=True)
    r = pk_overlap[pk_overlap.table == dd.value].iloc[0]
    f = go.Figure(
        go.Bar(
            x=["only in main", "in both", "only in backup"],
            y=[r.only_main, r.shared, r.only_backup],
            marker_color=[theme.MAIN_C, "#8a8984", theme.BACKUP_C],
        )
    )
    f.update_layout(
        title=f"{dd.value}: primary-key set difference", height=360, yaxis_title="distinct keys"
    )
    with out:
        display(f)
        display(summary[summary.table == dd.value].T)


dd.observe(draw, "value")
draw()
display(w.VBox([dd, out]))

# %% [markdown]
# ## Findings
# | # | finding | evidence |
# |---|---|---|
# | F1 | Backup lacks 2 whole tables and 59 % of the transaction history | §1 |
# | F2 | Only complaints and 3 static tables share their full key set | §2 |
# | F3 | Customers, products, agents and facts share only 1–50 % of their keys (transactions 1.4 %, customers 2.7 %) | §2 |
# | F4 | Only ~7 % of real-world customer identities (document no., name+DOB) overlap → **not a re-keyed copy** (H2 rejected); a ~6k-customer core exists under different IDs | §3 |
# | F5 | Only 0.65 % of transactions and 8.6 % of events match on content under other keys → backup facts are **new draws**, not re-dated copies | §4 |
#
# **Open question for notebook 03:** the small set of rows that *do* share a key carry dates shifted by
# whole days. Is that shift constant, random, or drifting?
