# %% [markdown]
# # 01 · Grain design and the hour star
# **Granularity series III · the bank at the hour** · every fact table re-grained to the hour of its own delivery clock
#
# **Why this series.** Series II measured the clock each process runs on (ADR-014) and found that the *counts* of every
# process are flat over the hours of the business day. This series goes the whole way: it re-grains every fact table
# to the hour (or below), redesigns the dimensions the hour needs, and executes every candidate model of every
# scenario, **whatever the signal**. A model that cannot be trained is a result: its readiness gate (notebook 08) names
# the root cause and what the data collection must change to turn it green.
#
# **This notebook.** The bus matrix at the hour, the build and checks of every hour model, the sparsity of each
# entity × hour grain (which grains are viable at all), and the dimension redesign.
#
# **Clocks.** Every hour is placed on its process's declared delivery clock (`country.PROCESS_DAY_OFFSET`): −6 h for
# transactions, digital events and sends, −8 h for contacts and complaints. "Hour 0" is the first hour of the delivery
# day, the same in every market.

# %%
import sys
import time
import warnings
from pathlib import Path

sys.path.insert(0, "../../src")
import numpy as np
import pandas as pd
import plotly.express as px
from IPython.display import Markdown, display
from itables import show

from latam_eda import country, theme
from latam_eda import granularity as g

warnings.filterwarnings("ignore")
OUT = Path("../../reports/tables")
OUT.mkdir(parents=True, exist_ok=True)
theme.register()
t0 = time.time()
pl = country.session("ALL", "main")
country.prepare(pl, "gold")
star = g.open_star(pl, [g.SQL_DIR_TIME, g.SQL_DIR_HOUR])

# %% [markdown]
# ## 1 · The bus matrix at the hour
# Rows are the hour-grain facts; columns the conformed dimensions they join. A ● marks a join; "role" marks a
# role-playing join (the same dimension under a process's own clock).

# %%
bus = pd.DataFrame(
    [
        ("fct_country_hour", "market × hour", "periodic, dense", "●", "", "●", "", "", "", ""),
        (
            "fct_channel_hour",
            "market × channel × hour",
            "periodic, dense",
            "●",
            "",
            "●",
            "",
            "",
            "",
            "●",
        ),
        ("fct_branch_hour", "branch × hour", "periodic, sparse", "●", "", "", "●", "", "", "●"),
        (
            "fct_agent_hour",
            "agent × hour",
            "periodic, sparse",
            "role (−8 h)",
            "",
            "",
            "",
            "●",
            "",
            "",
        ),
        (
            "fct_contact_queue_hour",
            "market × channel × hour",
            "periodic, dense",
            "role (−8 h)",
            "",
            "●",
            "",
            "",
            "",
            "●",
        ),
        ("fct_session", "session (minutes)", "accumulating", "role", "●", "", "", "", "●", "●"),
        (
            "fct_case_clock",
            "complaint case",
            "accumulating (milestones)",
            "role (−8 h)",
            "●",
            "●",
            "",
            "",
            "",
            "",
        ),
        (
            "fct_send_response",
            "campaign send",
            "accumulating (milestones)",
            "role",
            "●",
            "",
            "",
            "",
            "",
            "●",
        ),
        (
            "fct_customer_daypart",
            "customer × daypart",
            "periodic snapshot",
            "daypart",
            "●",
            "",
            "",
            "",
            "",
            "",
        ),
    ],
    columns=[
        "fact",
        "grain",
        "type",
        "dim_hour / dim_time_of_day",
        "customer",
        "market",
        "dim_branch_schedule",
        "dim_agent_shift",
        "dim_session_outcome",
        "channel",
    ],
)
show(bus, paging=False)

# %% [markdown]
# ## 2 · Build and check every model
# Each model declares its grain, the reconciliation of every additive measure to its atomic fact, and (when dense)
# the cross product it must cover; `Star.check` tests all three.

# %%
built = star.build(verbose=False)
checks = star.check()
checks.to_csv(OUT / "granularity_hour_checks.csv", index=False)
show(built, paging=False)
show(checks[["model", "check", "detail", "expected", "observed", "ok"]], paging=True)
display(
    Markdown(
        f"**{int(checks.ok.sum())} of {len(checks)} checks pass on {built.model.nunique()} models** "
        f"({int(built.rows.sum()):,} rows in all): every hour model reconciles exactly to the transaction, contact, "
        "complaint, session and send facts of gold."
    )
)

# %% [markdown]
# ## 3 · Which entity × hour grains are viable?
# A grain is only useful if its cells hold events. For each candidate the table gives the number of possible cells,
# the share that hold at least one event, the mean events in an occupied cell, and the share a Poisson process with
# the same mean would leave empty (a much higher observed empty share means events cluster; equal means they are
# spread at random). Grains where almost every cell is empty cannot carry a model or a KPI and are aggregated to a
# coarser grain (daypart, day) instead.

# %%
hours = star.q("select count(*) from {dim_hour}").iloc[0, 0]
spec = [
    (
        "market × hour",
        "select count(*) from {fct_country_hour} where n_tx > 0",
        "select sum(n_tx) from {fct_country_hour}",
        3,
    ),
    (
        "market × channel × hour",
        "select count(*) from {fct_channel_hour} where n_tx > 0",
        "select sum(n_tx) from {fct_channel_hour}",
        18,
    ),
    (
        "branch × hour (teller + ATM)",
        "select count(*) from {fct_branch_hour}",
        "select sum(n_tx) from {fct_branch_hour}",
        star.q("select count(*) from {stg_branches}").iloc[0, 0],
    ),
    (
        "agent × hour (contacts)",
        "select count(*) from {fct_agent_hour}",
        "select sum(contacts) from {fct_agent_hour}",
        star.q("select count(*) from {dim_agent}").iloc[0, 0],
    ),
    (
        "customer × hour (transactions)",
        "select count(distinct (customer_id, date_trunc('hour', transaction_ts_utc))) from {int_transactions_enriched}",
        "select count(*) from {int_transactions_enriched}",
        star.q("select count(*) from {int_customer_profile}").iloc[0, 0],
    ),
    (
        "product × hour (transactions)",
        "select count(distinct (product_id, date_trunc('hour', transaction_ts_utc))) from {int_transactions_enriched}",
        "select count(*) from {int_transactions_enriched}",
        star.q("select count(*) from {stg_products}").iloc[0, 0],
    ),
    (
        "customer × daypart × day (transactions)",
        "select count(distinct (customer_id, cast(transaction_ts_utc - interval 6 hour as date), hour(transaction_ts_utc - interval 6 hour) // 6)) from {int_transactions_enriched}",
        "select count(*) from {int_transactions_enriched}",
        star.q("select count(*) from {int_customer_profile}").iloc[0, 0] / 6,
    ),
]
rows = []
for name, occ_sql, ev_sql, units in spec:
    occ, ev = star.q(occ_sql).iloc[0, 0], star.q(ev_sql).iloc[0, 0]
    cells = units * hours
    lam = ev / cells
    rows.append(
        {
            "grain": name,
            "cells": int(cells),
            "occupied %": 100 * occ / cells,
            "events per occupied cell": ev / occ,
            "Poisson empty %": 100 * np.exp(-lam),
            "events per cell": lam,
            "viable": "yes"
            if lam >= 1
            else "sparse: aggregate"
            if lam >= 0.01
            else "no: too sparse",
        }
    )
sp = pd.DataFrame(rows)
sp.to_csv(OUT / "granularity_hour_sparsity.csv", index=False)
show(sp.round(4), paging=False)
fig = px.bar(
    sp,
    x="grain",
    y="events per cell",
    log_y=True,
    title="Events per cell by grain (log scale; below 1, most cells are empty)",
)
fig.add_hline(y=1, line_dash="dot")
fig.update_layout(height=360, xaxis_tickangle=-25)
fig.show()
dense = sp[sp["events per cell"] >= 1].grain.tolist()
display(
    Markdown(
        f"**Viable dense hour grains: {', '.join(dense)}.** "
        f"Customer × hour holds {sp.loc[4, 'events per cell']:.4f} transactions per cell and product × hour "
        f"{sp.loc[5, 'events per cell']:.4f}: {100 - sp.loc[4, 'occupied %']:.2f} % and {100 - sp.loc[5, 'occupied %']:.2f} % of cells "
        "are empty, so neither is a fact table. A customer's time of day is kept as a **profile over dayparts** "
        "(`fct_customer_daypart`), and a product has no hourly decision at all. Branch × hour and agent × hour are "
        "sparse: they are stored only where activity happens and read against a schedule dimension, which is what "
        "turns an empty cell into information (closed, or off shift)."
    )
)

# %% [markdown]
# ## 4 · The dimension redesign
# | dimension | change | why the hour needs it |
# |---|---|---|
# | `dim_hour` (series II) | one row per UTC hour; delivery day, hour of day and weekday on the transaction clock | the calendar of every intraday fact; other clocks are role-played by shifting the hour |
# | `dim_time_of_day` (new) | 24 rows: daypart, business-hour flag | a role-playing dimension every process joins on its *own* clock's hour, so "morning" means the same everywhere |
# | `dim_process_clock` (new) | process → declared offset | ADR-014 as data: the offset each fact must apply, testable and versioned |
# | `dim_branch_schedule` (new) | branch × weekday × hour → open fraction | a coverage (factless) dimension: the hour grain needs to know when a branch *should* be active; the source gives one window and no opening days (Monday to Friday assumed) |
# | `dim_agent_shift` (new) | shift × hour → in shift | the bridge from a declared shift to its hours; the source names shifts but not their hours (standard three-shift roster assumed) |
# | `dim_session_outcome` (new) | 8-row junk dimension | three low-cardinality outcome flags of 1.8 M sessions in one key |
# | customer bands (series I) → **daypart profile** | customer × daypart snapshot | the customer's time of day, as a mini-dimension instead of a 99.99 %-empty customer × hour fact |
#
# **What the redesign assumes, and the audit must replace:** branch opening days, shift hours, and the clock of every
# timestamp. Each assumption is a field the source should collect (notebook 08).

# %%
pl.close()
print(f"notebook time {time.time() - t0:.0f}s")
