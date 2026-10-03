# %% [markdown]
# # 01 · Raw tables: complete profile
# **Medallion re-analysis, layer 0 (raw)** · LATAM Bank dataset (Factored Datathon 2026)
#
# ## Why this notebook exists
# The platform moves the 13 source tables through **raw → bronze → silver → gold (Kimball star schemas)**.
# Every later layer cleans, conforms or models something it found here. This notebook is the
# baseline: a complete, table-by-table profile of the raw Parquet extracts in `data/parquet/`,
# so each transformation downstream can be judged against what the source really looked like.
#
# | layer | notebook | question |
# |---|---|---|
# | raw | **01 (this one)** | What is in each source table: shape, types, gaps, distributions, relationships? |
# | bronze | 02 | What did ingestion change (types, rejects, quarantine, lineage columns)? |
# | silver | 03 | Did conformance fix the raw issues found here (labels, currencies, keys)? |
# | gold | 04 | Do the Kimball facts and dimensions reconcile with the raw totals? |
#
# ## How to read it
# * **Exact vs. sample.** Counts, nulls, `describe`, value counts, histograms, crosstabs and time profiles
#   are computed by **DuckDB on the full table** (exact). Views that need pandas: `info()`, missingno,
#   KDEs and association matrices use a **reproducible sample** of at most 200,000 rows
#   (the rows with the lowest `hash(primary key, 42)`; small tables are used whole). Each view says which.
# * **Null vs. missing.** *Nulls* are SQL `NULL`s. *Missing* adds **disguised** missing values:
#   blank strings and placeholders such as `'N/A'`, `'None'`, `'null'`. Raw extracts often hide gaps this way.
# * **Money** columns are heavy-tailed, so their histograms and KDEs use a **log10 scale**.
# * **PII.** Names, document numbers, e-mails, phones, addresses, IPs and dates of birth are profiled by
#   **shape and cardinality only** (`A` = letters, `9` = digit run); their values are never printed.
# * **Interactivity.** Plotly charts zoom and hover; tables are searchable. The **explorers** in the last
#   section are ipywidgets and need a **live kernel**: in the HTML export they show nothing.
#
# ## Contents
# 1. Toolkit · 2. Inventory and referential integrity
# 3. Core banking: customers, products, transactions, daily exchange rates
# 4. Network and people: branches, service agents
# 5. Customer service: call-center interactions, call transcripts, satisfaction surveys, complaints
# 6. Marketing: marketing campaigns, campaign sends
# 7. Digital: digital events
# 8. Interactive explorers · 9. Findings to carry into bronze and silver

# %% [markdown]
# ## 1 · Toolkit
# Shared helpers. Everything statistical lives in `latam_eda.profiling` (tested in `eda/tests/test_profiling.py`);
# the functions below only lay out the figures, so you can tweak a view without touching the statistics.

# %%
import sys

sys.path.insert(0, "../../src")
import warnings

import matplotlib.pyplot as plt
import missingno as msno
import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from IPython.display import Markdown, display
from itables import init_notebook_mode, show
from plotly.subplots import make_subplots
from scipy.stats import gaussian_kde

from latam_eda import profiling as p
from latam_eda import theme
from latam_eda.data import DIMS, FACTS, PK, connect

warnings.filterwarnings("ignore", category=FutureWarning)
theme.register()
theme.register_mpl()
init_notebook_mode(all_interactive=False, connected=False)  # DataTables embedded: works offline
pd.options.display.float_format = "{:,.2f}".format
pd.options.display.max_columns = 40
con = connect()

TABLES = DIMS + FACTS
BLUE_RGB = tuple(int(theme.BLUE[i : i + 2], 16) / 255 for i in (1, 3, 5))
# Heavy-tailed money columns and multi-scale FX rates: binned and smoothed on log10
MONEY = {
    "exchange_rate",
    "buy_rate",
    "sell_rate",
    "amount",
    "amount_usd",
    "current_balance",
    "credit_limit",
    "estimated_monthly_income",
    "claimed_amount",
    "compensation_granted",
    "conversion_value",
    "budget",
    "send_cost",
    "event_value",
}
# (partition date, event timestamp) of each time-stamped table
TIME = {
    "transactions": ("process_date", "transaction_date"),
    "digital_events": ("process_date", "event_date"),
    "call_center_interactions": ("process_date", "interaction_date"),
    "call_transcripts": ("process_date", None),
    "campaign_sends": ("process_date", "send_date"),
    "complaints": ("process_date", "creation_date"),
    "satisfaction_surveys": ("process_date", "survey_date"),
    "daily_exchange_rates": ("date", None),
}
OV: dict[str, pd.DataFrame] = {}  # overview per table, filled as sections run
_samples: dict[str, pd.DataFrame] = {}


def rel(t):
    return f"m_{t}"


def smp(t, n=200_000):
    """Cached reproducible sample of table t (whole table when small)."""
    if t not in _samples:
        _samples[t] = p.sample(con, rel(t), n=n, key=PK.get(t))
    return _samples[t]


def kinds(t, *ks):
    return p.cols_of(con, rel(t), *ks)


def has_cols(t, *cols):
    """True when every picked column exists in table t (widgets fire mid-update with stale picks)."""
    names = set(p.columns(con, rel(t))["column"])
    return all(c in names for c in cols if c and c != "(none)")


def missing_view(df):
    """Placeholders ('', 'N/A', 'None'...) turned into NaN, for the 'missing data' views."""
    out = df.copy()
    for c in out.columns:
        if pd.api.types.is_string_dtype(out[c]) or out[c].dtype == object:
            s = out[c].astype("string").str.strip().str.lower()
            out[c] = out[c].mask(s.isin(p.PLACEHOLDERS))
    return out


def h(text):
    display(Markdown(text))


def rgba(colour, alpha):
    """'#rrggbb' -> 'rgba(r,g,b,a)' for translucent fills."""
    return f"rgba({int(colour[1:3], 16)},{int(colour[3:5], 16)},{int(colour[5:7], 16)},{alpha})"


def kde(x, log=False, points=256, n=20_000):
    """Gaussian KDE of a numeric series on a grid (on log10 values when `log`), from up to n values."""
    x = pd.Series(x).dropna().astype(float)
    if log:
        x = x[x > 0]
    if x.nunique() < 3:
        return np.array([]), np.array([])
    x = x.sample(min(len(x), n), random_state=0)
    v = np.log10(x) if log else x
    grid = np.linspace(v.min(), v.max(), points)
    dens = gaussian_kde(v)(grid)
    return (10**grid if log else grid), dens


def kde_fig(groups, title, log=False, height=360, xaxis_title=None):
    """Overlaid filled KDE curves for {label: series}; click legend items to hide or isolate them."""
    fig = go.Figure()
    for i, (label, x) in enumerate(list(groups.items())[:8]):  # one fixed palette slot each
        gx, gy = kde(x, log=log)
        if not len(gx):
            continue
        c = theme.CATEGORICAL[i]
        fig.add_scatter(
            x=gx,
            y=gy,
            mode="lines",
            name=str(label),
            fill="tozeroy",
            line=dict(color=c, width=2),
            fillcolor=rgba(c, 0.15),
            hovertemplate=f"{label}: %{{x:,.2f}}<extra></extra>",
        )
    fig.update_layout(
        title=title,
        height=height,
        xaxis_title=xaxis_title,
        yaxis_title="density" + (" (per log10 unit)" if log else ""),
        hovermode="x unified",
    )
    if log:
        fig.update_xaxes(type="log")
    return fig


def dist_fig(df, x, by, kind="box", log=False, title="", n=20_000, order=None, color=None):
    """Interactive horizontal box or violin plot of `x` per level of `by`, on up to n sampled rows."""
    cols = [x, by] + ([color] if color and color != by else [])
    d = df[cols].dropna()
    if log:
        d = d[d[x] > 0]
    d = d.sample(min(len(d), n), random_state=0)
    order = order or d.groupby(by)[x].median().sort_values().index.tolist()
    extra = {"points": False} if kind == "box" else {"points": False, "box": True}
    fn = px.box if kind == "box" else px.violin
    fig = fn(
        d,
        x=x,
        y=by,
        color=color,
        orientation="h",
        category_orders={by: order},
        color_discrete_sequence=theme.CATEGORICAL if color else [theme.BLUE],
        log_x=log,
        **extra,
    )
    fig.update_layout(title=title, height=max(300, 48 * len(order) + 150), yaxis_title="")
    if kind == "violin":  # full-height violins, clipped to the observed range
        fig.update_traces(width=0.85, scalemode="width", spanmode="hard")
    fig.update_yaxes(type="category")
    return fig


def matrix_fig(m, title, scale, zmin, zmax):
    """Lower-triangle heatmap of a symmetric matrix (diagonal dropped), values on hover and in cells."""
    m = m.iloc[1:, :-1].copy()
    m = m.mask(np.triu(np.ones(m.shape, dtype=bool), 1))
    fig = go.Figure(
        go.Heatmap(
            z=m.values,
            x=m.columns,
            y=m.index,
            colorscale=scale,
            zmin=zmin,
            zmax=zmax,
            texttemplate="%{z:.2f}" if len(m) <= 14 else None,
            hovertemplate="%{y} × %{x}: %{z:.3f}<extra></extra>",
            hoverongaps=False,
            xgap=1,
            ygap=1,
        )
    )
    fig.update_layout(title=title, height=max(360, 34 * len(m) + 170))
    fig.update_xaxes(tickangle=-35, showgrid=False)
    fig.update_yaxes(autorange="reversed", showgrid=False)
    return fig


def fmt_overview(ov):
    cols = [
        "dtype",
        "kind",
        "non_null",
        "nulls",
        "placeholders",
        "null_pct",
        "missing_pct",
        "distinct",
        "distinct_pct",
    ]
    return (
        ov.set_index("column")[cols]
        .style.format(
            {
                "non_null": "{:,}",
                "nulls": "{:,}",
                "placeholders": "{:,}",
                "distinct": "{:,}",
                "null_pct": "{:.1f}%",
                "missing_pct": "{:.1f}%",
                "distinct_pct": "{:.1f}%",
            }
        )
        .background_gradient(
            cmap=theme.cmap_seq(), subset=["null_pct", "missing_pct"], vmin=0, vmax=100
        )
        .bar(subset=["distinct_pct"], color=theme.SEQ_BLUE[1], vmin=0, vmax=100)
    )


# ---------- per-table core views ----------
def show_overview(t):
    """Shape, primary key, pandas info() on the sample, and the per-column null/missing/distinct table."""
    ov = p.overview(con, rel(t))
    OV[t] = ov
    n = ov.attrs["rows"]
    s = smp(t)
    mem = s.memory_usage(deep=True).sum() * n / max(len(s), 1) / 1e6
    line = f"**Shape** {n:,} rows × {len(ov)} columns · **est. pandas memory (full table)** {mem:,.0f} MB"
    if t in PK:
        k = p.pk_check(con, rel(t), PK[t])
        ok = "unique" if k["duplicate_keys"] == 0 and k["null_keys"] == 0 else "**NOT unique**"
        line += f" · **PK** `{PK[t]}` {ok} ({k['duplicate_keys']:,} duplicated, {k['null_keys']:,} null)"
    else:
        line += " · no single-column primary key"
    h(line)
    h(f"`info()` on the sample ({len(s):,} rows):")
    s.info(memory_usage="deep", show_counts=True)
    display(fmt_overview(ov))


def show_describe(t):
    """Exact describe() of numeric columns, plus describe() of the non-numeric columns (sample)."""
    num = kinds(t, "numeric")
    if num:
        h(
            "**Numeric columns, exact (full table)**: describe plus tails, shape and IQR outlier share"
        )
        d = p.numeric_summary(con, rel(t), num)
        shares = ["zero_share", "negative_share", "iqr_outlier_share"]
        display(
            d.style.format("{:,.2f}")
            .format("{:.1%}", subset=shares)
            .background_gradient(cmap=theme.cmap_seq(), subset=shares, vmin=0, vmax=1)
        )
    other = p.safe(smp(t)).select_dtypes(exclude="number")
    if other.shape[1]:
        h(
            "**Non-numeric columns (sample)**: count, distinct, most frequent value and its frequency"
        )
        display(other.astype("string").describe().T)


def show_missing(t):
    """missingno matrix (rows in time order), bar, nullity correlation heatmap and dendrogram."""
    df = missing_view(smp(t))
    order = TIME.get(t, (None, None))
    sort_col = order[1] or order[0]
    if sort_col and sort_col in df:
        df = df.sort_values(sort_col)
    gaps = [c for c in df.columns if df[c].isna().any()]
    if not gaps:
        h("No nulls or placeholders in this table.")
        return
    h(
        f"**Missing data (nulls + placeholders), sample.** {len(gaps)} of {df.shape[1]} columns have gaps. "
        "The matrix rows run in time order, so a block that starts or stops mid-way means the field "
        "was added or dropped at some date."
    )
    view = df.iloc[:: max(1, len(df) // 3000)]
    fig, axes = plt.subplots(1, 2, figsize=(16, 5.5), gridspec_kw={"width_ratios": [3, 2]})
    msno.matrix(view, ax=axes[0], color=BLUE_RGB, sparkline=False, fontsize=8)
    msno.bar(df, ax=axes[1], color=BLUE_RGB, fontsize=8)
    for ax in axes:
        ax.grid(False)
    axes[0].set_title("Nullity matrix (dark = present)")
    axes[1].set_title("Share present per column")
    plt.tight_layout()
    plt.show()
    partial = [c for c in gaps if df[c].notna().any()]
    if len(partial) >= 2:
        fig, axes = plt.subplots(1, 2, figsize=(16, max(4, 0.35 * len(partial) + 2)))
        msno.heatmap(df[partial], ax=axes[0], cmap=theme.cmap_div(), fontsize=8, cbar=False)
        axes[0].set_title(
            "Nullity correlation (+1 missing together, −1 one or the other; blank = none)"
        )
        for ax in axes:
            ax.grid(False)
        if len(partial) >= 3:
            msno.dendrogram(df[partial], ax=axes[1], fontsize=8, orientation="left")
            axes[1].set_title("Nullity clusters")
        else:
            axes[1].axis("off")
        plt.tight_layout()
        plt.show()


def show_distributions(t, cols=None, per_row=3):
    """SQL-binned histograms over the full table (log10 bins for money) and sample KDEs."""
    num = cols or kinds(t, "numeric")
    if not num:
        return
    rows = -(-len(num) // per_row)
    fig = make_subplots(
        rows=rows,
        cols=per_row,
        subplot_titles=[f"{c} (log10)" if c in MONEY else c for c in num],
        vertical_spacing=0.12 / max(rows, 1) * 3,
    )
    for i, c in enumerate(num):
        hist = p.binned_hist(con, rel(t), c, bins=40, log=c in MONEY)
        mid = (
            (hist["left"] * hist["right"]) ** 0.5
            if c in MONEY
            else (hist["left"] + hist["right"]) / 2
        )
        r, k = divmod(i, per_row)
        fig.add_bar(
            x=mid,
            y=hist["n"],
            marker_color=theme.BLUE,
            showlegend=False,
            row=r + 1,
            col=k + 1,
            customdata=np.c_[hist["left"], hist["right"]],
            hovertemplate="%{customdata[0]:,.2f} – %{customdata[1]:,.2f}<br>%{y:,} rows<extra></extra>",
        )
        if c in MONEY:
            fig.update_xaxes(type="log", row=r + 1, col=k + 1)
    fig.update_layout(
        title=f"{t}: numeric distributions (exact, full table)", height=260 * rows + 80, bargap=0.02
    )
    fig.update_annotations(font_size=12)
    fig.show()

    s = smp(t)
    smooth = [c for c in num if s[c].nunique() > 10]
    if not smooth:
        return
    rows = -(-len(smooth) // per_row)
    fig = make_subplots(
        rows=rows,
        cols=per_row,
        vertical_spacing=0.12 / max(rows, 1) * 3,
        subplot_titles=[f"{c} (log10)" if c in MONEY else c for c in smooth],
    )
    for i, c in enumerate(smooth):
        r, k = divmod(i, per_row)
        gx, gy = kde(s[c], log=c in MONEY)
        if not len(gx):
            continue
        med = s[c].dropna().astype(float)
        med = (med[med > 0] if c in MONEY else med).median()
        fig.add_scatter(
            x=gx,
            y=gy,
            mode="lines",
            fill="tozeroy",
            line=dict(color=theme.BLUE, width=1.6),
            fillcolor=rgba(theme.BLUE, 0.18),
            showlegend=False,
            row=r + 1,
            col=k + 1,
            hovertemplate=f"{c}: %{{x:,.2f}}<extra></extra>",
        )
        # the median as a trace (data coordinates also on log axes)
        fig.add_scatter(
            x=[med, med],
            y=[0, gy.max()],
            mode="lines",
            showlegend=False,
            line=dict(color=theme.INK2, width=1, dash="dash"),
            row=r + 1,
            col=k + 1,
            hovertemplate=f"median {med:,.2f}<extra></extra>",
        )
        if c in MONEY:
            fig.update_xaxes(type="log", row=r + 1, col=k + 1)
    fig.update_layout(
        title=f"{t}: kernel density (sample; dashed = median)", height=240 * rows + 80
    )
    fig.update_yaxes(showticklabels=False)
    fig.update_annotations(font_size=12)
    fig.show()


def show_categories(t, per_row=3, top=12):
    """Exact top-N value counts of every categorical and boolean column, as bars and a searchable table."""
    cats = kinds(t, "categorical", "boolean")
    if not cats:
        return
    vcs = {c: p.value_counts(con, rel(t), c, top=top) for c in cats}
    rows = -(-len(cats) // per_row)
    titles = [f"{c} ({vcs[c].attrs['cardinality']:,} values)" for c in cats]
    fig = make_subplots(
        rows=rows,
        cols=per_row,
        subplot_titles=titles,
        horizontal_spacing=0.18,
        vertical_spacing=0.25 / max(rows, 1) + 0.03,
    )
    for i, c in enumerate(cats):
        vc = vcs[c].iloc[::-1]
        colors = [
            theme.GRID if str(v).startswith(("(other", "(null")) else theme.BLUE
            for v in vc["value"]
        ]
        r, k = divmod(i, per_row)
        fig.add_bar(
            x=vc["share_pct"],
            y=vc["value"].astype(str).str.slice(0, 28),
            orientation="h",
            marker_color=colors,
            showlegend=False,
            row=r + 1,
            col=k + 1,
            customdata=vc["n"],
            hovertemplate="%{y}: %{customdata:,} rows (%{x:.1f}%)<extra></extra>",
        )
    fig.update_layout(
        title=f"{t}: categories (exact; share of rows, %; gray = tail or null)",
        height=max(330, 60 + 300 * rows),
    )
    fig.update_yaxes(tickfont_size=10, type="category")  # codes such as postal_code stay labels
    fig.update_annotations(font_size=12)
    fig.show()
    long = pd.concat([v.assign(column=c) for c, v in vcs.items()])[
        ["column", "value", "n", "share_pct", "cum_pct"]
    ]
    show(
        long,
        caption=f"{t}: value counts (top {top} + tail), searchable",
        pageLength=10,
        classes="display compact",
    )


def show_associations(t):
    """Spearman correlation of numeric/boolean columns and Cramér's V of low-cardinality categoricals."""
    s = smp(t)
    num = [c for c in kinds(t, "numeric", "boolean") if s[c].nunique() > 1]
    cats = [c for c in kinds(t, "categorical", "boolean") if 2 <= s[c].nunique() <= 60]
    if len(num) >= 2:
        matrix_fig(
            p.spearman_matrix(s, num),
            f"{t}: Spearman rank correlation (sample)",
            theme.DIV_SCALE,
            -1,
            1,
        ).show()
    if len(cats) >= 2:
        m = p.cramers_v_matrix(s.sample(min(len(s), 50_000), random_state=0), cats)
        matrix_fig(m, f"{t}: Cramér's V, bias-corrected (sample)", theme.SEQ_SCALE, 0, 1).show()


def show_time(t):
    """Daily volume by partition date (with 28-day mean) and weekday × hour heatmap of the event timestamp."""
    if t not in TIME:
        return
    part, ts = TIME[t]
    d = p.time_profile(con, rel(t), part, "day")
    d["mean_28d"] = d["value"].rolling(28, min_periods=7).mean()
    fig = go.Figure()
    fig.add_scatter(
        x=d["period"],
        y=d["value"],
        mode="lines",
        name="rows per day",
        line=dict(color=theme.SEQ_BLUE[1], width=1),
    )
    fig.add_scatter(
        x=d["period"],
        y=d["mean_28d"],
        mode="lines",
        name="28-day mean",
        line=dict(color=theme.BLUE, width=2.2),
    )
    fig.update_layout(
        title=f"{t}: rows per {part} (exact)", height=320, yaxis_title="rows", hovermode="x unified"
    )
    fig.show()
    if ts:
        g = p.weekday_hour(con, rel(t), ts)
        fig = px.imshow(
            g,
            color_continuous_scale=theme.SEQ_SCALE,
            aspect="auto",
            labels=dict(x="hour of day", y="", color="rows"),
        )
        fig.update_layout(title=f"{t}: rows by weekday × hour of {ts} (exact)", height=300)
        fig.show()


# ---------- small builders for the bespoke views ----------
def wilson(k, n, z=1.96):
    """95% Wilson interval for a proportion (stable for the rare events of fraud and churn)."""
    k, n = np.asarray(k, float), np.asarray(n, float)
    ph = np.divide(k, n, out=np.zeros_like(k), where=n > 0)
    den = 1 + z**2 / n
    centre = (ph + z**2 / (2 * n)) / den
    half = z * np.sqrt(ph * (1 - ph) / n + z**2 / (4 * n**2)) / den
    return centre - half, centre + half


def rate_by(t, by, flag, top=20, min_n=200):
    """Exact rate of a boolean SQL expression per category, with Wilson 95% intervals."""
    df = con.sql(
        f"""select {p.q(by)}::varchar as level, count(*) n, sum(({flag})::int) k
            from {rel(t)} group by 1 having count(*) >= {min_n} order by n desc limit {top}"""
    ).df()
    df["level"] = df["level"].fillna("(null)")
    df["rate"] = df["k"] / df["n"]
    df["lo"], df["hi"] = wilson(df["k"], df["n"])
    return df.sort_values("rate")


def rate_bars(frames, title, pct=True, per_row=2, height=300):
    """Small multiples of horizontal rate bars with 95% CIs; frames = {subtitle: rate_by(...)}."""
    rows = -(-len(frames) // per_row)
    fig = make_subplots(
        rows=rows, cols=per_row, subplot_titles=list(frames), horizontal_spacing=0.2
    )
    m = 100 if pct else 1
    for i, df in enumerate(frames.values()):
        r, k = divmod(i, per_row)
        fig.add_bar(
            x=df["rate"] * m,
            y=df["level"],
            orientation="h",
            marker_color=theme.BLUE,
            showlegend=False,
            error_x=dict(
                type="data",
                symmetric=False,
                array=(df["hi"] - df["rate"]) * m,
                arrayminus=(df["rate"] - df["lo"]) * m,
                color=theme.INK2,
                thickness=1,
            ),
            customdata=np.c_[df["k"], df["n"]],
            row=r + 1,
            col=k + 1,
            hovertemplate="%{y}: %{x:.3f}"
            + ("%" if pct else "")
            + " (%{customdata[0]:,} of %{customdata[1]:,})<extra></extra>",
        )
    fig.update_layout(title=title, height=height * rows + 60)
    fig.update_annotations(font_size=12)
    fig.show()


def heat(ct, title, fmt=".1f", scale=None, height=None, zmid=None):
    """Annotated plotly heatmap for a crosstab."""
    fig = px.imshow(
        ct,
        text_auto=fmt,
        aspect="auto",
        color_continuous_scale=scale or theme.SEQ_SCALE,
        color_continuous_midpoint=zmid,
    )
    fig.update_layout(title=title, height=height or max(320, 34 * len(ct) + 140))
    fig.update_xaxes(side="bottom", tickangle=-30)
    fig.show()


def core(t):
    """The full standard profile of one table, in order."""
    show_overview(t)
    show_describe(t)
    show_missing(t)
    show_distributions(t)
    show_categories(t)
    show_associations(t)
    show_time(t)


# %% [markdown]
# ## 2 · Inventory and referential integrity
# ### 2.1 All tables at a glance
# One row per table, all exact. *Cells missing* counts nulls plus placeholders over every cell.

# %%
inv = []
for t in TABLES:
    ov = p.overview(con, rel(t))
    OV[t] = ov
    n = ov.attrs["rows"]
    part = TIME.get(t, (None,))[0]
    rng = (
        con.sql(
            f"select min({part})::varchar || ' → ' || max({part})::varchar from {rel(t)}"
        ).fetchone()[0]
        if part
        else "snapshot"
    )
    k = p.pk_check(con, rel(t), PK[t]) if t in PK else None
    inv.append(
        {
            "table": t,
            "role": "fact" if t in FACTS else "dimension",
            "rows": n,
            "columns": len(ov),
            "cells_null_pct": 100 * ov["nulls"].sum() / (n * len(ov)),
            "cells_missing_pct": 100 * ov["missing"].sum() / (n * len(ov)),
            "cols_with_gaps": int((ov["missing"] > 0).sum()),
            "coverage": rng,
            "pk": PK.get(t, "—"),
            "pk_duplicates": k["duplicate_keys"] if k else None,
            "pii_cols": int((ov["kind"] == "pii").sum()),
        }
    )
inv = pd.DataFrame(inv).set_index("table")
display(
    inv.style.format(
        {
            "rows": "{:,}",
            "cells_null_pct": "{:.1f}%",
            "cells_missing_pct": "{:.1f}%",
            "pk_duplicates": "{:,.0f}",
        }
    )
    .background_gradient(cmap=theme.cmap_seq(), subset=["cells_missing_pct"], vmin=0, vmax=60)
    .bar(subset=["rows"], color=theme.SEQ_BLUE[1])
)

# %%
fig = px.bar(
    inv.reset_index().sort_values("rows"),
    x="rows",
    y="table",
    orientation="h",
    log_x=True,
    color="role",
    color_discrete_map={"fact": theme.BLUE, "dimension": theme.AQUA},
    text="rows",
)
fig.update_traces(texttemplate="%{x:,.0f}", textposition="outside", cliponaxis=False)
fig.update_layout(
    title="Row count per table (log scale)", height=430, xaxis_title="rows (log)", yaxis_title=""
)
fig.show()

# %% [markdown]
# ### 2.2 Where the gaps are
# Every column of every table as one dot: its missing rate (nulls + placeholders). Hover for the column name.
# Dots far to the right are fields that are optional by design (e.g. merchant data on non-card
# transactions) **or** extraction gaps; each table section tells which.

# %%
gaps = pd.concat([OV[t].assign(table=t) for t in TABLES])
gaps["disguised"] = gaps["placeholders"] > 0
fig = px.strip(
    gaps,
    x="missing_pct",
    y="table",
    color="disguised",
    hover_name="column",
    hover_data={
        "null_pct": ":.1f",
        "missing_pct": ":.1f",
        "placeholders": ":,",
        "disguised": False,
    },
    color_discrete_map={False: theme.BLUE, True: theme.ORANGE},
)
fig.update_traces(
    marker=dict(size=9, opacity=0.75, line=dict(width=0.5, color="white")), jitter=0.4
)
fig.update_layout(
    title="Missing rate per column (orange: includes placeholder strings)",
    height=520,
    xaxis_title="missing, % of rows",
    yaxis_title="",
    legend_title_text="has placeholders",
    showlegend=bool(gaps["disguised"].any()),
)
fig.show()
disguised = gaps.loc[
    gaps["placeholders"] > 0, ["table", "column", "nulls", "placeholders", "missing_pct"]
]
if disguised.empty:
    h(
        f"**No placeholder strings** ({', '.join(repr(x) for x in p.PLACEHOLDERS)}) in any text column: "
        "every gap in the raw extracts is a real SQL `NULL`."
    )
else:
    display(
        disguised.sort_values("placeholders", ascending=False)
        .reset_index(drop=True)
        .style.format({"nulls": "{:,}", "placeholders": "{:,}", "missing_pct": "{:.1f}%"})
        .set_caption("Columns with disguised missing values (placeholders)")
    )

# %% [markdown]
# ### 2.3 Referential integrity at a glance
# For each foreign key: the share of non-null child rows whose key is **absent** from the parent table.
# Orphans in raw data are normal (late-arriving dimensions, deleted parents); bronze and silver must decide
# whether to quarantine them or add an *unknown member* to the dimension (Kimball).

# %%
FKS = [
    ("products", "customer_id", "customers", "customer_id"),
    ("transactions", "customer_id", "customers", "customer_id"),
    ("transactions", "product_id", "products", "product_id"),
    ("transactions", "branch_id", "branches", "branch_id"),
    ("customers", "registration_branch_id", "branches", "branch_id"),
    ("products", "opening_branch_id", "branches", "branch_id"),
    ("service_agents", "assigned_branch_id", "branches", "branch_id"),
    ("call_center_interactions", "customer_id", "customers", "customer_id"),
    ("call_center_interactions", "agent_id", "service_agents", "agent_id"),
    ("call_transcripts", "interaction_id", "call_center_interactions", "interaction_id"),
    ("satisfaction_surveys", "interaction_id", "call_center_interactions", "interaction_id"),
    ("satisfaction_surveys", "customer_id", "customers", "customer_id"),
    ("complaints", "customer_id", "customers", "customer_id"),
    ("complaints", "affected_product_id", "products", "product_id"),
    ("complaints", "assigned_agent_id", "service_agents", "agent_id"),
    ("campaign_sends", "campaign_id", "marketing_campaigns", "campaign_id"),
    ("campaign_sends", "customer_id", "customers", "customer_id"),
    ("digital_events", "customer_id", "customers", "customer_id"),
]
ri = []
for child, ck, parent, pk_ in FKS:
    r = con.sql(
        f"""select count(c.{ck}) as non_null,
                   count(c.{ck}) filter (where p.{pk_} is null) as orphans,
                   count(distinct c.{ck}) filter (where p.{pk_} is null) as orphan_keys
            from {rel(child)} c left join (select distinct {pk_} from {rel(parent)}) p on c.{ck} = p.{pk_}"""
    ).fetchone()
    ri.append(
        {
            "child": f"{child}.{ck}",
            "parent": f"{parent}.{pk_}",
            "non_null_rows": r[0],
            "orphan_rows": r[1],
            "orphan_keys": r[2],
            "orphan_pct": 100 * r[1] / max(r[0], 1),
        }
    )
ri = pd.DataFrame(ri).sort_values("orphan_pct", ascending=False)
display(
    ri.style.format(
        {
            "non_null_rows": "{:,}",
            "orphan_rows": "{:,}",
            "orphan_keys": "{:,}",
            "orphan_pct": "{:.2f}%",
        }
    )
    .background_gradient(cmap=theme.cmap_seq(), subset=["orphan_pct"], vmin=0, vmax=20)
    .hide(axis="index")
)

# %% [markdown]
# ## 3 · Core banking
# ### 3.1 `customers` (dimension)
# **Grain:** one row per customer. **Key:** `customer_id`. The customer is the conformed dimension that
# every fact table joins to; its quality bounds the quality of every customer-level KPI.
# Watch for: segment and status mix, credit-score and income ranges, PII formats, registration dates.

# %%
t = "customers"
show_overview(t)
show_describe(t)

# %%
show_missing(t)

# %%
show_distributions(t)
show_categories(t)

# %%
show_associations(t)

# %% [markdown]
# **PII formats (shape only, no values).** A clean document or phone column has one or two dominant shapes;
# many shapes mean mixed formats that silver must standardise before matching or masking.

# %%
for c in ["document_number", "email", "mobile_phone", "landline_phone", "postal_code"]:
    pat = p.pattern_profile(con, rel(t), c, top=5)
    pat["share_pct"] = 100 * pat["n"] / OV[t].attrs["rows"]
    h(f"`{c}`")
    display(
        pat.style.format({"n": "{:,}", "avg_len": "{:.1f}", "share_pct": "{:.1f}%"}).hide(
            axis="index"
        )
    )

# %%
age = con.sql(
    """select gender, (floor(date_diff('year', date_of_birth, current_date) / 5) * 5)::int as band, count(*) n
       from m_customers where date_of_birth is not null group by 1, 2 order by 2"""
).df()
age["signed"] = np.where(age["gender"] == age["gender"].mode()[0], -age["n"], age["n"])
fig = px.bar(
    age,
    x="signed",
    y="band",
    color="gender",
    orientation="h",
    barmode="relative",
    color_discrete_sequence=[theme.BLUE, theme.ORANGE, theme.AQUA, theme.VIOLET],
    custom_data=["n"],
)
fig.update_traces(hovertemplate="%{y}–%{y}+4 years: %{customdata[0]:,}<extra></extra>")
fig.update_layout(
    title="Age pyramid (5-year bands, from date_of_birth; exact)",
    height=480,
    xaxis_title="customers",
    yaxis_title="age band",
    bargap=0.08,
)
fig.update_xaxes(
    tickvals=[-20000, -10000, 0, 10000, 20000], ticktext=["20k", "10k", "0", "10k", "20k"]
)
fig.show()

# %%
s = smp(t)
order = s.groupby("segment")["credit_score"].median().sort_values().index.tolist()
dist_fig(
    s,
    "credit_score",
    "segment",
    kind="violin",
    order=order,
    title="Credit score by segment (sample; inner box = quartiles)",
).show()
dist_fig(
    s,
    "estimated_monthly_income",
    "segment",
    log=True,
    order=order,
    color="country",
    title="Monthly income by segment and country (local currency, log; click a country to isolate it)",
).show()
heat(
    p.crosstab(con, rel(t), "segment", "country", normalize="column"),
    "Segment mix within each country (% of the country's customers, exact)",
)
heat(
    p.crosstab(con, rel(t), "customer_status", "segment", normalize="column"),
    "Customer status within each segment (% of the segment, exact)",
)
reg = p.time_profile(con, rel(t), "registration_date", "month")
fig = px.area(reg, x="period", y="value", color_discrete_sequence=[theme.BLUE])
fig.update_layout(
    title="New customers per month (registration_date, exact)", height=300, yaxis_title="customers"
)
fig.show()

# %% [markdown]
# ### 3.2 `products` (dimension / account snapshot)
# **Grain:** one row per product held by a customer (account, card, loan, investment, insurance).
# **Key:** `product_id`. It carries the balances, limits, interest rates and **days past due (DPD)**
# that drive credit-risk and collections views.

# %%
t = "products"
show_overview(t)
show_describe(t)

# %%
show_missing(t)

# %%
show_distributions(t)
show_categories(t)

# %%
show_associations(t)

# %% [markdown]
# **Portfolio views.** Balances and limits by product type, card utilisation, and the DPD ladder used in
# collections (0 · 1–30 · 31–60 · 61–90 · 90+ days). DPD exists only for credit products (credit cards and loans);
# for accounts, investments and insurance it is null by design and shows as "no data".

# %%
s = smp(t)
order = s.groupby("product_type")["current_balance"].median().sort_values().index.tolist()
dist_fig(
    s,
    "current_balance",
    "product_type",
    log=True,
    order=order,
    color="currency",
    title="Current balance by product type and currency (positive balances, log, sample)",
).show()
dist_fig(
    s, "interest_rate", "product_type", order=order, title="Interest rate by product type (sample)"
).show()

dpd = con.sql(
    """select product_type,
              case when days_past_due is null then 'no data' when days_past_due = 0 then '0 current'
                   when days_past_due <= 30 then '1–30' when days_past_due <= 60 then '31–60'
                   when days_past_due <= 90 then '61–90' else '90+' end as bucket,
              count(*) n
       from m_products group by 1, 2"""
).df()
dpd["pct"] = 100 * dpd["n"] / dpd.groupby("product_type")["n"].transform("sum")
fig = px.bar(
    dpd,
    y="product_type",
    x="pct",
    color="bucket",
    orientation="h",
    category_orders={"bucket": ["0 current", "1–30", "31–60", "61–90", "90+", "no data"]},
    color_discrete_map={
        "0 current": theme.STATUS["good"],
        "1–30": theme.STATUS["warning"],
        "31–60": theme.STATUS["serious"],
        "61–90": theme.STATUS["critical"],
        "90+": "#8a1f1f",
        "no data": theme.GRID,
    },
    custom_data=["n"],
)
fig.update_traces(
    hovertemplate="%{y} · %{fullData.name}: %{x:.1f}% (%{customdata[0]:,})<extra></extra>"
)
fig.update_layout(
    title="Days-past-due ladder by product type (% of products, exact)",
    height=380,
    xaxis_title="% of products",
    yaxis_title="",
    legend_title_text="DPD",
)
fig.show()

util = con.sql(
    """select current_balance / credit_limit as utilisation from m_products
       where credit_limit > 0 and current_balance is not null"""
).df()
h(
    f"Utilisation (balance ÷ limit) is defined for {len(util):,} products with a credit limit; "
    f"{(util['utilisation'] > 1).mean():.1%} are over their limit."
)
# bin before plotting so the figure carries 60 bars, not every product
counts, edges = np.histogram(util["utilisation"].clip(upper=1.5), bins=60)
fig = px.bar(x=(edges[:-1] + edges[1:]) / 2, y=counts, color_discrete_sequence=[theme.BLUE])
fig.update_layout(bargap=0.02, xaxis_title="utilisation")
fig.add_vline(x=1, line_dash="dash", line_color=theme.RED, annotation_text="limit")
fig.update_layout(
    title="Credit utilisation (capped at 150%, exact)", height=300, yaxis_title="products"
)
fig.show()
heat(
    p.crosstab(con, rel(t), "product_status", "product_type", normalize="column"),
    "Product status within each product type (% of the type, exact)",
)
heat(
    p.crosstab(con, rel(t), "currency", "product_type", normalize="column"),
    "Currency of each product type (% of the type, exact)",
)

# %% [markdown]
# ### 3.3 `transactions` (fact)
# **Grain:** one row per monetary movement on a product. **Key:** `transaction_id`. **Partition:** `process_date`.
# The largest financial fact: it feeds fraud, AML, spend analytics and balances. Two things deserve care:
# `amount` is in the transaction `currency` (USD, COP, ARS mixed) while `amount_usd` is the converted value,
# and `is_fraud` is a **rare** label, so rates come with confidence intervals.

# %%
t = "transactions"
show_overview(t)
show_describe(t)

# %%
show_missing(t)

# %%
show_distributions(t)
show_categories(t)

# %%
show_associations(t)
show_time(t)

# %% [markdown]
# **Currencies.** `amount` mixes three currencies, so its raw distribution is multi-modal and must never be
# summed across currencies. The table shows where `amount_usd` is filled.

# %%
cur = con.sql(
    """select currency, count(*) n, avg((amount_usd is null)::int) usd_null_share,
              median(amount) median_amount, median(amount_usd) median_amount_usd,
              median(amount / nullif(amount_usd, 0)) implied_rate
       from m_transactions group by 1 order by n desc"""
).df()
display(
    cur.style.format(
        {
            "n": "{:,}",
            "usd_null_share": "{:.1%}",
            "median_amount": "{:,.2f}",
            "median_amount_usd": "{:,.2f}",
            "implied_rate": "{:,.2f}",
        }
    ).hide(axis="index")
)
s = smp(t)
kde_fig(
    {c: g["amount"] for c, g in s.groupby("currency")},
    "amount by currency (log scale, sample): one distribution per currency",
    log=True,
    xaxis_title="amount, in the transaction currency",
).show()
heat(
    p.crosstab(con, rel(t), "transaction_country", "currency", normalize="row"),
    "Currency used per transaction country (% of the country's rows, exact)",
)

# %% [markdown]
# **Fraud.** Overall rate, then the rate by type, channel, country and merchant category with 95% Wilson
# intervals. Wide intervals mean too few cases to conclude anything.

# %%
k, n = con.sql("select sum(is_fraud::int), count(*) from m_transactions").fetchone()
lo, hi = wilson(k, n)
h(
    f"**{k:,} fraudulent of {n:,} transactions = {k / n:.3%}** (95% CI {lo:.3%}–{hi:.3%}); "
    f"about 1 in {n // max(k, 1):,}. Any classifier must be judged on precision/recall, not accuracy."
)
rate_bars(
    {
        f"by {c}": rate_by(t, c, "is_fraud", min_n=500)
        for c in ["transaction_type", "channel", "transaction_country", "merchant_category"]
    },
    "Fraud rate (%, exact, 95% Wilson CI)",
)
fr = con.sql(
    """(select fraud_score, is_fraud from m_transactions where is_fraud and fraud_score is not null)
       union all
       (select fraud_score, is_fraud from m_transactions where not is_fraud and fraud_score is not null
        order by hash(transaction_id, 42) limit 50000)"""
).df()
# a 1-point-bin histogram, not a KDE: smoothing would blur the hard edge at 30
fig = go.Figure()
for i, (label, flag) in enumerate([("legitimate (50k sample)", False), ("fraud (all)", True)]):
    fig.add_histogram(
        x=fr.loc[fr["is_fraud"] == flag, "fraud_score"],
        xbins=dict(start=0, end=100, size=1),
        histnorm="probability density",
        name=label,
        marker_color=theme.CATEGORICAL[i],
        opacity=0.6,
    )
fig.update_layout(
    barmode="overlay",
    title="fraud_score by label (each histogram normalised to its own total)",
    height=360,
    xaxis_title="fraud_score",
    yaxis_title="density",
)
fig.show()
leak = con.sql(
    """select max(fraud_score) filter (where not is_fraud) as legit_max,
              count(*) filter (where fraud_score > 30 and is_fraud) as tp,
              count(*) filter (where fraud_score > 30) as flagged,
              count(*) filter (where is_fraud) as frauds
       from m_transactions"""
).fetchone()
h(
    f"**Label leakage check:** the highest score of a legitimate transaction is **{leak[0]:.2f}**; "
    f"`fraud_score > 30` flags {leak[2]:,} rows, {leak[1] / leak[2]:.0%} of them fraud (precision), "
    f"and catches {leak[1] / leak[3]:.0%} of all fraud (recall)."
)
heat(
    p.crosstab(con, rel(t), "channel", "transaction_status", normalize="row"),
    "Transaction status by channel (% of the channel's rows, exact)",
)

# %% [markdown]
# **Geography.** Coordinates are filled for a minority of rows; plotting them shows whether they are
# plausible for the stated country.

# %%
geo = con.sql(
    """select latitude, longitude, transaction_country from m_transactions
       where latitude is not null order by hash(transaction_id, 7) limit 20000"""
).df()
fig = px.scatter(
    geo,
    x="longitude",
    y="latitude",
    color="transaction_country",
    opacity=0.5,
    color_discrete_sequence=theme.CATEGORICAL,
    render_mode="svg",
)
fig.update_traces(marker_size=4)
fig.update_layout(title="Transaction coordinates (20k rows with coordinates)", height=480)
fig.show()
nk, nn = con.sql(
    """select count(*) filter (where abs(latitude) <= 1.5 and abs(longitude) <= 1.5), count(latitude)
       from m_transactions"""
).fetchone()
h(
    f"**{nk:,} of {nn:,} rows with coordinates ({nk / nn:.1%}) sit within 1.5° of (0, 0)**, the "
    "'null island' in the Gulf of Guinea, nowhere near the stated countries: placeholder coordinates "
    "with jitter, to be treated as missing downstream."
)

# %% [markdown]
# ### 3.4 `daily_exchange_rates` (reference)
# **Grain:** one row per date × currency pair. No surrogate key: `(date, source_currency, target_currency)`
# should be unique. These rates are what silver should use to rebuild `amount_usd`.

# %%
t = "daily_exchange_rates"
show_overview(t)
show_describe(t)
dup = con.sql("""select count(*) - count(distinct (date, source_currency, target_currency))
                 from m_daily_exchange_rates""").fetchone()[0]
h(f"Duplicated `(date, source_currency, target_currency)` rows: **{dup:,}**")

# %%
show_missing(t)
show_distributions(t)
show_categories(t)
show_time(t)

# %%
fx = con.sql("""select date, source_currency || '→' || target_currency pair, exchange_rate, buy_rate, sell_rate
                from m_daily_exchange_rates order by date""").df()
fx["index_100"] = 100 * fx["exchange_rate"] / fx.groupby("pair")["exchange_rate"].transform("first")
fx[["source", "target"]] = fx["pair"].str.split("→", expand=True)
# weekly means keep the shape and send 7x fewer points to the browser
weekly = (
    fx.assign(week=pd.to_datetime(fx["date"]).dt.to_period("W").dt.start_time)
    .groupby(["source", "target", "week"], as_index=False)["index_100"]
    .mean()
)
fig = px.line(
    weekly,
    x="week",
    y="index_100",
    color="target",
    facet_col="source",
    color_discrete_sequence=theme.CATEGORICAL,
    labels={"week": "", "index_100": "index", "target": "to", "source": "from"},
    render_mode="svg",  # WebGL does not render everywhere (headless browsers, some exports)
)
fig.update_layout(
    title="Exchange rate per pair, indexed to 100 at the first date (weekly mean, exact)",
    height=360,
    hovermode="x unified",
)
fig.show()
fx["spread_bp"] = 1e4 * (fx["sell_rate"] - fx["buy_rate"]) / fx["exchange_rate"]
q = fx.groupby("pair")["spread_bp"].quantile([0.05, 0.25, 0.5, 0.75, 0.95]).unstack()
fig = go.Figure(
    go.Box(
        y=q.index,
        q1=q[0.25],
        median=q[0.5],
        q3=q[0.75],
        lowerfence=q[0.05],
        upperfence=q[0.95],
        orientation="h",
        marker_color=theme.BLUE,
        fillcolor=theme.SEQ_BLUE[0],
    )
)
fig.update_layout(
    title="Buy/sell spread per pair (bp of the mid rate; box = quartiles, whiskers = 5th–95th pct)",
    height=420,
    yaxis_title="",
)
fig.show()

# %% [markdown]
# ## 4 · Network and people
# ### 4.1 `branches` (dimension)
# **Grain:** one row per branch. **Key:** `branch_id`. Small and descriptive: location, format, ATMs, hours.

# %%
t = "branches"
core(t)

# %%
b = con.sql("select * from m_branches").df()
fig = px.scatter(
    b,
    x="longitude",
    y="latitude",
    color="branch_type",
    size="atm_count",
    size_max=14,
    hover_name="branch_name",
    hover_data=["city", "country", "branch_status"],
    color_discrete_sequence=theme.CATEGORICAL,
)
fig.update_layout(title="Branch locations (size = ATMs)", height=480)
fig.show()
heat(
    p.crosstab(con, rel(t), "branch_type", "country"),
    "Branches by type and country (count)",
    fmt="d",
)

# %% [markdown]
# ### 4.2 `service_agents` (dimension)
# **Grain:** one row per agent. **Key:** `agent_id`. Experience, specialty, languages and accent drive the
# routing questions of the AI customer-service system.

# %%
t = "service_agents"
core(t)

# %%
s = smp(t)
order = [
    o for o in ["Junior", "Mid-Senior", "Senior", "Specialist"] if o in set(s["experience_level"])
]
dist_fig(
    s, "avg_csat", "experience_level", order=order or None, title="Average CSAT by experience level"
).show()
fig = px.scatter(
    s,
    x="total_monthly_interactions",
    y="avg_csat",
    color="agent_type",
    hover_data=["agent_id", "experience_level", "specialty", "native_accent"],
    opacity=0.65,
    color_discrete_sequence=theme.CATEGORICAL,
    render_mode="svg",
)
fig.update_traces(marker_size=6)
fig.update_layout(title="Workload vs CSAT, one dot per agent (hover for details)", height=440)
fig.show()
heat(
    p.crosstab(con, rel(t), "specialty", "agent_type"),
    "Agents by specialty and type (count)",
    fmt="d",
)

# %% [markdown]
# ## 5 · Customer service
# ### 5.1 `call_center_interactions` (fact)
# **Grain:** one row per contact (phone, chat, e-mail...). **Key:** `interaction_id`. Wait time, handle time,
# resolution, escalation and sentiment: the operational KPIs the AI agents are meant to improve.

# %%
t = "call_center_interactions"
show_overview(t)
show_describe(t)

# %%
show_missing(t)

# %%
show_distributions(t)
show_categories(t)

# %%
show_associations(t)
show_time(t)

# %%
rate_bars(
    {
        "resolved, by reason_category": rate_by(t, "reason_category", "was_resolved"),
        "escalated, by reason_category": rate_by(t, "reason_category", "was_escalated"),
        "resolved, by channel": rate_by(t, "channel", "was_resolved"),
        "follow-up needed, by channel": rate_by(t, "channel", "requires_followup"),
    },
    "Service outcomes (%, exact, 95% Wilson CI)",
)
s = smp(t)
# each chart orders its own channels: wait time exists only for phone calls
dist_fig(
    s,
    "wait_time_seconds",
    "channel",
    kind="violin",
    title="Wait time by channel (s, sample)",
).show()
dist_fig(
    s,
    "duration_seconds",
    "channel",
    kind="violin",
    title="Handle time by channel (s, sample)",
).show()
heat(
    p.crosstab(con, rel(t), "reason_category", "detected_sentiment", normalize="row"),
    "Detected sentiment by reason category (% of the reason's contacts, exact)",
)
heat(
    p.crosstab(con, rel(t), "customer_detected_accent", "agent_used_accent", normalize="row"),
    "Accent match: customer accent (rows) vs accent the agent used (% of row, exact)",
)

# %% [markdown]
# ### 5.2 `call_transcripts` (fact, text)
# **Grain:** one row per transcribed call. **Key:** `transcript_id`, linked to `interaction_id`.
# Free text is profiled by length and language only; its content belongs to the knowledge-base and NLP work.

# %%
t = "call_transcripts"
show_overview(t)
show_describe(t)

# %%
show_missing(t)
show_distributions(t)
show_categories(t)

# %%
show_associations(t)
show_time(t)

# %%
tl = pd.concat(
    {c: p.text_lengths(con, rel(t), c) for c in ["full_text", "customer_text", "agent_text"]},
    names=["field"],
).reset_index(level=0)
# bin before plotting so the figure carries 80 bars per field, not every transcript
edges = np.linspace(0, tl["words"].max(), 81)
binned = pd.concat(
    pd.DataFrame(
        {"field": f, "words": (edges[:-1] + edges[1:]) / 2, "n": np.histogram(g["words"], edges)[0]}
    )
    for f, g in tl.groupby("field")
)
fig = px.bar(
    binned,
    x="words",
    y="n",
    color="field",
    barmode="overlay",
    opacity=0.6,
    color_discrete_sequence=theme.CATEGORICAL,
)
fig.update_layout(bargap=0)
fig.update_layout(
    title="Transcript length in words (exact, every transcript)",
    height=340,
    yaxis_title="transcripts",
)
fig.show()
dist_fig(
    smp(t),
    "accent_confidence",
    "audio_quality",
    title="Accent-detection confidence by audio quality (sample)",
).show()

# %% [markdown]
# ### 5.3 `satisfaction_surveys` (fact)
# **Grain:** one survey response. **Key:** `survey_id`. Three instruments share one table (CSAT, NPS, CES),
# so `main_score` means something different per `survey_type` and must be read per type.

# %%
t = "satisfaction_surveys"
show_overview(t)
show_describe(t)

# %%
show_missing(t)
show_distributions(t)
show_categories(t)

# %%
show_associations(t)
show_time(t)

# %%
sc = con.sql(
    "select survey_type, main_score, count(*) n from m_satisfaction_surveys group by 1, 2"
).df()
fig = px.bar(
    sc, x="main_score", y="n", facet_col="survey_type", color_discrete_sequence=[theme.BLUE]
)
fig.update_yaxes(matches=None, showticklabels=True)
fig.update_layout(title="main_score distribution per survey type (exact)", height=330)
fig.show()
ct = p.crosstab(con, rel(t), "main_score", "nps_category", top=20)
heat(
    ct.sort_index(key=lambda i: i.astype(int)),
    "main_score vs nps_category label (count, exact)",
    fmt="d",
)
nps = con.sql(
    """select 100 * avg((main_score >= 9)::int) - 100 * avg((main_score <= 6)::int)
       from m_satisfaction_surveys where survey_type = 'NPS'"""
).fetchone()[0]
h(
    f"**NPS recomputed from `main_score` (0–10 scale) = {nps:,.1f}** "
    "(promoters 9–10 minus detractors 0–6). Compare with the `nps_category` labels above."
)

# %% [markdown]
# ### 5.4 `complaints` (fact)
# **Grain:** one complaint case. **Key:** `complaint_id`. Lifecycle dates (creation → assignment →
# first response → resolution → closing), SLA and compensation: a regulatory-sensitive table.

# %%
t = "complaints"
show_overview(t)
show_describe(t)

# %%
show_missing(t)

# %%
show_distributions(t)
show_categories(t)

# %%
show_associations(t)
show_time(t)

# %%
sla = con.sql(
    "select category, priority, 100 * avg(sla_breached::int) r from m_complaints group by 1, 2"
).df()
sla = sla.pivot(index="category", columns="priority", values="r")
heat(
    sla[[c for c in ["Low", "Medium", "High", "Critical"] if c in sla.columns]],
    "SLA breach rate by category × priority (%, exact)",
)
s = smp(t)
pri = [x for x in ["Low", "Medium", "High", "Critical"] if x in set(s["priority"])]
dist_fig(
    s, "resolution_days", "priority", order=pri, title="Resolution days by priority (sample)"
).show()
comp = s[(s["claimed_amount"] > 0) & (s["compensation_granted"] > 0)]
fig = px.scatter(
    comp,
    x="claimed_amount",
    y="compensation_granted",
    color="currency",
    log_x=True,
    log_y=True,
    opacity=0.45,
    hover_data=["complaint_id", "category", "priority", "status"],
    color_discrete_sequence=theme.CATEGORICAL,
    render_mode="svg",
)
fig.update_traces(marker_size=4)
fig.update_layout(
    title=f"Claimed vs compensation granted (both > 0, log-log, {len(comp):,} complaints)",
    height=460,
)
fig.show()
lc = (
    con.sql(
        """select avg(date_diff('hour', creation_date, assignment_date)) / 24 assign_days,
              avg(date_diff('hour', creation_date, first_response_date)) / 24 first_response_days,
              avg(date_diff('hour', creation_date, resolution_date)) / 24 resolution_days_from_dates,
              avg(resolution_days) resolution_days_column,
              avg((resolution_date < creation_date)::int) resolved_before_created_share,
              avg((closing_date < resolution_date)::int) closed_before_resolved_share
       from m_complaints"""
    )
    .df()
    .T.rename(columns={0: "value"})
)
h(
    "**Lifecycle consistency (exact).** Mean durations from the date columns, and the share of impossible orders:"
)
display(lc.style.format("{:,.3f}"))

# %% [markdown]
# ## 6 · Marketing
# ### 6.1 `marketing_campaigns` (dimension)
# **Grain:** one campaign. **Key:** `campaign_id`. Budget, objective, target segment and expected conversion.

# %%
t = "marketing_campaigns"
core(t)

# %%
mc = con.sql("select * from m_marketing_campaigns order by start_date").df()
fig = px.timeline(
    mc,
    x_start="start_date",
    x_end="end_date",
    y="campaign_type",
    color="campaign_objective",
    hover_name="campaign_name",
    hover_data=["budget", "target_segment", "campaign_status"],
    color_discrete_sequence=theme.CATEGORICAL,
)
fig.update_traces(opacity=0.55)
fig.update_layout(
    title="Campaign calendar by type (colour = objective)", height=420, yaxis_title=""
)
fig.show()

# %% [markdown]
# ### 6.2 `campaign_sends` (fact)
# **Grain:** one message sent to one customer. **Key:** `send_id`. The marketing funnel: sent → delivered →
# opened → clicked → converted, with cost and conversion value.

# %%
t = "campaign_sends"
show_overview(t)
show_describe(t)

# %%
show_missing(t)

# %%
show_distributions(t)
show_categories(t)

# %%
show_associations(t)
show_time(t)

# %%
fun = con.sql(
    """select send_channel, count(*) sent, sum(was_delivered::int) delivered, sum(was_opened::int) opened,
              sum(was_clicked::int) clicked, sum(had_conversion::int) converted,
              sum(send_cost) as cost, sum(conversion_value) as value
       from m_campaign_sends group by 1 order by sent desc"""
).df()
stages = ["sent", "delivered", "opened", "clicked", "converted"]
fig = go.Figure()
for i, r in fun.iterrows():
    fig.add_scatter(
        x=stages,
        y=[100 * r[s_] / r["sent"] for s_ in stages],
        mode="lines+markers",
        name=r["send_channel"],
        line=dict(color=theme.CATEGORICAL[i % 8], width=2),
    )
fig.update_layout(
    title="Funnel by channel (% of sent, exact)",
    height=380,
    yaxis_title="% of sent",
    yaxis_type="log",
    hovermode="x unified",
)
fig.show()
fun["cost_per_conversion"] = fun["cost"] / fun["converted"].replace(0, np.nan)
fun["value_per_cost"] = fun["value"] / fun["cost"]
display(
    fun.style.format(
        dict.fromkeys(stages + ["cost", "value"], "{:,.0f}")
        | {"cost_per_conversion": "{:,.2f}", "value_per_cost": "{:,.2f}"},
        na_rep="not tracked",
    ).hide(axis="index")
)

# %%
camp = con.sql(
    """select c.campaign_id, c.campaign_type, c.expected_conversion_rate, c.budget,
              count(*) sends, avg(s.had_conversion::int) actual_conversion_rate
       from m_campaign_sends s join m_marketing_campaigns c using (campaign_id)
       group by 1, 2, 3, 4"""
).df()
fig = px.scatter(
    camp,
    x="expected_conversion_rate",
    y="actual_conversion_rate",
    size="sends",
    color="campaign_type",
    hover_name="campaign_id",
    color_discrete_sequence=theme.CATEGORICAL,
    size_max=18,
)
lim = [0, float(max(camp["expected_conversion_rate"].max(), camp["actual_conversion_rate"].max()))]
fig.add_scatter(
    x=lim, y=lim, mode="lines", line=dict(dash="dash", color=theme.INK2), name="actual = expected"
)
fig.update_layout(title="Expected vs actual conversion per campaign (size = sends)", height=440)
fig.show()

# %% [markdown]
# ## 7 · Digital
# ### 7.1 `digital_events` (fact, clickstream)
# **Grain:** one event in a web or app session. **Key:** `event_id`. 15.6 M rows: every statistic here is a
# DuckDB aggregate; only `info()`, missingno, KDEs and the association matrices use the 200k sample.

# %%
t = "digital_events"
show_overview(t)
show_describe(t)

# %%
show_missing(t)

# %%
show_distributions(t)
show_categories(t)

# %%
show_associations(t)
show_time(t)

# %%
heat(
    p.crosstab(con, rel(t), "event_type", "channel", normalize="column"),
    "Event type mix per channel (% of the channel's events, exact)",
)
depth = con.sql(
    """select least(n, 60) events_per_session, count(*) sessions
       from (select session_id, count(*) n from m_digital_events group by 1) group by 1 order by 1"""
).df()
fig = px.bar(depth, x="events_per_session", y="sessions", color_discrete_sequence=[theme.BLUE])
fig.update_layout(title="Session depth (events per session, 60 = 60 or more; exact)", height=320)
fig.show()
rate_bars(
    {
        "error events, by channel": rate_by(t, "channel", "event_type = 'Error'"),
        "error events, by app_version": rate_by(t, "app_version", "event_type = 'Error'", top=15),
    },
    "Error-event rate (%, exact, 95% Wilson CI)",
)

# %% [markdown]
# ## 8 · Interactive explorers
# Six tools to keep exploring on your own. They query **the full tables live** through DuckDB (the KDE, box
# and violin views use the cached sample). **Run the notebook in JupyterLab** to use them; the HTML export
# cannot run widgets.

# %%
import ipywidgets as widgets

out_col = widgets.Output()
w_t = widgets.Dropdown(options=TABLES, value="transactions", description="table")
w_c = widgets.Dropdown(description="column")
w_k = widgets.ToggleButtons(
    options=["histogram", "KDE", "box", "bar"], value="histogram", description="chart"
)
w_log = widgets.Checkbox(value=False, description="log scale")
w_bins = widgets.IntSlider(value=40, min=10, max=150, step=5, description="bins")


def _cols(*_):
    cols = p.columns(con, rel(w_t.value))
    w_c.options = cols.loc[
        cols["kind"].isin(["numeric", "categorical", "boolean", "temporal"]), "column"
    ].tolist()


def _draw_col(*_):
    t, c = w_t.value, w_c.value
    if not has_cols(t, c):
        return
    if c is None:
        return
    out_col.clear_output(wait=True)
    k = p.columns(con, rel(t)).set_index("column").loc[c, "kind"]
    with out_col:
        if w_k.value == "bar" or k in ("categorical", "boolean"):
            vc = p.value_counts(con, rel(t), c, top=25).iloc[::-1]
            fig = px.bar(
                vc,
                x="n",
                y="value",
                orientation="h",
                color_discrete_sequence=[theme.BLUE],
                log_x=w_log.value,
                hover_data={"share_pct": ":.2f"},
            )
            fig.update_yaxes(type="category")
            fig.update_layout(
                title=f"{t}.{c}: value counts (exact, {vc.attrs['cardinality']:,} distinct)",
                height=max(320, 22 * len(vc) + 120),
            )
            fig.show()
        elif k == "temporal":
            d = p.time_profile(con, rel(t), c, "day")
            px.line(
                d, x="period", y="value", title=f"{t}.{c}: rows per day (exact)", render_mode="svg"
            ).show()
        elif w_k.value == "histogram":
            hist = p.binned_hist(con, rel(t), c, bins=w_bins.value, log=w_log.value)
            fig = go.Figure(
                go.Bar(x=(hist["left"] + hist["right"]) / 2, y=hist["n"], marker_color=theme.BLUE)
            )
            fig.update_layout(
                title=f"{t}.{c}: histogram (exact" + (", log10 bins" if w_log.value else "") + ")",
                xaxis_type="log" if w_log.value else None,
                bargap=0.02,
                height=380,
            )
            fig.show()
        else:
            x = smp(t)[c].dropna().astype(float)
            x = x[x > 0] if w_log.value else x
            if w_k.value == "KDE":
                kde_fig({c: x}, f"{t}.{c}: KDE (sample of {len(x):,})", log=w_log.value).show()
            else:
                fig = px.box(
                    x=x,
                    points="suspectedoutliers",
                    log_x=w_log.value,
                    color_discrete_sequence=[theme.BLUE],
                )
                fig.update_layout(
                    title=f"{t}.{c}: box (sample of {len(x):,}; dots = outliers)", height=300
                )
                fig.show()


w_t.observe(_cols, "value")
for w in (w_t, w_c, w_k, w_log, w_bins):
    w.observe(_draw_col, "value")
_cols()
h("### 8.1 Column explorer")
display(widgets.VBox([widgets.HBox([w_t, w_c]), w_k, widgets.HBox([w_log, w_bins]), out_col]))

# %%
out_x = widgets.Output()
x_t = widgets.Dropdown(options=TABLES, value="transactions", description="table")
x_r, x_c = widgets.Dropdown(description="rows"), widgets.Dropdown(description="columns")
x_norm = widgets.ToggleButtons(
    options=["count", "row %", "column %", "total %"], value="row %", description="show"
)
x_top = widgets.IntSlider(value=12, min=3, max=40, description="top N")


def _xcols(*_):
    opts = p.cols_of(con, rel(x_t.value), "categorical", "boolean")
    x_r.options, x_c.options = opts, opts
    if len(opts) > 1:
        x_c.value = opts[1]


def _draw_x(*_):
    if not has_cols(x_t.value, x_r.value, x_c.value):
        return
    if not (x_r.value and x_c.value) or x_r.value == x_c.value:
        return
    out_x.clear_output(wait=True)
    norm = {"count": None, "row %": "row", "column %": "column", "total %": "all"}[x_norm.value]
    ct = p.crosstab(con, rel(x_t.value), x_r.value, x_c.value, top=x_top.value, normalize=norm)
    with out_x:
        heat(
            ct,
            f"{x_t.value}: {x_r.value} × {x_c.value} ({x_norm.value}, exact)",
            fmt="d" if norm is None else ".1f",
        )


x_t.observe(_xcols, "value")
for w in (x_t, x_r, x_c, x_norm, x_top):
    w.observe(_draw_x, "value")
_xcols()
h("### 8.2 Cross-matrix explorer")
display(widgets.VBox([widgets.HBox([x_t, x_r, x_c]), x_norm, x_top, out_x]))

# %%
out_g = widgets.Output()
g_t = widgets.Dropdown(options=TABLES, value="transactions", description="table")
g_y, g_by = widgets.Dropdown(description="number"), widgets.Dropdown(description="split by")
g_k = widgets.ToggleButtons(options=["box", "violin", "KDE"], value="box", description="chart")
g_log = widgets.Checkbox(value=True, description="log scale")


def _gcols(*_):
    g_y.options = p.cols_of(con, rel(g_t.value), "numeric")
    s = smp(g_t.value)
    g_by.options = [
        c for c in p.cols_of(con, rel(g_t.value), "categorical", "boolean") if s[c].nunique() <= 30
    ]


def _draw_g(*_):
    if not has_cols(g_t.value, g_y.value, g_by.value):
        return
    if not (g_y.value and g_by.value):
        return
    out_g.clear_output(wait=True)
    s = smp(g_t.value)[[g_y.value, g_by.value]].dropna()
    if g_log.value:
        s = s[s[g_y.value] > 0]
    order = s.groupby(g_by.value)[g_y.value].median().sort_values().index
    with out_g:
        title = f"{g_t.value}: {g_y.value} by {g_by.value} (sample of {len(s):,})"
        if g_k.value == "KDE":
            top = s[g_by.value].value_counts().index[:8]  # one palette slot per level, max 8
            kde_fig(
                {lvl: s.loc[s[g_by.value] == lvl, g_y.value] for lvl in top},
                title + " · 8 most frequent levels",
                log=g_log.value,
                height=420,
            ).show()
        else:
            dist_fig(
                s,
                g_y.value,
                g_by.value,
                kind=g_k.value,
                log=g_log.value,
                order=order.tolist(),
                title=title,
            ).show()


g_t.observe(_gcols, "value")
for w in (g_t, g_y, g_by, g_k, g_log):
    w.observe(_draw_g, "value")
_gcols()
h("### 8.3 Numeric-by-category explorer")
display(widgets.VBox([widgets.HBox([g_t, g_y, g_by]), widgets.HBox([g_k, g_log]), out_g]))

# %%
out_ts = widgets.Output()
ts_t = widgets.Dropdown(options=list(TIME), value="transactions", description="table")
ts_d = widgets.Dropdown(description="date")
ts_grain = widgets.ToggleButtons(
    options=["day", "week", "month", "quarter"], value="week", description="grain"
)
ts_agg = widgets.ToggleButtons(
    options=["count", "sum", "avg"], value="count", description="measure"
)
ts_v = widgets.Dropdown(description="of column")
ts_split = widgets.Dropdown(description="split by")


def _tscols(*_):
    ts_d.options = p.cols_of(con, rel(ts_t.value), "temporal")
    ts_d.value = TIME[ts_t.value][0]
    ts_v.options = p.cols_of(con, rel(ts_t.value), "numeric", "boolean")
    s = smp(ts_t.value)
    # at most 8 series: one fixed palette slot each, never cycled
    ts_split.options = ["(none)"] + [
        c for c in p.cols_of(con, rel(ts_t.value), "categorical") if s[c].nunique() <= 8
    ]


def _draw_ts(*_):
    if not has_cols(ts_t.value, ts_d.value, ts_v.value, ts_split.value):
        return
    if not ts_d.value:
        return
    out_ts.clear_output(wait=True)
    measure = (
        "count(*)"
        if ts_agg.value == "count" or not ts_v.value
        else f"{ts_agg.value}({p.q(ts_v.value)}::double)"
    )
    split = ts_split.value if ts_split.value and ts_split.value != "(none)" else None
    d = con.sql(
        f"""select date_trunc('{ts_grain.value}', {p.q(ts_d.value)})::date as period,
                   {p.q(split) + "::varchar" if split else "'all'"} as series, {measure} as value
            from {rel(ts_t.value)} where {p.q(ts_d.value)} is not null group by 1, 2 order by 1"""
    ).df()
    label = "rows" if ts_agg.value == "count" else f"{ts_agg.value} of {ts_v.value}"
    with out_ts:
        fig = px.line(
            d,
            x="period",
            y="value",
            color="series",
            color_discrete_sequence=theme.CATEGORICAL,
            render_mode="svg",
        )
        fig.update_layout(
            title=f"{ts_t.value}: {label} per {ts_grain.value} of {ts_d.value} (exact)",
            height=420,
            yaxis_title=label,
            hovermode="x unified",
        )
        fig.show()


ts_t.observe(_tscols, "value")
for w in (ts_t, ts_d, ts_grain, ts_agg, ts_v, ts_split):
    w.observe(_draw_ts, "value")
_tscols()
h("### 8.4 Time explorer")
display(widgets.VBox([widgets.HBox([ts_t, ts_d, ts_v]), ts_grain, ts_agg, ts_split, out_ts]))

# %%
out_sc = widgets.Output()
sc_t = widgets.Dropdown(options=TABLES, value="transactions", description="table")
sc_x, sc_y = widgets.Dropdown(description="x"), widgets.Dropdown(description="y")
sc_c = widgets.Dropdown(description="colour")
sc_n = widgets.IntSlider(value=5000, min=1000, max=50000, step=1000, description="points")
sc_lx, sc_ly = widgets.Checkbox(description="log x"), widgets.Checkbox(description="log y")


def _sccols(*_):
    nums = p.cols_of(con, rel(sc_t.value), "numeric")
    sc_x.options, sc_y.options = nums, nums
    if len(nums) > 1:
        sc_y.value = nums[1]
    s = smp(sc_t.value)
    sc_c.options = ["(none)"] + [
        c for c in p.cols_of(con, rel(sc_t.value), "categorical", "boolean") if s[c].nunique() <= 8
    ]


def _draw_sc(*_):
    if not has_cols(sc_t.value, sc_x.value, sc_y.value, sc_c.value):
        return
    if not (sc_x.value and sc_y.value):
        return
    out_sc.clear_output(wait=True)
    colour = sc_c.value if sc_c.value and sc_c.value != "(none)" else None
    d = smp(sc_t.value)[[c for c in {sc_x.value, sc_y.value, colour} if c]].dropna()
    if sc_lx.value:
        d = d[d[sc_x.value] > 0]
    if sc_ly.value:
        d = d[d[sc_y.value] > 0]
    d = d.sample(min(len(d), sc_n.value), random_state=0)
    rho = d[sc_x.value].corr(d[sc_y.value], method="spearman") if len(d) > 2 else float("nan")
    with out_sc:
        fig = px.scatter(
            d,
            x=sc_x.value,
            y=sc_y.value,
            color=colour,
            log_x=sc_lx.value,
            log_y=sc_ly.value,
            opacity=0.5,
            marginal_x="histogram",
            marginal_y="histogram",
            color_discrete_sequence=theme.CATEGORICAL,
            render_mode="webgl",  # live kernel only; fast for 50k points
        )
        fig.update_traces(marker_size=4, selector=dict(type="scattergl"))
        fig.update_layout(
            title=f"{sc_t.value}: {sc_y.value} vs {sc_x.value} "
            f"({len(d):,} sampled rows, Spearman ρ = {rho:.2f})",
            height=560,
        )
        fig.show()


sc_t.observe(_sccols, "value")
for w in (sc_t, sc_x, sc_y, sc_c, sc_n, sc_lx, sc_ly):
    w.observe(_draw_sc, "value")
_sccols()
h("### 8.5 Scatter explorer")
display(
    widgets.VBox(
        [widgets.HBox([sc_t, sc_x, sc_y]), widgets.HBox([sc_c, sc_n, sc_lx, sc_ly]), out_sc]
    )
)

# %% [markdown]
# ### 8.6 Slice explorer
# Profile any **slice** of a table against the whole table, exactly, on the full data. Write a DuckDB `WHERE`
# clause (e.g. `currency = 'COP' and amount > 1e6`, `is_fraud`, `channel in ('ATM', 'POS')`), pick a column,
# and press **Run**. Categorical columns show the slice's share next to the table's share and the **lift**
# (slice ÷ table: above 1 means over-represented in the slice); numeric columns show both distributions on
# the same bins.

# %%
import duckdb

out_sl = widgets.Output()
sl_t = widgets.Dropdown(options=TABLES, value="transactions", description="table")
sl_w = widgets.Text(value="is_fraud", description="where", layout=widgets.Layout(width="60%"))
sl_c = widgets.Dropdown(description="column")
sl_log = widgets.Checkbox(value=False, description="log (numeric)")
sl_go = widgets.Button(description="Run", button_style="primary")


def _slcols(*_):
    cols = p.columns(con, rel(sl_t.value))
    sl_c.options = cols.loc[
        cols["kind"].isin(["numeric", "categorical", "boolean"]), "column"
    ].tolist()


def _draw_sl(*_):
    t, c, where = sl_t.value, sl_c.value, sl_w.value.strip() or "true"
    if not has_cols(t, c):
        return
    piece = f"(select * from {rel(t)} where {where})"
    out_sl.clear_output(wait=True)
    with out_sl:
        try:
            n_all = con.sql(f"select count(*) from {rel(t)}").fetchone()[0]
            n_sl = con.sql(f"select count(*) from {piece}").fetchone()[0]
        except duckdb.Error as e:
            h(f"**Query error:** `{e}`")
            return
        h(f"**Slice:** {n_sl:,} of {n_all:,} rows ({n_sl / max(n_all, 1):.2%}) where `{where}`")
        if not n_sl:
            return
        kind = p.columns(con, rel(t)).set_index("column").loc[c, "kind"]
        if kind == "numeric":
            x = f"{p.q(c)}::double"
            v = f"log10(case when {x} > 0 then {x} end)" if sl_log.value else x
            lo, hi = con.sql(f"select min({v}), max({v}) from {rel(t)}").fetchone()
            if lo is None:
                h("No values to plot.")
                return
            w = (hi - lo) / 50 if hi > lo else 1.0
            frames = []
            for label, src in (("table", rel(t)), ("slice", piece)):
                b = con.sql(f"""select least(floor(({v} - {lo}) / {w}), 49)::int b, count(*) n
                                from {src} where {v} is not null group by 1""").df()
                b["share"] = 100 * b["n"] / b["n"].sum()
                frames.append(b.assign(group=label))
            d = pd.concat(frames)
            d["x"] = lo + (d["b"] + 0.5) * w
            if sl_log.value:
                d["x"] = 10 ** d["x"]
            fig = px.bar(
                d,
                x="x",
                y="share",
                color="group",
                barmode="overlay",
                opacity=0.6,
                color_discrete_sequence=[theme.SEQ_BLUE[1], theme.ORANGE],
                log_x=sl_log.value,
            )
            fig.update_layout(
                title=f"{t}.{c}: slice vs table (% of each group's rows, same bins)",
                height=380,
                bargap=0,
                xaxis_title=c,
                yaxis_title="% of rows",
            )
        else:
            whole = p.value_counts(con, rel(t), c, top=1000)[["value", "share_pct"]]
            part = p.value_counts(con, piece, c, top=1000)[["value", "share_pct"]]
            d = part.merge(whole, on="value", how="left", suffixes=("_slice", "_table"))
            d = d[~d["value"].str.startswith("(other")].head(20)
            d["lift"] = d["share_pct_slice"] / d["share_pct_table"]
            long = d.melt(
                id_vars=["value", "lift"],
                value_vars=["share_pct_table", "share_pct_slice"],
                var_name="group",
                value_name="share",
            )
            long["group"] = long["group"].str.replace("share_pct_", "")
            fig = px.bar(
                long.iloc[::-1],
                x="share",
                y="value",
                color="group",
                barmode="group",
                orientation="h",
                hover_data={"lift": ":.2f"},
                color_discrete_sequence=[theme.ORANGE, theme.SEQ_BLUE[1]],
            )
            fig.update_yaxes(type="category")
            fig.update_layout(
                title=f"{t}.{c}: share in the slice vs the table (%; hover for lift)",
                height=max(340, 30 * len(d) + 160),
                xaxis_title="% of rows",
                yaxis_title="",
            )
        fig.show()


sl_t.observe(_slcols, "value")
sl_go.on_click(_draw_sl)
_slcols()
sl_c.value = "transaction_type"
display(widgets.VBox([widgets.HBox([sl_t, sl_c, sl_log]), widgets.HBox([sl_w, sl_go]), out_sl]))

# %% [markdown]
# ### 8.7 Row browser
# The cached sample of any table (PII and free-text columns removed), with column search and SearchBuilder
# filters. Change `TABLE` and re-run the cell.

# %%
TABLE = "transactions"
show(
    p.safe(smp(TABLE)).head(5000),
    caption=f"{TABLE}: first 5,000 sampled rows (PII removed)",
    layout={"top1": "searchBuilder"},
    pageLength=15,
    classes="display compact nowrap",
    scrollX=True,
)

# %% [markdown]
# ## 9 · Findings to carry into bronze and silver
# The cell below recomputes every number quoted here from the full raw tables, so the list stays honest
# if the extract changes. Each finding names the layer that should act on it.
#
# **Keys and integrity**
# 1. **Every primary key is unique and non-null** in all 12 keyed tables, and the complaint lifecycle has
#    no impossible date orders: the extracts are structurally sound.
# 2. **`customers.registration_branch_id` (100%) and `service_agents.assigned_branch_id` (≈99.8%) point to
#    branches that do not exist.** They share the `SUC-…` format of `branches.branch_id` but are
#    independent random codes, while `products.opening_branch_id` and `transactions.branch_id` resolve fully.
#    *Silver:* no join from customers or agents to branches; *gold:* an "unknown branch" member if one is modelled.
# 3. **24% of `digital_events` have no `customer_id`** (anonymous sessions); every non-null id resolves.
#    *Gold:* keep them in the clickstream fact with an "anonymous" customer member.
#
# **Money and currencies**
# 4. **`amount` mixes USD, COP and ARS**, about 10⁴× apart; it must never be summed across currencies.
#    **`amount_usd` is null for every USD row** (by design) and uses an **almost fixed rate** for COP
#    (≈4,000 ± 0.1%) and ARS (≈350 ± 0.1%), while the same pairs in `daily_exchange_rates` vary with a ≈1.2%
#    coefficient of variation: the conversion did not use the daily table. *Silver:* one reporting-currency
#    amount, from the daily FX table, filled for every row. The FX table itself has **no trend**: every pair
#    stays within ±2% of its median and drifts less than 0.2% over three years (no ARS devaluation), so it
#    reads as simulated rather than market data.
# 5. **All `México` transactions are in USD** (no MXN at all, although the FX table quotes MXN); their median
#    amount matches the other USD rows, so the label, not the scale, is suspect. To confirm with the data owner.
# 6. **`estimated_monthly_income` is in local currency** (median ≈ 39k MX, 0.8M AR, 9.2M CO): segment
#    comparisons across countries are meaningless until silver converts it.
#
# **Labels and conformance**
# 7. **`transaction_country` spells Mexico two ways** (`México` for domestic rows, `Mexico` for a cross-border
#    block of ≈40k rows like USA, Spain and Brazil). *Silver:* a conformed country dimension (ISO codes).
# 8. **NPS cannot be computed from this table as labelled:** NPS surveys only score 2–7, so there are no
#    promoters and the recomputed NPS is about −75; ≈3.3k NPS rows have no `nps_category`. Treat the score
#    scale as unknown until documented.
# 9. **Opens, clicks and conversions are not tracked for WhatsApp and Voice sends** (all null): funnel KPIs
#    exist only for Email, SMS and Push.
#
# **Quality of optional fields**
# 10. **Transaction coordinates are mostly placeholders:** ≈81% of rows have none, and about half of the
#     rest sit within 1.5° of (0, 0). *Silver:* null them; do not use them for geo features.
# 11. **Gaps are plain `NULL`s, no disguised placeholders**, so bronze needs no token cleaning, and no table
#     shows a time block (a field appearing or vanishing at some date; `campaign_sends` null rates swing by
#     month only because the channel mix does, and are flat within each channel). Missingness is mostly
#     **structural**: fields go missing together by design (complaint dates for stages a case has not reached,
#     merchant name + category, the latitude/longitude pair, the UTM triplet, `claimed_amount` + `currency`). Customer attributes are the
#     exception: their gaps are uncorrelated (random), so silver can impute them per column.
# 12. **Fraud is rare (≈0.1%, 1 in ~1,000) and `fraud_score` leaks the label.** No legitimate transaction
#     scores above 30, while fraud scores spread evenly over 0–100: `fraud_score > 30` flags fraud with 100%
#     precision and ≈55% recall. The score was likely generated from `is_fraud`, so it must **not** be a model
#     feature (*gold / ML:* drop it or treat it as a benchmark). Fraud rates are flat (≈0.1%) across type,
#     channel, country and merchant category, so categorical signal is weak.
# 13. **6% of credit products are over their limit**, and ≈15% of credit products with a recorded DPD are
#     past due; worth reconciling with collections rules in gold.
# 14. **Call-center timings exist only for voice:** wait time is recorded for phone calls alone, and handle
#     time for phone plus part of App and Web; Email, WhatsApp and Web Chat contacts have neither. Service
#     KPIs (wait, AHT) are comparable only on the phone channel until those channels are instrumented.

# %%
ev = {}
ev["PK duplicates (all keyed tables)"] = sum(
    p.pk_check(con, rel(t), k)["duplicate_keys"] for t, k in PK.items()
)
ev["customers.registration_branch_id orphan %"] = float(
    ri.set_index("child").loc["customers.registration_branch_id", "orphan_pct"]
)
ev["service_agents.assigned_branch_id orphan %"] = float(
    ri.set_index("child").loc["service_agents.assigned_branch_id", "orphan_pct"]
)
ev["digital_events null customer_id %"] = con.sql(
    "select 100 * avg((customer_id is null)::int) from m_digital_events"
).fetchone()[0]
ev["USD rows with amount_usd null %"] = con.sql(
    "select 100 * avg((amount_usd is null)::int) from m_transactions where currency = 'USD'"
).fetchone()[0]
for c in ("COP", "ARS"):
    ev[f"{c} implied fixed rate (amount / amount_usd), min–max"] = "{:,.2f} – {:,.2f}".format(
        *con.sql(
            f"""select min(amount / amount_usd), max(amount / amount_usd) from m_transactions
                where currency = '{c}' and amount_usd > 0"""
        ).fetchone()
    )
ev["USD→COP and USD→ARS daily rate, coefficient of variation %"] = " / ".join(
    f"{v:.2f}"
    for (v,) in con.sql(
        """select 100 * stddev(exchange_rate) / avg(exchange_rate) from m_daily_exchange_rates
           where source_currency = 'USD' and target_currency in ('COP', 'ARS')
           group by target_currency order by target_currency desc"""
    ).fetchall()
)
ev["México transactions not in USD"] = con.sql(
    "select count(*) from m_transactions where transaction_country = 'México' and currency <> 'USD'"
).fetchone()[0]
ev["'Mexico' (unaccented) transactions"] = con.sql(
    "select count(*) from m_transactions where transaction_country = 'Mexico'"
).fetchone()[0]
ev["NPS surveys: main_score range"] = "{} – {}".format(
    *con.sql(
        "select min(main_score), max(main_score) from m_satisfaction_surveys where survey_type = 'NPS'"
    ).fetchone()
)
ev["NPS recomputed"] = nps
ev["WhatsApp + Voice sends with a known open flag"] = con.sql(
    "select count(was_opened) from m_campaign_sends where send_channel in ('WhatsApp', 'Voice')"
).fetchone()[0]
ev["transactions without coordinates %"] = con.sql(
    "select 100 * avg((latitude is null)::int) from m_transactions"
).fetchone()[0]
ev["coordinates within 1.5° of (0, 0) %"] = 100 * nk / nn
ev["placeholder cells (all tables)"] = int(gaps["placeholders"].sum())
ev["fraud rate %"] = con.sql("select 100 * avg(is_fraud::int) from m_transactions").fetchone()[0]
ev["fraud_score > 30: precision % / recall %"] = (
    f"{100 * leak[1] / leak[2]:.1f} / {100 * leak[1] / leak[3]:.1f}"
)
ev["contacts with a wait time, by channel (%)"] = ", ".join(
    f"{ch} {v:.0f}"
    for ch, v in con.sql(
        """select channel, 100 * avg((wait_time_seconds is not null)::int) from m_call_center_interactions
           group by 1 order by count(*) desc"""
    ).fetchall()
)
ev["credit products over limit %"] = 100 * (util["utilisation"] > 1).mean()
ev["credit products with recorded DPD that are past due %"] = con.sql(
    "select 100 * avg((days_past_due > 0)::int) from m_products"
).fetchone()[0]
display(
    pd.Series(ev, name="value")
    .map(lambda v: f"{v:,.2f}" if isinstance(v, float) else (f"{v:,}" if isinstance(v, int) else v))
    .to_frame()
)
