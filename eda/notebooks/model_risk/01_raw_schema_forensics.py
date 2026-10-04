# %% [markdown]
# # 01 · Raw schema forensics
# **Model-risk series, phase 1** · LATAM Bank dataset (Factored Datathon 2026)
#
# ## Why this notebook exists
# The 13 source tables arrive as CSV files **without any metadata**: no schema, no types, no version, no
# change log. Every downstream layer (the EDA Parquet copy, bronze, silver, gold) assumes that each table has
# one stable schema. If a source changed a format, a vocabulary, a unit or a key convention without saying so,
# the pipelines would silently propagate it.
#
# So the schema is **inferred from the raw text**, file by file, and any change is detected before anything is
# typed. The typed copies are only audited at the end (section 9): converting to Parquet already **erased the
# evidence** this analysis needs (original formats, decimal separators, leading zeros, timezone suffixes,
# empty-vs-null, values that did not fit the inferred type).
#
# ## Method (details in `docs/platform/09_data_and_model_risk_methodology.md`, section A)
# | level | what is fingerprinted, per file (and per column) | where |
# |---|---|---|
# | L0 physical | bytes, sha256, BOM, line endings, UTF-8 validity, **records by CSV grammar**, ragged rows | §2 |
# | L1 header | column names and order, BOM attached to the first name | §2 |
# | L2 lexical | share of each value class (int, leading-zero code, decimal dot/comma, date and timestamp variants, IP, JSON, text), lengths, charset, decimals, log10 scale | §3 |
# | L3 semantic | per-file vocabularies (births, deaths, variants), unit/scale steps | §4 |
# | L3b invariants | row-level consistency computed from the raw text | §6 |
# | L4 relational | primary keys across files, foreign-key coverage per day | §7 |
#
# Daily fingerprints are classified (`stable`, `born`, `died`, `episode`, `intermittent`, `transient`,
# `coexisting`) and tested for sustained shifts by binary segmentation with a **permutation test** on the
# standardized CUSUM, so the false-alarm rate is controlled on the data itself. Scale steps below a factor of
# 1.26 are treated as immaterial (effect size first: with millions of rows everything is significant).
#
# **Positive controls.** Detectors are only trusted after they find known changes: ten synthetic mutations
# injected into real partitions (§8) and the backup copy, a real, known-different source (§5).
#
# **Inputs.** Fingerprints cached by `scripts/raw_schema_scan.py` (both copies, every file) and the detector
# scorecard from `scripts/mutate_partitions.py`. Run both before this notebook.

# %%
import sys

sys.path.insert(0, "../../src")
import json
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from IPython.display import Markdown, display
from itables import init_notebook_mode, show

from latam_eda import change_detection as cd
from latam_eda import raw_forensics as rf
from latam_eda import theme
from latam_eda.data import DATA, DERIVED, PK
from latam_eda.profiling import PII, TEXT

theme.register()
init_notebook_mode(all_interactive=False, connected=False)
pd.options.display.max_colwidth = 80

FP = DERIVED / "raw_fingerprints"
RAW = {"main": DATA / "raw" / "data", "backup": DATA / "raw" / "data_backup_20260831"}
OUT = Path("../../reports/tables")
CONTRACTS = Path("../../reports/contracts")
assert (FP / "main").exists(), "run scripts/raw_schema_scan.py first"
TABLES = sorted(p.name.split("__")[0] for p in (FP / "main").glob("*__files.parquet"))
COLOR = {"main": theme.MAIN_C, "backup": theme.BACKUP_C}
con = duckdb.connect()


def h(text):
    display(Markdown(text))


def load(copy, table):
    """Cached fingerprints of one table in one copy: (files, lexical, vocabulary), dates parsed."""
    base = FP / copy
    if not (base / f"{table}__files.parquet").exists():
        return None
    out = []
    for kind in ("files", "lexical", "vocabulary"):
        df = pd.read_parquet(base / f"{table}__{kind}.parquet")
        if "partition_date" in df:
            df["partition_date"] = pd.to_datetime(df["partition_date"])
        out.append(df)
    return tuple(out)


FPS = {(c, t): load(c, t) for c in RAW for t in TABLES}
FPS = {k: v for k, v in FPS.items() if v is not None}


def raw_src(copy, table):
    """DuckDB read of a table's raw text (pinned dialect, all VARCHAR, '' kept), with the source file."""
    files = rf.table_files(RAW[copy], table)
    listing = "[" + ", ".join(f"'{f}'" for f in files) + "]"
    return f"read_csv({listing}, {rf.READ_OPTS})"


h(
    f"Fingerprints loaded for **{len(FPS)}** (copy, table) pairs: "
    f"{sum(len(v[0]) for v in FPS.values()):,} files, {sum(int(v[0]['records'].sum()) for v in FPS.values()):,} records."
)

# %% [markdown]
# ## 1 · Coverage: every file, every record
# Records are counted by **CSV grammar**, not by lines: a quoted field may contain newlines. The landing
# manifest counts lines, so the two differ exactly by the embedded newlines; anything else would be a gap.

# %%
manifest = json.loads((DATA / "lake" / "manifests" / "landing" / "latest.json").read_text())
lines = pd.DataFrame(manifest["files"])
lines["copy"] = np.where(lines["path"].str.startswith("data/"), "main", "backup")
lines["table"] = lines["path"].str.split("/").str[1].str.replace(".csv", "", regex=False)
lines = lines.groupby(["copy", "table"]).agg(
    manifest_files=("path", "size"), manifest_lines=("lines", "sum")
)

cov = []
for (copy, table), (files, lex, voc) in FPS.items():
    cov.append(
        {
            "copy": copy,
            "table": table,
            "files": len(files),
            "bytes": int(files["size"].sum()),
            "records": int(files["records"].sum()),
            "multiline_records": int(files["multiline_records"].sum()),
            "headers": files["header"].nunique(),
        }
    )
cov = pd.DataFrame(cov).set_index(["copy", "table"]).join(lines)
cov["lines_minus_headers"] = cov["manifest_lines"] - cov["manifest_files"]
embedded = {}
for (copy, table), (files, _, _) in FPS.items():
    if files["multiline_records"].sum():
        cols = json.loads(files["header"].iloc[0])
        expr = " + ".join(
            f"coalesce(sum(length({rf.q(c)}) - length(replace({rf.q(c)}, chr(10), ''))), 0)"
            for c in cols
        )
        embedded[(copy, table)] = con.sql(f"select {expr} from {raw_src(copy, table)}").fetchone()[
            0
        ]
cov["embedded_newlines"] = pd.Series(embedded).reindex(cov.index).fillna(0)
cov["unexplained_gap"] = cov["lines_minus_headers"] - cov["records"] - cov["embedded_newlines"]
display(
    cov.style.format("{:,.0f}", na_rep="—").background_gradient(
        subset=["multiline_records"], cmap=theme.cmap_seq()
    )
)

# %% [markdown]
# ## 2 · Physical layer and header (L0, L1)

# %%
l0 = []
for (copy, table), (files, lex, voc) in FPS.items():
    dated = files["partition_date"].dropna()
    full = pd.date_range(dated.min(), dated.max()) if len(dated) else pd.DatetimeIndex([])
    file_day = files["path"].str.extract(r"_(\d{8})\.csv$")[0]
    l0.append(
        {
            "copy": copy,
            "table": table,
            "bom_share": files["bom"].mean(),
            "crlf_only_share": ((files["crlf"] > 0) & (files["lf"] == 0)).mean(),
            "utf8_errors": int(files["utf8_errors"].sum()),
            "nul_bytes": int(files["nul_bytes"].sum()),
            "ragged_rows": int(files["ragged"].sum()),
            "grammar_errors": int(files["grammar_error"].notna().sum()),
            "bom_inside_header_name": int(files["header_bom_in_name"].sum()),
            "duplicate_file_hashes": int(files["sha256"].duplicated().sum()),
            "missing_days": len(full.difference(dated)) if len(dated) else 0,
            "filename_date_mismatch": int(
                (
                    pd.to_datetime(file_day, format="%Y%m%d", errors="coerce")
                    != files["partition_date"]
                ).sum()
            )
            if len(dated)
            else 0,
        }
    )
l0 = pd.DataFrame(l0).set_index(["copy", "table"])
display(
    l0.style.format({"bom_share": "{:.0%}", "crlf_only_share": "{:.0%}"})
    .format("{:,}", subset=l0.columns[2:])
    .background_gradient(subset=["missing_days", "duplicate_file_hashes"], cmap=theme.cmap_seq())
)

# %%
daily = []
for (copy, table), (files, _, _) in FPS.items():
    if files["partition_date"].notna().any():
        d = files.groupby("partition_date")["records"].sum().reset_index()
        daily.append(d.assign(copy=copy, table=table))
daily = pd.concat(daily)
fig = px.line(
    daily,
    x="partition_date",
    y="records",
    color="copy",
    facet_row="table",
    height=170 * daily["table"].nunique(),
    color_discrete_map=COLOR,
    render_mode="svg",
    labels={"partition_date": "", "records": ""},
)
fig.update_yaxes(matches=None, showticklabels=True)
fig.for_each_annotation(
    lambda a: a.update(text=a.text.split("=")[-1], textangle=0, x=0.0, xanchor="left")
)
fig.update_layout(
    title="Records per daily partition, by copy (from the raw files)", hovermode="x unified"
)
fig.show()

# %% [markdown]
# ## 3 · Lexical layer: inferred types and formats (L2)
# For each column the **inferred type** is the first type on the lattice `boolean ⊂ integer ⊂ decimal ⊂ date ⊂
# timestamp ⊂ time ⊂ json ⊂ ip ⊂ string` that covers ≥ 99.9% of the non-empty values. *Formats* are the value
# classes actually present, with their shares. A column whose values do not all fit its type has **minority
# formats**, listed per file below.

# %%
contracts, anomalies = {}, []
for table in TABLES:
    files, lex, voc = FPS[("main", table)]
    header = json.loads(files["header"].iloc[0])
    low_card = voc.groupby("column")["value"].nunique()
    vocab = {
        c: sorted(voc.loc[voc["column"] == c, "value"].dropna().astype(str).unique().tolist())
        for c in low_card.index
        # never enumerate personal data or free text into a committed artefact
        if low_card[c] <= 60 and c not in PII and c not in TEXT
    }
    contracts[table] = rf.table_contract(table, lex, header, vocab)
    m = rf.minority_formats(lex, contracts[table])
    anomalies.append(m.assign(table=table))
anomalies = pd.concat(anomalies)

ctab = pd.DataFrame(
    [
        {
            "table": t,
            "column": c,
            "type": s["type"],
            "coverage": s["coverage"],
            "formats": ", ".join(f"{k} {v:.1%}" for k, v in s["formats"].items()),
            "empty_share": s["empty_share"],
            "non_ascii_share": s["non_ascii_share"],
            "max_len": s["length"][1],
        }
        for t, ct in contracts.items()
        for c, s in ct["columns"].items()
    ]
)
show(
    ctab,
    caption="Inferred contract per column (main copy, all files)",
    pageLength=15,
    classes="display compact",
    scrollX=True,
)

# %%
types = ctab.pivot_table(
    index="table", columns="type", values="column", aggfunc="count", fill_value=0
)
fig = px.imshow(types, text_auto=True, color_continuous_scale=theme.SEQ_SCALE, aspect="auto")
fig.update_layout(title="Inferred column types per table", height=420, coloraxis_showscale=False)
fig.show()
multi = ctab[ctab["formats"].str.count(",") >= 1].copy()
h(
    f"**{len(multi)} columns carry more than one value format** (coexisting formats are design or source "
    "heterogeneity, not necessarily errors):"
)
display(multi[["table", "column", "type", "formats", "empty_share"]].reset_index(drop=True))

# %%
if len(anomalies):
    agg = (
        anomalies.groupby(["table", "column", "expected_type", "found_class"])
        .agg(
            files=("file", "nunique"),
            values=("n", "sum"),
            first_day=("partition_date", "min"),
            last_day=("partition_date", "max"),
        )
        .reset_index()
    )
    h("**Minority formats** (values the inferred type does not cover):")
    display(agg)
else:
    agg = pd.DataFrame(
        columns=[
            "table",
            "column",
            "expected_type",
            "found_class",
            "files",
            "values",
            "first_day",
            "last_day",
        ]
    )
    h("**No minority formats**: every non-empty value fits its column's inferred type.")

# %% [markdown]
# ## 4 · Change detection across time (L0–L3), main copy
# Every daily fingerprint is classified. Only what is **not stable** is reported, plus columns where several
# formats coexist every day. `intermittent` values (rare but recurring, e.g. `is_fraud = True` on most days)
# are natural variation and are not reported.

# %%
findings = []
for table in TABLES:
    files, lex, voc = FPS[("main", table)]
    findings.append(cd.detect_table(files, lex, voc).assign(copy="main", table=table))
findings = pd.concat(findings, ignore_index=True)
heat = findings.pivot_table(
    index="table", columns="kind", values="signal", aggfunc="count", fill_value=0
)
fig = px.imshow(
    heat.reindex(TABLES, fill_value=0),
    text_auto=True,
    color_continuous_scale=theme.SEQ_SCALE,
    aspect="auto",
)
fig.update_layout(
    title="Findings per table and kind (main copy)", height=440, coloraxis_showscale=False
)
fig.show()
show(
    findings.drop(columns=["copy"]),
    caption="All findings, main copy",
    pageLength=15,
    classes="display compact",
    scrollX=True,
)


# %%
def class_timeline(table, column, copy="main"):
    """Daily share of each value class of one column: the evidence behind an L2 finding."""
    _, lex, _ = FPS[(copy, table)]
    shares = rf.class_share_matrix(lex, column)
    shares = shares.loc[:, (shares > 0).any()]
    fig = go.Figure()
    for i, c in enumerate(shares.columns):
        fig.add_scatter(
            x=shares.index,
            y=100 * shares[c],
            name=c,
            stackgroup="one",
            mode="lines",
            line=dict(width=0.5, color=theme.CATEGORICAL[i % 8]),
        )
    fig.update_layout(
        title=f"{table}.{column}: value classes per day (% of rows, raw text)",
        height=320,
        yaxis_title="% of rows",
        hovermode="x unified",
    )
    fig.show()


for _, f in findings[findings["level"] == "L2"].drop_duplicates(["table", "column"]).iterrows():
    class_timeline(f["table"], f["column"])

# %% [markdown]
# ## 5 · Positive control on real data: main vs backup
# The backup copy is a real, known-different source (study `01–11`): its vocabularies are partly translated and
# some amounts are redenominated. The forensics must see this **from the raw text alone**.

# %%
cmp_rows = []
for table in TABLES:
    if ("backup", table) not in FPS:
        cmp_rows.append(
            {
                "table": table,
                "column": None,
                "difference": "table absent from the backup",
                "detail": "",
            }
        )
        continue
    fm, lm, vm = FPS[("main", table)]
    fb, lb, vb = FPS[("backup", table)]
    hm, hb = set(fm["header"]), set(fb["header"])
    if hm != hb:
        cmp_rows.append(
            {"table": table, "column": None, "difference": "header differs", "detail": str(hb - hm)}
        )
    cb = rf.table_contract(table, lb, json.loads(fb["header"].iloc[0]))
    for col, sm in contracts[table]["columns"].items():
        sb = cb["columns"].get(col)
        if sb is None:
            continue
        if sm["type"] != sb["type"]:
            cmp_rows.append(
                {
                    "table": table,
                    "column": col,
                    "difference": "inferred type",
                    "detail": f"{sm['type']} -> {sb['type']}",
                }
            )
        new_fmt = set(sb["formats"]) - set(sm["formats"])
        if new_fmt:
            cmp_rows.append(
                {
                    "table": table,
                    "column": col,
                    "difference": "new value formats",
                    "detail": ", ".join(sorted(new_fmt)),
                }
            )
    for col in sorted(set(vm["column"]) & set(vb["column"])):
        a = set(vm.loc[vm["column"] == col, "value"].dropna().astype(str))
        b = set(vb.loc[vb["column"] == col, "value"].dropna().astype(str))
        only_b, only_m = b - a, a - b
        if only_b and len(a) <= 60:
            cmp_rows.append(
                {
                    "table": table,
                    "column": col,
                    "difference": f"vocabulary: {len(only_b)} values only in backup",
                    "detail": " | ".join(sorted(only_b)[:4])
                    + "  vs main: "
                    + " | ".join(sorted(only_m)[:4]),
                }
            )
backup_cmp = pd.DataFrame(cmp_rows)
show(
    backup_cmp,
    caption="What the raw text alone reveals about the backup copy",
    pageLength=20,
    classes="display compact",
    scrollX=True,
)

# %%
scale = con.sql(f"""
    with m as (select currency, median(try_cast(current_balance as double)) bal from {raw_src("main", "products")}
               where try_cast(current_balance as double) > 0 group by 1),
         b as (select currency, median(try_cast(current_balance as double)) bal from {raw_src("backup", "products")}
               where try_cast(current_balance as double) > 0 group by 1)
    select coalesce(m.currency, b.currency) currency, m.bal main_median, b.bal backup_median
    from m full join b using (currency) order by 1""").df()
h(
    "**Unit check on `products.current_balance` by stated currency** (raw text, positive balances): a currency "
    "whose median moves by a factor near an FX rate between copies indicates redenominated amounts."
)
display(scale.style.format({"main_median": "{:,.2f}", "backup_median": "{:,.2f}"}, na_rep="—"))
mix = []
for copy in RAW:
    v = FPS[(copy, "products")][2]
    v = v[v["column"] == "currency"].groupby("value")["n"].sum()
    mix.append((v / v.sum()).rename(copy))
h("**Currency mix of `products` per copy** (share of rows):")
display(pd.concat(mix, axis=1).style.format("{:.2%}"))
h(
    "Neither the per-currency medians nor the currency mix move between copies, yet study `01–11` linked records "
    "and found products restated from COP to USD with amounts divided by 4,000. **Column-level forensics cannot "
    "see an entity-level restatement that preserves every marginal distribution**; only record linkage on "
    "natural keys can (phase E). The vocabulary translation and the null-semantics change below are visible "
    "from the raw text alone."
)
clicked = []
for copy in RAW:
    v = FPS[(copy, "campaign_sends")][2]
    clicked.append(v[v["column"] == "was_clicked"].groupby("value")["n"].sum().rename(copy))
h(
    "**`campaign_sends.was_clicked` per copy**: the backup leaves the flag empty where main writes `False`."
)
display(pd.concat(clicked, axis=1).fillna(0).astype(int).rename(index={"": "(empty)"}))

# %% [markdown]
# ## 6 · Row invariants from the raw text (L3b)
# Consistency rules that a schema cannot express. Each is computed on the raw text with `try_cast`, so a
# value that does not parse is counted, never dropped.

# %%
EVENT_TS = {
    "transactions": "transaction_date",
    "digital_events": "event_date",
    "call_center_interactions": "interaction_date",
    "complaints": "creation_date",
    "satisfaction_surveys": "survey_date",
    "campaign_sends": "send_date",
}
inv = []
for table, ts in EVENT_TS.items():
    r = con.sql(f"""
        select count(*) n,
               count(*) filter (where try_cast({ts} as timestamp) is null and {ts} <> '') unparsable_ts,
               count(*) filter (where cast(try_cast({ts} as timestamp) as date) <> try_cast(process_date as date)) process_ne_event,
               count(*) filter (where try_cast(process_date as date) <> try_cast(regexp_extract(filename, '_(\\d{{8}})\\.csv$', 1) as date)) process_ne_file
        from {raw_src("main", table)}""").fetchone()
    inv.append(
        {
            "table": table,
            "rows": r[0],
            "unparsable_event_ts": r[1],
            "process_date_ne_event_date": r[2],
            "process_date_ne_file_date": r[3],
        }
    )
inv = pd.DataFrame(inv)
inv["process_ne_event_pct"] = 100 * inv["process_date_ne_event_date"] / inv["rows"]
display(
    inv.style.format(
        {
            "rows": "{:,}",
            "unparsable_event_ts": "{:,}",
            "process_date_ne_event_date": "{:,}",
            "process_date_ne_file_date": "{:,}",
            "process_ne_event_pct": "{:.2f}%",
        }
    )
)

# %%
lag = con.sql(f"""
    select date_diff('day', cast(try_cast(event_date as timestamp) as date), try_cast(process_date as date)) lag_days,
           count(*) n
    from {raw_src("main", "digital_events")} group by 1 order by 1""").df()
fig = px.bar(lag, x="lag_days", y="n", color_discrete_sequence=[theme.BLUE], log_y=True)
fig.update_layout(
    title="digital_events: process_date − event date (days; log scale)",
    height=320,
    xaxis_title="days between the event and its processing date",
    yaxis_title="rows",
)
fig.show()

# %%
tx = raw_src("main", "transactions")
fx_check = con.sql(f"""
    select currency, count(*) n,
           count(*) filter (where amount_usd = '') usd_empty,
           median(try_cast(amount as double) / nullif(try_cast(amount_usd as double), 0)) implied_rate,
           count(*) filter (where abs(try_cast(latitude as double)) <= 1.5 and abs(try_cast(longitude as double)) <= 1.5) null_island,
           count(*) filter (where latitude <> '') with_coordinates,
           count(*) filter (where regexp_full_match(latitude, '.*[eE].*') or regexp_full_match(longitude, '.*[eE].*')) scientific_coords
    from {tx} group by 1 order by n desc""").df()
h("**transactions: currency conversion and coordinates, from the raw text**")
display(
    fx_check.style.format(
        {
            "n": "{:,}",
            "usd_empty": "{:,}",
            "implied_rate": "{:,.2f}",
            "null_island": "{:,}",
            "with_coordinates": "{:,}",
            "scientific_coords": "{:,}",
        }
    )
)
life = con.sql(f"""
    select count(*) n,
           count(*) filter (where try_cast(resolution_date as timestamp) < try_cast(creation_date as timestamp)) resolved_before_created,
           count(*) filter (where try_cast(closing_date as timestamp) < try_cast(resolution_date as timestamp)) closed_before_resolved,
           count(*) filter (where try_cast(first_response_date as timestamp) < try_cast(creation_date as timestamp)) responded_before_created
    from {raw_src("main", "complaints")}""").df()
h("**complaints: lifecycle order (raw text)**")
display(life)

# %% [markdown]
# **Batch windows.** `process_date` precedes the event date on a quarter or more of the rows, never the reverse:
# a record cannot be processed before it happens, so the two dates do not share a clock. For each daily file,
# the window of event timestamps it contains shows the batch cut-off of its source.

# %%
win = []
for copy in RAW:
    for table, ts in EVENT_TS.items():
        if (copy, table) not in FPS:
            continue
        r = con.sql(f"""
            with w as (select filename, min(try_cast({ts} as timestamp)) lo, max(try_cast({ts} as timestamp)) hi,
                              any_value(try_cast(process_date as date)) d
                       from {raw_src(copy, table)} group by 1)
            select mode(hour(lo)) cut_hour, avg(date_diff('hour', lo, hi)) span_hours,
                   avg((cast(lo as date) = d)::int) starts_on_partition_day from w""").fetchone()
        win.append(
            {
                "copy": copy,
                "table": table,
                "window_starts": f"{r[0]:02d}:00",
                "span_hours": r[1],
                "starts_on_partition_day": r[2],
            }
        )
win = pd.DataFrame(win)
display(win.pivot_table(index="table", columns="copy", values="window_starts", aggfunc="first"))
hours = con.sql(f"""
    select date_diff('day', cast(try_cast(transaction_date as timestamp) as date), try_cast(process_date as date)) as lag,
           hour(try_cast(transaction_date as timestamp)) as hr, count(*) as n
    from {raw_src("main", "transactions")} group by 1, 2 order by 2""").df()
fig = px.bar(
    hours,
    x="hr",
    y="n",
    color=hours["lag"].map({0: "same day", -1: "event the next day"}),
    color_discrete_sequence=[theme.BLUE, theme.ORANGE],
    barmode="stack",
)
fig.update_layout(
    title="transactions: event hour, split by event date vs process_date (raw text)",
    height=340,
    xaxis_title="hour of the event timestamp",
    yaxis_title="rows",
    legend_title_text="",
)
fig.show()

# %% [markdown]
# ## 7 · Keys across files and foreign-key coverage (L4)
# A primary key that appears in two daily files is a restatement or a replay: bronze must keep both, silver
# must decide. Foreign-key coverage is measured per day against the dimension snapshots.

# %%
pk_rows = []
for copy in RAW:
    for table in TABLES:
        if (copy, table) not in FPS or table not in PK:
            continue
        r = con.sql(f"""
            select count(*) n, count(distinct {PK[table]}) d,
                   count(*) filter (where {PK[table]} = '') empty_keys
            from {raw_src(copy, table)}""").fetchone()
        multi = con.sql(f"""select count(*) from (select {PK[table]} from {raw_src(copy, table)}
                            group by 1 having count(distinct filename) > 1)""").fetchone()[0]
        pk_rows.append(
            {
                "copy": copy,
                "table": table,
                "rows": r[0],
                "duplicate_rows": r[0] - r[1],
                "empty_keys": r[2],
                "keys_in_several_files": multi,
            }
        )
pk_tab = pd.DataFrame(pk_rows)
display(
    pk_tab.style.format(
        "{:,}", subset=["rows", "duplicate_rows", "empty_keys", "keys_in_several_files"]
    )
)

# %%
cust = raw_src("main", "customers")
fk_daily = []
for table in [
    "transactions",
    "call_center_interactions",
    "complaints",
    "digital_events",
    "campaign_sends",
]:
    d = con.sql(f"""
        select try_cast(f.process_date as date) as day, count(*) as n,
               count(*) filter (where f.customer_id <> '' and c.customer_id is null) orphans,
               count(*) filter (where f.customer_id = '') empty_fk
        from {raw_src("main", table)} f left join (select customer_id from {cust}) c using (customer_id)
        group by 1 order by 1""").df()
    fk_daily.append(d.assign(table=table))
fk_daily = pd.concat(fk_daily)
fk_daily["orphan_pct"] = 100 * fk_daily["orphans"] / fk_daily["n"]
fk_daily["empty_pct"] = 100 * fk_daily["empty_fk"] / fk_daily["n"]
fig = px.line(
    fk_daily,
    x="day",
    y=["orphan_pct", "empty_pct"],
    facet_row="table",
    height=900,
    render_mode="svg",
    color_discrete_sequence=[theme.RED, theme.SEQ_BLUE[2]],
    labels={"value": "%", "day": ""},
)
fig.update_yaxes(matches=None)
fig.for_each_annotation(
    lambda a: a.update(text=a.text.split("=")[-1], textangle=0, x=0.0, xanchor="left")
)
fig.update_layout(
    title="customer_id per day: orphans and empty references (% of rows)", hovermode="x unified"
)
fig.show()

# %% [markdown]
# ## 8 · Can the detectors be trusted? Synthetic positive controls
# `scripts/mutate_partitions.py` injected ten known schema changes into copies of 90 real daily transaction files
# (verbatim before day 45, mutated from it), ran the same fingerprinting and detection, and compared the
# findings with a clean copy of the same window: **recall**, **delay** in days and **false alarms** before the
# change.

# %%
score = pd.read_csv(OUT / "forensics_detector_scorecard.csv")
display(score.style.format(na_rep="—"))
mut = score[score["mutation"] != "clean_copy"]
h(
    f"**Recall {mut['detected'].mean():.0%}** ({int(mut['detected'].sum())}/{len(mut)}), median delay "
    f"**{mut['delay_days'].median():.0f} days**, **{int(mut['false_alarms_before_change'].sum())} false alarms** "
    "before the changes."
)

# %% [markdown]
# ## 9 · Propagation audit: what the typed copies kept and lost
# For each column: what the raw text contains (empties, codes with leading zeros, timezone suffixes,
# scientific notation, fractional digits) against the type and nulls in the EDA Parquet copy and in bronze v1.
# A loss is anything the raw text says that a typed copy can no longer reproduce.


# %%
def typed_info(path_expr):
    rows = con.sql(f"describe select * from {path_expr}").fetchall()
    types = {r[0]: r[1] for r in rows}
    cols = [c for c in types if not c.startswith("_")]
    nulls = con.sql(
        "select " + ", ".join(f"count(*) - count({rf.q(c)})" for c in cols) + f" from {path_expr}"
    ).fetchone()
    return types, dict(zip(cols, nulls))


prop = []
for table in TABLES:
    _, lex, _ = FPS[("main", table)]
    sums = lex.groupby("column")[[c for c in lex.columns if c.startswith("n_") or c == "n"]].sum()
    pq_types, pq_nulls = typed_info(f"'{DATA / 'parquet' / table}.parquet'")
    bronze = DATA / "lake" / "bronze" / table
    if bronze.exists():
        b_types, b_nulls = typed_info(f"read_parquet('{bronze}/**/*.parquet', union_by_name=true)")
        hold = DATA / "lake" / "holdout" / table
        if hold.exists() and any(hold.rglob("*.parquet")):
            _, h_nulls = typed_info(f"read_parquet('{hold}/**/*.parquet', union_by_name=true)")
            b_nulls = {c: b_nulls.get(c, 0) + h_nulls.get(c, 0) for c in b_nulls}
    else:
        b_types, b_nulls = {}, {}
    fracmax = lex.groupby("column")["max_fraction_digits"].max()
    for col, s in sums.iterrows():
        losses = []
        t_pq, t_b = pq_types.get(col, "absent"), b_types.get(col, "absent")
        numeric = ("INT", "BIGINT", "DOUBLE", "DECIMAL", "FLOAT")
        if s["n_int_leading_zero"] and (t_pq.startswith(numeric) or t_b.startswith(numeric)):
            losses.append("leading zeros")
        if s["n_ts_tz"] and "WITH TIME ZONE" not in t_pq:
            losses.append("timezone suffix")
        if s["n_empty"] and pq_nulls.get(col, 0) == s["n_empty"]:
            losses.append("'' became NULL")
        prop.append(
            {
                "table": table,
                "column": col,
                "raw_empty": int(s["n_empty"]),
                "raw_null_tokens": int(s["n_null_token"]),
                "raw_leading_zero_codes": int(s["n_int_leading_zero"]),
                "raw_tz_values": int(s["n_ts_tz"]),
                "raw_scientific": int(s["n_sci"]),
                "raw_max_fraction_digits": fracmax.get(col),
                "parquet_type": t_pq,
                "parquet_nulls": pq_nulls.get(col),
                "bronze_v1_type": t_b,
                "bronze_v1_nulls": b_nulls.get(col),
                "losses": ", ".join(losses),
            }
        )
prop = pd.DataFrame(prop)
show(
    prop,
    caption="Raw text vs typed copies, per column",
    pageLength=15,
    classes="display compact",
    scrollX=True,
)
h("**Columns where a typed copy can no longer reproduce the raw text:**")
display(
    prop[prop["losses"] != ""][
        ["table", "column", "raw_empty", "parquet_type", "bronze_v1_type", "losses"]
    ].reset_index(drop=True)
)

# %% [markdown]
# ## 10 · Evidence written for the next phases
# * `reports/contracts/<table>.json`: the inferred, versioned contract of each table (type, formats, empty share,
#   length, vocabulary for low-cardinality columns). Phase 3 promotes them, after review, into the silver contracts.
# * `reports/tables/schema_change_log.csv`: every finding of §4 with its change date.
# * `reports/tables/raw_format_anomalies.csv`: minority formats per table and column (§3).
# * `reports/tables/propagation_audit.csv`: §9.

# %%
CONTRACTS.mkdir(parents=True, exist_ok=True)
for table, c in contracts.items():
    (CONTRACTS / f"{table}.json").write_text(
        json.dumps(c, indent=1, ensure_ascii=False, default=str) + "\n"
    )
findings.drop(columns=["copy"]).to_csv(OUT / "schema_change_log.csv", index=False)
# one row per typed column, zero included: "no minority format" is evidence too
typed_cols = ctab.loc[ctab["type"] != "string", ["table", "column", "type"]].rename(
    columns={"type": "expected_type"}
)
per_col = agg.groupby(["table", "column"]).agg(
    minority_values=("values", "sum"),
    files_affected=("files", "sum"),
    classes=("found_class", lambda x: ", ".join(sorted(x))),
)
anomaly_table = typed_cols.merge(per_col, on=["table", "column"], how="left").fillna(
    {"minority_values": 0, "files_affected": 0, "classes": ""}
)
anomaly_table.to_csv(OUT / "raw_format_anomalies.csv", index=False)
prop.to_csv(OUT / "propagation_audit.csv", index=False)
h(
    f"Wrote {len(contracts)} contracts, {len(findings)} findings, {len(agg)} anomaly groups, {len(prop)} audited columns."
)

# %% [markdown]
# ## 11 · Verdict and findings
# **Verdict.** No table changed its *declared* schema: one header per table in every partition of both copies,
# every record accounted for (raw lines − headers − embedded newlines = records, with 0 unexplained), no ragged
# rows, no grammar errors, no encoding errors, no duplicate or empty primary keys, no key in two files, no minority
# formats in typed columns. The detectors find every one of ten injected schema changes on the day they happen,
# with no false alarms. **But the raw text does carry undeclared changes and semantic traps that every typed copy
# would propagate silently.** Each finding names the layer that must act.
#
# **Undeclared evolution and defects inside the content**
# 1. **A null leaked into source text.** `campaign_sends.subject` contains `¡Oferta especial en nan!` on
#    **38,142 sends (6.8% of sends with a subject)** from 2024-01-12 to 2026-05-09: a template rendered with a
#    missing product, the Python `NaN` serialised as the word `nan`. Valid text to any typed check.
#    *Silver:* flag `V`/`I` and treat as missing product; *source:* report the defect.
# 2. **Channels were added and removed mid-stream.** `send_channel = WhatsApp` is born on 2023-07-10 and
#    `Voice` lives from 2023-12-01 to 2026-03-23, both without open/click tracking. As they ramp up, the empty share of
#    `was_opened` rises from 6% to 25% and of `open_date`/`open_device`/`open_country` from ~62% to ~72%
#    (Sept–Dec 2023). This is **instrumentation drift**, not behaviour: funnel KPIs must be computed per channel.
# 3. **`subject` exists only for e-mail**, so its empty share follows the channel mix (53% → 82%).
#
# **Semantic traps a schema cannot express**
# 4. **`process_date` is a batch-window date, not the event date.** Each daily file holds a 24-hour window of event
#    timestamps that starts at a source-specific cut-off: **06:00** for transactions, digital events and campaign
#    sends, **08:00** for call-center interactions and complaints, **10:00 (≈ 42 h windows)** for surveys, identical
#    in both copies. So 25% (transactions) to 79% (surveys) of rows have an event date after their `process_date`,
#    never before, and the event timestamps carry **no timezone**. *Silver/gold:* date facts by the event timestamp,
#    keep `process_date` as the load date, and record the timezone assumption in the contract.
# 5. **Three cut-off families point to at least three source systems** (core banking/digital/marketing, contact
#    center, survey platform): input to phase E (keys and source systems).
# 6. **The same country is spelled two ways** (`México`/`Mexico`) in `transactions.transaction_country` and
#    `digital_events.ip_country`. *Silver:* conformed country dimension.
# 7. **Coordinates near (0, 0) are placeholders**: 407,656 USD transactions, some written in scientific notation
#    (`6.57e-05`). *Silver:* null them.
# 8. **Codes with leading zeros coexist with plain digits** in `postal_code`, `document_number`, `product_number`
#    and `response_code`: they are codes and must stay text. The typed copies kept them as VARCHAR (§9), so no
#    leading zero was lost; a numeric cast anywhere downstream would destroy them.
#
# **What propagated to the typed copies (§9)**
# 9. In **103 columns** an empty raw field became NULL in Parquet and bronze v1. The raw files have no null token,
#    so `''` is the only absence marker and the meaning survives, but the representation does not: lossless bronze
#    (section B of the methodology) keeps `''`.
# 10. Nothing else was lost: no leading zeros, no timezone suffixes (none exist), no dropped rows.
#
# **Positive control: the backup copy, from the raw text alone**
# 11. Detected: the **translated vocabulary** (`Inbound Call` → `Llamada Entrante`), **different null semantics**
#     (`was_clicked` empty on 87,081 rows where main writes `False`), two tables missing and transactions covering
#     453 days.
# 12. **Not detectable at column level:** the COP → USD restatement of products (÷ 4,000) found by study `01–11`.
#     Per-currency medians and the currency mix are identical in both copies because whole entities moved between
#     currencies while every marginal distribution was preserved. **Entity-level restatements need record linkage
#     on natural keys** (phase E); column-level forensics are necessary but not sufficient.
