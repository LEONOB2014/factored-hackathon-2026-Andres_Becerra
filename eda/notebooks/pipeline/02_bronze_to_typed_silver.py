# %% [markdown]
# # 02 · Lossless bronze → typed silver
# **Pipeline series** · task group `silver`, part 1: the `typed_*` views
#
# ## What happens here
# Bronze stores every source record exactly as written: every field is **text**, nothing is cast, nothing is
# dropped, and each record carries its lineage (file, record number, sha256, parse status). The first silver step
# reads that text and **types it against a reviewed source contract** (`platform/contracts/sources/<table>.yml`).
#
# The rule that governs the step: **a value that breaks the contract is flagged, never dropped and never silently
# repaired.** The row flows on with the bad cell typed as NULL, and the problem is written into `_dq_issues` as
# `<column>:<code>`. `audit.dq_cell_findings` (notebook 12) turns those lists into one row per bad cell, the work
# list for the data steward.
#
# | code | rule | meaning |
# |---|---|---|
# | G | C07 | the record breaks the CSV grammar |
# | N | C02 | a required value is empty or absent |
# | T | C01 | a non-empty value does not cast to the contract type |
# | F | C08 | it casts, but in a format the contract does not accept (e.g. a day-first date) |
# | K | C05 | an identifier breaks its key pattern |
# | V1 / V2 | C03 / C04 | a value outside the vocabulary / a known variant spelling of an allowed value |
# | P / S | C06 / C09 | a null rendered into free text (`nan`) / an unrendered template slot (`{monto}`) |

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
TYPED = sorted(n for n in pl.catalog()["node"] if n.startswith("typed_"))
# the overlay and the typed views of this notebook (views build instantly: they are queries over bronze Parquet)
built = pl.build_set(["dq_corrections_active", *TYPED])
pl.ensure(pl.key("dq_partition_profile"))  # read in section 7 (explained in notebook 03)
print(f"{len(TYPED)} typed views")

# %% [markdown]
# ## 1 · What a bronze record looks like
# One record of the transactions bronze, as stored. Every business column is `VARCHAR`; the underscore columns are
# lineage added by `bronze_build`. Nothing here has been interpreted yet: an empty string is still an empty string.

# %%
BRONZE = f"read_parquet('{pl.lake}/bronze_raw/transactions/*/*.parquet', union_by_name = true)"
sample = pl.con.sql(f"SELECT * FROM {BRONZE} LIMIT 3").df()
display(pl.con.sql(f"DESCRIBE SELECT * FROM {BRONZE}").df()[["column_name", "column_type"]].T)
show(pl.safe(sample), paging=False)

# %% [markdown]
# ## 2 · The contract: what each column is allowed to be
# The contract for transactions as the pipeline reads it (seed `source_contract_columns`, generated from the YAML).
# `required` means an empty value is a finding; `enumerated` means the column has a closed vocabulary; `keyed` means
# an identifier pattern; `scale_*` are the baselines the drift check compares each day against (notebook 03).

# %%
show(
    pl.q(
        "select * exclude (contract_version) from {source_contract_columns} where table_name = 'transactions' "
        "order by ordinal"
    ),
    paging=False,
)

# %% [markdown]
# ## 3 · How a typed view is built
# The generated SQL has three parts. The excerpt below is the start of `typed_transactions`.
# 1. `c`: the **corrections overlay**: approved four-eyes corrections for this table, one map per record.
# 2. `o`: bronze plus `_dq_issues`, a list of every contract check that fails, computed on the **original text**.
# 3. `r` and the final select: the corrected text (original where no correction applies) is cast with
#    `try_cast(nullif(x, ''))`: empty → NULL, uncastable → NULL. Lineage columns pass through.

# %%
code = pl.sql("typed_transactions").splitlines()
print(
    "\n".join(
        code[:12] + ["    …"] + [ln for ln in code if "try_cast" in ln][:6] + ["    …"] + code[-10:]
    )
)

# %% [markdown]
# ## 4 · Every record survives: bronze rows = typed rows
# The typed views never filter. The check below counts bronze records and typed rows for every table.

# %%
rows = []
for t in TYPED:
    table = t.removeprefix("typed_")
    zone = "holdout_raw" if table.endswith("_holdout") else "bronze_raw"
    src = table.removesuffix("_holdout")
    n_bronze = pl.con.sql(
        f"SELECT count(*) FROM read_parquet('{pl.lake}/{zone}/{src}/*/*.parquet', union_by_name = true)"
    ).fetchone()[0]
    n_typed, n_clean, n_bad = pl.q(
        f"select count(*), count(*) filter (where len(_dq_issues) = 0), count(*) filter (where len(_dq_issues) > 0) "
        f"from {{{t}}}"
    ).iloc[0]
    rows.append(
        {
            "typed view": t,
            "bronze records": n_bronze,
            "typed rows": n_typed,
            "clean rows": n_clean,
            "flagged rows": n_bad,
        }
    )
surv = pd.DataFrame(rows)
surv["kept"] = surv["typed rows"] == surv["bronze records"]
surv["flagged %"] = (100 * surv["flagged rows"] / surv["typed rows"]).round(3)
show(surv, paging=False)
print(
    f"all kept: {surv['kept'].all()} · flagged rows in total: {surv['flagged rows'].sum():,} "
    f"of {surv['typed rows'].sum():,} ({100 * surv['flagged rows'].sum() / surv['typed rows'].sum():.2f} %)"
)

# %%
fig = px.bar(
    surv.melt(
        id_vars="typed view",
        value_vars=["clean rows", "flagged rows"],
        var_name="state",
        value_name="rows",
    ),
    y="typed view",
    x="rows",
    color="state",
    orientation="h",
    log_x=True,
    title="Clean versus flagged rows per typed view (log scale)",
)
fig.update_layout(height=520, yaxis_title=None, legend_title=None)
fig.show()

# %% [markdown]
# ## 5 · What is flagged: table × column × code
# `_dq_issues` unnested over all typed views: one row per (table, column, code) with the number of cells. This is
# exactly what `audit.dq_cell_findings` will hold, before lineage and masking.

# %%
issues = pl.q(
    " union all ".join(
        f"select '{t.removeprefix('typed_')}' as table_name, split_part(i, ':', 1) as column_name, "
        f"split_part(i, ':', 2) as code, count(*) as cells from (select unnest(_dq_issues) as i from {{{t}}}) group by all"
        for t in TYPED
    )
).sort_values("cells", ascending=False)
show(issues, paging=False)

# %% [markdown]
# ## 6 · Flagged cells next to their raw text
# For each finding, a few examples: the original text (masked where it is personal data), what the typed column
# holds after typing, and the lineage that leads back to the bronze file and record.


# %%
def examples(table: str, column: str, code: str, n: int = 5) -> pd.DataFrame:
    t = f"typed_{table}"
    raw = (
        f"read_parquet('{pl.lake}/{'holdout_raw' if table.endswith('_holdout') else 'bronze_raw'}/"
        f"{table.removesuffix('_holdout')}/*/*.parquet', union_by_name = true)"
    )
    return pl.con.sql(f"""
        select b."{column}" as raw_text, t."{column}" as typed_value, t._partition_date, t._source_file,
               t._record_no, t._dq_issues
        from {pl.relation(pl.key(t))} t
        join {raw} b on b._source_file = t._source_file and b._record_no = t._record_no
        where list_contains(t._dq_issues, '{column}:{code}')
        limit {n}""").df()


for r in issues.head(4).itertuples():
    display(Markdown(f"**{r.table_name}.{r.column_name} · {r.code}** · {r.cells:,} cells"))
    df = examples(r.table_name, r.column_name, r.code)
    if r.column_name in pl.restricted:
        df["raw_text"] = df["raw_text"].map(pipe._shape)
        df["typed_value"] = df["typed_value"].map(pipe._shape)
    show(df, paging=False)

# %% [markdown]
# ## 7 · Empty versus NULL: the decision the typed layer makes for every column
# In the CSV an empty field is `,,`. The contract decides whether that is acceptable (`required: false`) or a finding
# (`N`). Typing turns every empty string into NULL, so downstream SQL never has to distinguish `''` from NULL. The
# lossless bronze keeps the difference if it is ever needed. Below, the share of empty values per column, read
# from the per-partition profile the drift check uses, for the columns where it is not zero.

# %%
empty = pl.q("""
    select table_name, column_name, sum(n_empty) as empty, sum(n_absent) as absent, sum(n_rows) as rows,
           round(100 * sum(n_empty) / sum(n_rows), 3) as empty_pct
    from {dq_partition_profile} group by all having sum(n_empty) + sum(n_absent) > 0
    order by empty_pct desc""")
show(empty, paging=False)

# %%
fig = px.bar(
    empty.head(25),
    x="empty_pct",
    y=empty.head(25)["table_name"] + "." + empty.head(25)["column_name"],
    orientation="h",
    title="Columns with the highest share of empty values (top 25)",
)
fig.update_layout(
    height=600, yaxis_title=None, xaxis_title="% of rows empty", yaxis=dict(autorange="reversed")
)
fig.show()

# %% [markdown]
# ## 8 · The correction overlay (phase 4)
# Approved corrections live in an append-only log (`lake/corrections/applied/*.parquet`). `dq_corrections_active`
# selects those in force; each typed view overlays them on the text **before** typing, while `_dq_issues` stays
# computed on the original text. `_corrected_columns` lists what the overlay changed in each row.

# %%
display(pl.q("select count(*) as corrections_in_force from {dq_corrections_active}"))
display(
    pl.q(
        "select count(*) filter (where len(_corrected_columns) > 0) as corrected_rows from {typed_transactions}"
    )
)

# %% [markdown]
# ## 9 · Two variant spellings that are not typos
# The contract calls `Mexico` (without the accent) a *variant* (V2) of the allowed `México`. Before deciding to
# correct it, look at **who** produces it. If it were a typing slip, it would appear in proportion to Mexican
# activity. It does not.

# %%
tx_cc = pl.q("""
    select c.country as customer_country, t.transaction_country, count(*) as transactions
    from {typed_transactions} t join {typed_customers} c using (customer_id)
    where t.transaction_country in ('Mexico', 'USA', 'Spain', 'Brazil')
    group by all order by 2, 1""")
fig = px.bar(
    tx_cc,
    x="transaction_country",
    y="transactions",
    color="customer_country",
    barmode="group",
    title="Transactions in the four 'foreign' labels, by the customer's country",
)
fig.update_layout(height=380, xaxis_title=None, legend_title="customer country")
fig.show()
ev = pl.q("""select customer_id is null as anonymous, ip_country, count(*) as events
             from {typed_digital_events} group by all order by 1, 2""")
show(ev, paging=False)

# %% [markdown]
# **What the two views say.**
# * In **transactions**, `Mexico` behaves exactly like `USA`, `Spain` and `Brazil`: the same ~0.9 % of every
#   customer country's activity (8.6 k for Argentines, 12.8 k for Colombians, 17.9 k for Mexicans), while `México`
#   appears only on Mexican customers' domestic transactions. `Mexico` is the generator's **foreign-destination
#   label**, not a misspelling. Staging maps both to `MX`, so an Argentine paying in "Mexico" is correctly
#   cross-border; for the 17.9 k Mexican customers it becomes domestic, which is also correct geographically.
# * In **digital events**, `Mexico` appears **only on anonymous events** (no customer id): 1.01 M of them, against
#   0.30 M anonymous events labelled `México`. Identified customers always log in from their own country: there is
#   **not a single cross-border login** in 11.5 M identified events.
#
# **Implications.**
# * Correcting `Mexico` → `México` (the pattern proposal of the four-eyes demo) changes no country code downstream:
#   both already map to `MX`. It is safe, and it is cosmetic. Its real value is the audit trail.
# * `ip_country = 'Mexico'` is a **perfect marker of anonymous traffic**. Any model given the raw string would learn
#   "anonymous" from it, a generator artefact. Use the ISO code from staging, never the raw text.
# * Because identified logins never cross a border, "login from an unusual country" and "impossible travel" fraud
#   features have **no signal** in this data. They must stay in the design (a real bank needs them) but cannot be
#   validated here.

# %% [markdown]
# ## 10 · Explorer: any table, any column, any code
# Pick a finding to see its examples next to the raw text. (Live kernel only; the static HTML shows the tables
# above.)

# %%
opts = issues[["table_name", "column_name", "code"]].drop_duplicates()
w_t = w.Dropdown(options=sorted(opts["table_name"].unique()), description="table")
w_c = w.Dropdown(description="column")
w_k = w.Dropdown(description="code")
out_x = w.Output()


def _cols(*_):
    w_c.options = sorted(opts.loc[opts.table_name == w_t.value, "column_name"].unique())


def _codes(*_):
    w_k.options = sorted(
        opts.loc[(opts.table_name == w_t.value) & (opts.column_name == w_c.value), "code"]
    )


def draw_examples(*_):
    with out_x:
        out_x.clear_output()
        if not (w_t.value and w_c.value and w_k.value):
            return
        df = examples(w_t.value, w_c.value, w_k.value, 10)
        if w_c.value in pl.restricted:
            df["raw_text"] = df["raw_text"].map(pipe._shape)
            df["typed_value"] = df["typed_value"].map(pipe._shape)
        display(df)


w_t.observe(_cols, "value")
w_c.observe(_codes, "value")
w_k.observe(draw_examples, "value")
_cols()
_codes()
draw_examples()
display(w.VBox([w.HBox([w_t, w_c, w_k]), out_x]))

# %% [markdown]
# ## Findings and what to do
# 1. **Nothing is lost.** Every bronze record of every table becomes exactly one typed row (15 views: 22.85 M main +
#    0.56 M holdout = 23.41 M rows). Typing never filters; only staging does, and only for held partitions (notebook 03).
# 2. **The data is structurally clean.** Every record parsed (`_parse_status = ok`); no value fails to cast, no key
#    breaks its pattern, no required field is empty. Only **three findings** exist, all known from the forensics:
#    * `Mexico` in `transactions.transaction_country` (39,356 rows, 0.92 %) and in
#      `digital_events.ip_country` (1,010,493 rows, 6.65 %), plus the holdout share (1,159 and 27,681);
#    * the text `nan` rendered into 38,142 campaign subjects (`¡Oferta especial en nan!`, 2.25 % of sends, 7 % of
#      the sends that have a subject).
#
#    1,116,831 flagged cells in total; 1,078,689 of them are spellings that staging already normalises.
# 3. **`Mexico` is not a typo** (section 9): it is the generator's foreign-destination label in transactions and the
#    anonymous-traffic label in digital events. **Recommendation:** approve the correction for the audit trail, and
#    never feed raw country text to a model.
# 4. **`nan` in subjects is a real source defect**: an upstream template filled with a missing product name. The
#    right action is twofold: correct it through the four-eyes flow so reports read cleanly, **and** report it to the
#    campaign system so it stops sending a broken message to customers (2.25 % of sends: a customer-experience and
#    brand issue, not only a data issue).
# 5. **Empty is common and meaningful.** Many columns are empty most of the time because they only apply to some
#    rows: conversion fields on 99.4 % of sends, resolution fields on 77 % of complaints, `credit_limit` on the 69 %
#    of products that are not credit products, coordinates on 81 % of transactions. Typing turns them into NULL. **Do
#    not impute them in silver.** Whether a NULL means "not applicable", "unknown" or "zero" is a per-use decision
#    taken in conformed silver or in the marts (notebooks 05, 07, 08), where it is visible and tested.
# 6. **`complaints.origin_interaction_id` is empty in 100 % of rows.** The key that would link a complaint to the
#    contact that raised it does not exist, which blocks contact-to-complaint journeys (notebook 07, CX journey).

# %%
pl.close()
print(f"notebook time {time.time() - t0:.0f}s")
