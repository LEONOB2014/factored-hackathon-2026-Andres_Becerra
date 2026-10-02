# %% [markdown]
# # 01 · Business & data understanding
# **CRISP-DM phases 1–2** · LATAM Bank dataset (Factored Datathon 2026)
#
# ## Why this analysis exists
# The bucket holds two folders that look like the same dataset:
#
# | folder | role |
# |---|---|
# | `data/` | main dataset, 13 tables, documented in the data dictionary |
# | `data_backup_20260831/` | unexplained second copy; not mentioned in the dictionary |
#
# A first pass (`docs/dataset/backup_comparison.md`) showed the backup is **not** a byte copy: most IDs differ,
# some tables are absent, and transactions stop in September 2024. The questions this series answers:
#
# 1. What is in one folder and not in the other? (**notebook 02**)
# 2. Is the mismatch explained by a **time shift**? Can rows be aligned? (**03–04**)
# 3. On comparable rows, what differs and how? (**05**)
# 4. Are the two folders statistically the same process? (**06**)
# 5. Which records are anomalous, by which method, and do methods agree? (**07–10**)
#
# ## Business framing
# For a bank, a "backup" that silently differs from production is a **data-governance risk**:
# a restore would change customer identity, balances and history. Beyond that, any anomaly
# detection (fraud, AML, operational) has to know which copy is the source of truth.
#
# ## Hypotheses
# | id | hypothesis | tested in |
# |---|---|---|
# | H1 | Mismatch is caused by a **time shift** (records re-dated by whole days) | 03 |
# | H2 | Entities are **re-keyed** (same entity, new surrogate ID) | 04 |
# | H3 | Backup is an **independent replicate** (same generator, different seed) | 06 |
# | H4 | Backup is **incomplete** (tables missing, history truncated) | 02 |
# | H5 | Shared IDs carry **mutated attributes** (silent record changes) | 05 |
#
# ## Success criteria
# * Every claim is backed by a table or figure computed from the data (reproducible from Parquet).
# * Alignment quality is **validated on a known ground truth** (complaints keep their IDs and text).
# * Hypotheses are explicitly **accepted / rejected / unresolved**; no claim about *why* the backup exists
#   is made beyond what the data supports.

# %%
import sys

sys.path.insert(0, "../src")
import pandas as pd
import plotly.graph_objects as go

from latam_eda import theme
from latam_eda.data import DIMS, FACTS, PK, connect

theme.register()
pd.options.display.float_format = "{:,.2f}".format
con = connect()

# %% [markdown]
# ## Data inventory
# Row counts, date coverage and schema agreement for every table in both folders.

# %%
date_col = dict.fromkeys(FACTS, "process_date")
date_col["daily_exchange_rates"] = "date"

rows = []
for t in FACTS + DIMS:
    has_b = (
        con.sql(
            f"select count(*) from information_schema.tables where table_name='b_{t}'"
        ).fetchone()[0]
        > 0
    )
    m_n = con.sql(f"select count(*) from m_{t}").fetchone()[0]
    b_n = con.sql(f"select count(*) from b_{t}").fetchone()[0] if has_b else None
    dc = date_col.get(t)
    m_rng = (
        con.sql(f"select min({dc})::varchar||' → '||max({dc})::varchar from m_{t}").fetchone()[0]
        if dc
        else "snapshot"
    )
    b_rng = (
        con.sql(f"select min({dc})::varchar||' → '||max({dc})::varchar from b_{t}").fetchone()[0]
        if (dc and has_b)
        else ("snapshot" if has_b else "absent")
    )
    if has_b:
        mc = [
            r[0]
            for r in con.sql(f"describe m_{t}").fetchall()
            if r[0] not in ("day", "month", "year")
        ]
        bc = [
            r[0]
            for r in con.sql(f"describe b_{t}").fetchall()
            if r[0] not in ("day", "month", "year")
        ]
        schema = "identical" if mc == bc else f"differs ({len(set(mc) ^ set(bc))} cols)"
    else:
        schema = "n/a"
    rows.append(
        dict(
            table=t,
            kind="fact" if t in FACTS else "dimension",
            rows_main=m_n,
            rows_backup=b_n,
            ratio=(b_n / m_n if b_n else None),
            range_main=m_rng,
            range_backup=b_rng,
            schema=schema,
        )
    )
inventory = pd.DataFrame(rows)
inventory.style.format(
    {"rows_main": "{:,.0f}", "rows_backup": "{:,.0f}", "ratio": "{:.3f}"}, na_rep="absent"
)

# %%
fig = go.Figure()
fig.add_bar(name="main", x=inventory.table, y=inventory.rows_main, marker_color=theme.MAIN_C)
fig.add_bar(
    name="backup", x=inventory.table, y=inventory.rows_backup.fillna(0), marker_color=theme.BACKUP_C
)
fig.update_layout(
    barmode="group",
    bargap=0.35,
    bargroupgap=0.08,
    yaxis_type="log",
    title="Rows per table, main vs backup (log scale)",
    height=430,
    yaxis_title="rows (log)",
)
fig.update_xaxes(tickangle=-30)
fig.show()

# %% [markdown]
# **Reading the chart.** Ten tables have comparable row counts in both folders (the six dimension tables are
# *exactly* equal; the four shared facts other than transactions are within ±2 %), while three tables behave differently:
# `transactions` is cut to ~41 % of its volume, and `call_transcripts` / `satisfaction_surveys` are
# missing (bars at zero are absent on a log axis). `digital_events` is the only fact table where the
# backup is larger. Schemas are identical wherever both exist.

# %% [markdown]
# ## Documented vs observed
# The dataset summary PDF states target volumes. Comparing both folders to the documentation shows whether
# the *main* data itself is faithful to its own documentation (it is not, see below) — important context
# before judging the backup.

# %%
documented = {
    "transactions": 5_000_000,
    "digital_events": 10_000_000,
    "call_center_interactions": 800_000,
    "call_transcripts": 200_000,
    "campaign_sends": 2_000_000,
    "complaints": 80_000,
    "satisfaction_surveys": 250_000,
    "customers": 150_000,
    "products": 400_000,
    "branches": 350,
    "service_agents": 1_200,
    "marketing_campaigns": 200,
    "daily_exchange_rates": 3_000,
}
doc = inventory[["table", "rows_main", "rows_backup"]].copy()
doc["documented"] = doc.table.map(documented)
doc["main_vs_doc_%"] = 100 * (doc.rows_main / doc.documented - 1)
doc["backup_vs_doc_%"] = 100 * (doc.rows_backup / doc.documented - 1)
doc.style.format(
    {
        "rows_main": "{:,.0f}",
        "rows_backup": "{:,.0f}",
        "documented": "{:,.0f}",
        "main_vs_doc_%": "{:+.1f}",
        "backup_vs_doc_%": "{:+.1f}",
    },
    na_rep="absent",
)

# %% [markdown]
# **Interpretation.** Neither folder matches the documented volumes for facts (-11 % to -16 % for most,
# +56–59 % for `digital_events`; the backup's `transactions` is a further -63 % because it is truncated; `daily_exchange_rates` has 13,164 rows because it stores all 12 currency
# pairs × 1,097 days, not 3,000). Apart from the truncated `transactions`, both folders deviate **in the same
# direction and by almost the same amount**, which is the first hint that they share a generator — H3.

# %% [markdown]
# ## Data model recap
# The 13 tables form a star around `customers` (24 documented foreign keys; see `docs/dataset/erd.md`).
# Key consequence for this study: **if surrogate keys differ between folders, every foreign-key join
# across folders is meaningless** — alignment (notebook 04) must come first.

# %%
pk_table = pd.DataFrame({"table": list(PK), "primary_key": list(PK.values())})
pk_table

# %% [markdown]
# ## Findings & interpretation
# * **H4 (incomplete backup): supported by inventory.** Two tables absent, one truncated at 453/1,097 days.
# * Dimension row counts equal, fact counts close → candidate for **H3 (replicate)**; to be tested with
#   proper two-sample tests in notebook 06.
# * Documentation drift exists in *both* folders → neither is "the documented dataset".
#
# **Next:** notebook 02 quantifies exactly what exists in one folder and not the other.
