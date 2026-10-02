# %% [markdown]
# # 03 · Is the mismatch a time shift?
# **CRISP-DM phase 2→3** · hypothesis **H1**: *the backup holds the same records stored on different dates.*
#
# A "time shift" can mean three different things; we test them separately because they have different
# remedies:
#
# | | claim | test |
# |---|---|---|
# | **H1a** | the **whole series** is lagged (one global offset) | weekday-phase rotation, de-seasonalised cross-correlation |
# | **H1b** | **individual rows** are re-dated (same key, different date) | offsets of rows that share a key |
# | **H1c** | rows are re-dated **and otherwise identical** (a clean re-partitioning) | content matched-filter: are fingerprint-equal rows separated by a common offset? |
#
# Preliminary probes (see chat) suggested a whole-day offset on shared transaction keys that grows over time.
# This notebook measures it properly and checks whether it *explains* the mismatch.

# %%
import sys

sys.path.insert(0, "../src")
import ipywidgets as w
import numpy as np
import pandas as pd
import plotly.graph_objects as go
import ruptures as rpt
from IPython.display import display
from plotly.subplots import make_subplots
from scipy import stats

from latam_eda import theme
from latam_eda.data import DERIVED, ROOT, connect

theme.register()
con = connect()
TABLES = {  # table: (primary key, timestamp column)
    "transactions": ("transaction_id", "transaction_date"),
    "digital_events": ("event_id", "event_date"),
    "call_center_interactions": ("interaction_id", "interaction_date"),
    "campaign_sends": ("send_id", "send_date"),
    "complaints": ("complaint_id", "creation_date"),
}
OUT = ROOT / "reports" / "tables"

# %% [markdown]
# ## 1 · H1a — is the *whole series* shifted?
# If the backup were the main series moved by *k* days, two things would show up in the **daily counts**:
# the weekday/weekend pattern would be rotated by *k mod 7*, and the cross-correlation of the
# de-seasonalised series would peak at lag *k*. We test both on every fact table with a full history.


# %%
def daily(prefix, t):
    return (
        con.sql(f"select process_date d, count(*) n from {prefix}_{t} group by 1 order by 1")
        .df()
        .set_index("d")
        .n
    )


rot_rows, ccf = [], {}
for t in [
    "transactions",
    "call_center_interactions",
    "digital_events",
    "campaign_sends",
    "complaints",
]:
    m, b = daily("m", t), daily("b", t)
    idx = m.index.intersection(b.index)
    for q, g in pd.Series(1, index=idx).groupby(idx.to_period("Q")):
        if len(g) < 60:
            continue
        pm, pb = (
            m[g.index].groupby(g.index.dayofweek).mean(),
            b[g.index].groupby(g.index.dayofweek).mean(),
        )
        pm, pb = (pm - pm.mean()) / pm.std(), (pb - pb.mean()) / pb.std()
        corr = [np.dot(np.roll(pm.values, r), pb.values) / 7 for r in range(7)]
        rot_rows.append(
            dict(
                table=t,
                quarter=str(q),
                best_rotation=int(np.argmax(corr)),
                corr_at_0=corr[0],
                corr_best=max(corr),
            )
        )

    # de-seasonalised residuals: subtract the weekday mean, then cross-correlate
    def resid(s):
        return s - s.groupby(s.index.dayofweek).transform("mean")

    a, c_ = resid(m[idx]).values, resid(b[idx]).values
    a, c_ = (a - a.mean()) / a.std(), (c_ - c_.mean()) / c_.std()
    ccf[t] = (
        pd.Series(
            {
                k: np.mean(a[max(0, k) : len(a) + min(0, k)] * c_[max(0, -k) : len(c_) - max(0, k)])
                for k in range(-30, 31)
            }
        ),
        1.96 / np.sqrt(len(idx)),
    )
rot = pd.DataFrame(rot_rows)
rot_summary = rot.groupby("table").agg(
    quarters=("quarter", "count"),
    quarters_best_rotation_0=("best_rotation", lambda s: int((s == 0).sum())),
    mean_corr_at_0=("corr_at_0", "mean"),
)
rot_summary

# %%
fig = make_subplots(rows=1, cols=len(ccf), shared_yaxes=True, subplot_titles=list(ccf))
for i, (t, (s, ci)) in enumerate(ccf.items(), 1):
    fig.add_bar(
        x=s.index,
        y=s.values,
        marker_color=[theme.BLUE if k != 0 else theme.ORANGE for k in s.index],
        showlegend=False,
        row=1,
        col=i,
    )
    fig.add_hline(y=ci, line_dash="dot", line_color="#8a8984", row=1, col=i)
    fig.add_hline(y=-ci, line_dash="dot", line_color="#8a8984", row=1, col=i)
fig.update_layout(
    title="Cross-correlation of weekday-adjusted daily counts, main vs backup (lag in days; dotted = 95 % noise band)",
    height=330,
    bargap=0.2,
)
fig.update_xaxes(title_text="lag (days)")
fig.show()

# %% [markdown]
# **Interpretation (H1a).** For transactions, interactions, sends and complaints the best weekday rotation is **0 in
# every quarter** (digital events: 8 of 12 quarters, their weekly profile is noisier with a mid-week spike) and
# the weekday pattern is identical (weekend ≈ 0.6–0.7× weekdays on the *same* calendar days in both folders). A
# lag of 1–6 days would rotate that pattern. After removing it, the residual daily counts of the two folders
# are **uncorrelated at every lag** (all bars sit inside the noise band, including lag 0, highlighted):
# daily volumes in the backup are independent noise around the same weekly profile.
# **A global time shift is rejected.** (The early cross-correlation peaks at ±7, ±14, ±28 lags that a naive
# analysis shows are pure weekly seasonality.)

# %% [markdown]
# ## 2 · H1b — row-level offsets for rows that share a key
# For every key present in both folders we compute `offset = backup_date − main_date` (days of `process_date`
# and seconds of the event timestamp). Results are cached in `data/derived/` for later notebooks.

# %%
offsets = {}
for t, (k, ts) in TABLES.items():
    df = con.sql(f"""select m.{k} pk, m.process_date md, b.process_date bd,
                            date_diff('day', m.process_date, b.process_date) k_days,
                            date_diff('second', m.{ts}, b.{ts}) k_sec
                     from m_{t} m join b_{t} b using({k})""").df()
    df["md"] = pd.to_datetime(df.md)
    offsets[t] = df
    df.to_parquet(DERIVED / f"offsets_{t}.parquet")

rows = []
for t, d in offsets.items():
    rows.append(
        dict(
            table=t,
            pairs=len(d),
            offset_zero_pct=100 * (d.k_days == 0).mean(),
            whole_day_ts_pct=100 * (d.k_sec % 86400 == 0).mean(),
            mean_days=d.k_days.mean(),
            median_days=d.k_days.median(),
            sd_days=d.k_days.std(),
            min_days=d.k_days.min(),
            max_days=d.k_days.max(),
            spearman_dates=stats.spearmanr(d.md.astype("int64"), d.bd.astype("int64"))[0],
        )
    )
off_summary = pd.DataFrame(rows)
off_summary.to_csv(OUT / "time_offsets_summary.csv", index=False)
off_summary.style.format(
    {
        "pairs": "{:,.0f}",
        "offset_zero_pct": "{:.1f}",
        "whole_day_ts_pct": "{:.1f}",
        "mean_days": "{:.2f}",
        "median_days": "{:.0f}",
        "sd_days": "{:.2f}",
        "spearman_dates": "{:.5f}",
    }
)

# %% [markdown]
# **Reading the table.**
# * The offset is **never a constant**: transactions sit at 0…+7 days, digital events at −18…+11,
#   interactions at −5…+5, campaign sends at **−7 to −166 days**, complaints at exactly 0.
# * It is **not always a whole number of days**: only 39 % (events) and 60 % (sends) of pairs have an
#   offset that is a multiple of 24 h, so the row is not merely "re-dated" — the time of day also differs.
# * Yet the mapping is **perfectly monotone** (Spearman ρ ≈ 1.0000): the order of shared rows in time is
#   preserved. That is the signature of two *sequences* walking through the same ID stream at slightly different speeds.

# %%
fig = make_subplots(
    rows=len(offsets),
    cols=1,
    shared_xaxes=False,
    subplot_titles=[f"{t}: backup − main date (days), by main month" for t in offsets],
    vertical_spacing=0.07,
)
for i, (t, d) in enumerate(offsets.items(), 1):
    g = d.groupby(d.md.dt.to_period("M")).k_days.describe(percentiles=[0.1, 0.5, 0.9])
    x = g.index.to_timestamp()
    fig.add_scatter(
        x=x,
        y=g["90%"],
        mode="lines",
        line=dict(width=0),
        showlegend=False,
        row=i,
        col=1,
        hoverinfo="skip",
    )
    fig.add_scatter(
        x=x,
        y=g["10%"],
        mode="lines",
        line=dict(width=0),
        fill="tonexty",
        fillcolor="rgba(42,120,214,.18)",
        showlegend=False,
        row=i,
        col=1,
        hoverinfo="skip",
    )
    fig.add_scatter(
        x=x,
        y=g["50%"],
        mode="lines+markers",
        line=dict(color=theme.BLUE, width=2),
        marker=dict(size=4),
        showlegend=False,
        name=t,
        row=i,
        col=1,
        hovertemplate="%{x|%Y-%m}<br>median %{y:.0f} d<extra></extra>",
    )
    fig.add_hline(y=0, line_dash="dot", line_color="#8a8984", row=i, col=1)
fig.update_layout(
    height=190 * len(offsets) + 80,
    title="Row-level date offsets drift smoothly over time (band = 10th–90th percentile)",
)
fig.show()

# %% [markdown]
# **Interpretation (H1b).** Offsets are smooth, table-specific **drift curves**, not a calendar constant:
# transactions slide from ≈ +1 d (Oct 2023) to ≈ +6 d (mid-2024); events swing between +8 and −13 d; interactions
# stay within a few days of zero (weak drift, R² 0.11); campaign sends fall **linearly by ≈ 13–15 days per quarter**. The
# month-to-month scatter is small compared to the drift, so each table behaves like a deterministic
# warp of one sequence against the other, plus a few days of jitter.

# %% [markdown]
# ## 3 · Model comparison: constant, linear, or segmented drift?
# We fit three models to the monthly median offset of each table and rank them by BIC
# (lower is better): **constant**, **linear trend**, **piece-wise constant** with change-points found by
# binary segmentation (`ruptures`, ≤ 3 breakpoints).


# %%
def bic(y, yhat, p):
    n = len(y)
    rss = max(float(np.sum((y - yhat) ** 2)), 1e-9)
    return n * np.log(rss / n) + p * np.log(n)


rows, fits = [], {}
for t, d in offsets.items():
    s = d.groupby(d.md.dt.to_period("M")).k_days.median()
    y, x = s.values.astype(float), np.arange(len(s), dtype=float)
    if len(y) < 8:
        continue
    const = np.full_like(y, y.mean())
    slope, icpt = np.polyfit(x, y, 1)
    lin = slope * x + icpt
    algo = rpt.Binseg(model="l2", min_size=3).fit(y.reshape(-1, 1))
    best = None
    for nb in (1, 2, 3):
        if (nb + 1) * 3 > len(y):
            break
        try:
            bk = algo.predict(n_bkps=nb)
        except rpt.exceptions.BadSegmentationParameters:
            continue
        seg = np.zeros_like(y)
        a = 0
        for e in bk:
            seg[a:e] = y[a:e].mean()
            a = e
        sc = bic(y, seg, 2 * nb + 1)
        if best is None or sc < best[0]:
            best = (sc, seg, bk)
    if best is None:
        best = (np.inf, const, [len(y)])
    cand = {
        "constant": (bic(y, const, 1), const),
        "linear": (bic(y, lin, 2), lin),
        "piecewise-constant": (best[0], best[1]),
    }
    winner = min(cand, key=lambda k: cand[k][0])
    ss_tot = np.sum((y - y.mean()) ** 2) or 1
    rows.append(
        dict(
            table=t,
            months=len(y),
            bic_constant=cand["constant"][0],
            bic_linear=cand["linear"][0],
            bic_piecewise=cand["piecewise-constant"][0],
            winner=winner,
            slope_days_per_month=slope,
            r2_linear=1 - np.sum((y - lin) ** 2) / ss_tot,
            breakpoints=[str(s.index[i - 1]) for i in best[2][:-1]],
        )
    )
    fits[t] = (s, cand[winner][1], winner)
model_cmp = pd.DataFrame(rows)
model_cmp.to_csv(OUT / "time_shift_model_comparison.csv", index=False)
model_cmp.style.format(
    {
        "bic_constant": "{:.1f}",
        "bic_linear": "{:.1f}",
        "bic_piecewise": "{:.1f}",
        "slope_days_per_month": "{:+.2f}",
        "r2_linear": "{:.2f}",
    }
)

# %% [markdown]
# **Interpretation.** A constant offset is rejected for every table that has a drift (BIC gap of ≈ 23 for
# transactions, ≈ 50 events, ≈ 38 interactions, ≈ 270 sends). **Transactions** (+0.36 d/month, R² 0.80) and
# **campaign sends** (−4.6 d/month, R² ≈ 1.00) are best described by a *linear* drift; **digital events** and
# **interactions** need change-points (events: Mar 2024, Jan 2025, Jun 2025). Only complaints are constant (0).
# This rules out "a fixed N-day storage delay" as the generating mechanism.

# %% [markdown]
# ## 4 · H1c — do *content-identical* rows share a common offset? (matched filter)
# The decisive test for a clean re-dating: take rows whose **business content** is identical across folders
# (ignoring keys and dates) and histogram their date difference. A true shift of *k* days would put all the mass
# at *k*; independent draws give a broad, symmetric, noise-like histogram.

# %%
# Only transactions have a discriminating fingerprint (uniqueness 0.99, notebook 02). Events/interactions/sends
# fingerprints are low-entropy: a many-to-many join explodes to billions of meaningless pairs, so they are excluded.
fp = {
    "transactions": "amount, currency, transaction_type, channel, transaction_country, merchant_name, fraud_score"
}
mf = {}
for t, cols in fp.items():
    d = con.sql(f"""
        with a as (select hash({cols}) h, process_date d from m_{t}),
             b as (select hash({cols}) h, process_date d from b_{t})
        select date_diff('day', a.d, b.d) k, count(*) n from a join b using(h) group by 1 order by 1""").df()
    mf[t] = d
fig = make_subplots(
    rows=1,
    cols=1,
    subplot_titles=[f"{t} (content-matched pairs: {int(d.n.sum()):,})" for t, d in mf.items()],
)
for i, (t, d) in enumerate(mf.items(), 1):
    d = d[d.k.between(-400, 400)]
    fig.add_bar(x=d.k, y=d.n, marker_color=theme.BLUE, showlegend=False, row=1, col=i)
fig.update_layout(
    title="Date offset between content-identical transactions (backup − main, days)",
    height=360,
    bargap=0,
)
fig.update_xaxes(title_text="backup − main date (days)")
fig.show()

# %%
tx = mf["transactions"]
peak = tx.loc[tx.n.idxmax()]
mf_stats = pd.DataFrame(
    [
        dict(
            table=t,
            pairs=int(d.n.sum()),
            modal_offset=int(d.loc[d.n.idxmax(), "k"]),
            share_at_mode_pct=100 * d.n.max() / d.n.sum(),
            share_within_pm7_pct=100 * d[d.k.abs() <= 7].n.sum() / d.n.sum(),
            uniform_expectation_pct=100 * 15 / (d.k.max() - d.k.min() + 1),
        )
        for t, d in mf.items()
    ]
)
mf_stats.style.format(
    {
        "pairs": "{:,.0f}",
        "share_at_mode_pct": "{:.2f}",
        "share_within_pm7_pct": "{:.1f}",
        "uniform_expectation_pct": "{:.1f}",
    }
)

# %% [markdown]
# **Interpretation (H1c).** Two populations are visible. A **flat, broad background** spread over hundreds of
# days (coincidental content matches from the generator's finite value pools) and a **sharp peak at +1…+7
# days**: the modal offset (+2 d) holds 8.3 % of pairs and 30.8 % of all pairs fall within ±7 days, against ≈ 1 %
# expected from a uniform spread. So **a small set of transactions *are* the same record re-dated by a few days**.
# Section 6 isolates that set.

# %% [markdown]
# ## 6 · Inside the shared keys: *clones* vs *key collisions* (transactions)
# Of the 61,361 transactions that share an ID, some are the same business transaction re-dated (**clones**:
# identical amount, currency, type, channel, merchant and fraud score), the rest only share the ID
# (**collisions**: different transaction, same label).

# %%
pairs = con.sql("""
    select m.transaction_id pk, m.process_date md, b.process_date bd,
           date_diff('day', m.process_date, b.process_date) k_days,
           (m.amount = b.amount and m.currency = b.currency and m.transaction_type = b.transaction_type
            and m.channel = b.channel and m.fraud_score is not distinct from b.fraud_score
            and m.merchant_name is not distinct from b.merchant_name) as is_clone,
           (m.customer_id = b.customer_id) same_customer, (m.product_id = b.product_id) same_product
    from m_transactions m join b_transactions b using(transaction_id)""").df()
pairs["md"] = pd.to_datetime(pairs.md)
pairs.to_parquet(DERIVED / "transaction_pairs.parquet")
tab = pairs.groupby("is_clone").agg(
    pairs=("pk", "size"),
    mean_offset=("k_days", "mean"),
    sd_offset=("k_days", "std"),
    same_customer=("same_customer", "mean"),
    same_product=("same_product", "mean"),
)
tab.index = tab.index.map(
    {True: "clone (same transaction, re-dated)", False: "collision (same ID only)"}
)
tab.style.format(
    {
        "pairs": "{:,.0f}",
        "mean_offset": "{:.2f}",
        "sd_offset": "{:.2f}",
        "same_customer": "{:.1%}",
        "same_product": "{:.1%}",
    }
)

# %%
fig = make_subplots(
    rows=1, cols=2, subplot_titles=["Offset distribution (days)", "Monthly mean offset"]
)
for flag, name, col in ((True, "clones", theme.BLUE), (False, "collisions", theme.ORANGE)):
    d = pairs[pairs.is_clone == flag]
    h = d.k_days.value_counts(normalize=True).sort_index()
    fig.add_bar(x=h.index, y=h.values, name=name, marker_color=col, row=1, col=1)
    g = d.groupby(d.md.dt.to_period("M")).k_days.mean()
    fig.add_scatter(
        x=g.index.to_timestamp(),
        y=g.values,
        mode="lines+markers",
        name=name,
        line=dict(color=col),
        showlegend=False,
        row=1,
        col=2,
    )
fig.update_layout(
    barmode="group",
    height=360,
    title="Clones and collisions drift identically → the date offset belongs to the key stream, not to the content",
)
fig.show()

# %% [markdown]
# **Interpretation.** Clones (19 % of shared keys, **11,734 transactions = 0.27 % of main**) and collisions share
# the same offset distribution and the same drift over time, so the offset is a property of the *key position*, not of the
# record. Customer **and** product keys of clones differ in 100 % of cases: the clones were re-keyed as well as re-dated,
# and the customer mapping they imply does **not** agree with the one implied by complaints (0 of 4,335 checked).
# There is no single consistent re-keying — which is why notebook 04 matches on content, not on IDs.

# %% [markdown]
# ## 5 · A timestamp convention we must not confuse with a shift
# Many tables store `process_date` as the **local** business date and the timestamp 6 hours ahead of it
# (UTC−6 convention). Without this, 25 % of rows look like they were "processed the day before the event".

# %%
rows = []
for t, (k, ts) in {**TABLES, "satisfaction_surveys": ("survey_id", "survey_date")}.items():
    for p, lab in (("m", "main"), ("b", "backup")):
        if p == "b" and t == "satisfaction_surveys":
            continue
        r = con.sql(f"""select round(100*avg((cast({ts} as date)=process_date)::int),2),
                               round(100*avg((cast({ts} - interval 6 hour as date)=process_date)::int),2)
                        from {p}_{t}""").fetchone()
        rows.append(
            dict(
                table=t,
                folder=lab,
                ts_date_equals_process_date_pct=r[0],
                ts_minus_6h_equals_process_date_pct=r[1],
            )
        )
tzc = pd.DataFrame(rows)
tzc

# %% [markdown]
# **Interpretation.** Subtracting 6 h from the timestamp reproduces `process_date` for **100 %** of
# transactions and campaign sends and 99.8 % of events — in both folders — versus only 75 % without it. For interactions
# and complaints it holds for 91.6 % (the other ~8 % need a larger offset, a further anomaly picked up in notebook 07).
# This is a *schema convention*, identical in both folders; it must be applied before any day-level join.

# %% [markdown]
# ## Interactive explorer
# Choose a table and a date window; the histogram shows the row-level offsets of shared keys in that window.

# %%
dd = w.Dropdown(options=list(offsets), value="transactions", description="table")
rng = w.SelectionRangeSlider(
    options=[str(x.date()) for x in pd.date_range("2023-06-01", "2026-06-01", freq="MS")],
    index=(0, 36),
    description="main month",
    layout=w.Layout(width="650px"),
)
out = w.Output()


def draw(_=None):
    d = offsets[dd.value]
    lo, hi = pd.Timestamp(rng.value[0]), pd.Timestamp(rng.value[1])
    d = d[(d.md >= lo) & (d.md <= hi)]
    out.clear_output(wait=True)
    with out:
        if d.empty:
            print("no shared keys in this window")
            return
        f = go.Figure(go.Histogram(x=d.k_days, marker_color=theme.BLUE, xbins=dict(size=1)))
        f.update_layout(
            title=f"{dd.value}: offsets of {len(d):,} shared keys (mean {d.k_days.mean():.2f} d, sd {d.k_days.std():.2f})",
            height=340,
            xaxis_title="backup − main (days)",
            yaxis_title="pairs",
            bargap=0.05,
        )
        display(f)


dd.observe(draw, "value")
rng.observe(draw, "value")
draw()
display(w.VBox([dd, rng, out]))

# %% [markdown]
# ## Decision & consequences
# | hypothesis | verdict | basis |
# |---|---|---|
# | **H1a** whole-series lag | **Rejected** | weekday phase identical (rotation 0 in every quarter); no cross-correlation peak at any lag |
# | **H1b** row-level offsets on shared keys | **Confirmed, but not a calendar shift** | offsets exist, are monotone and smoothly drifting, table-specific, not whole-day for events/sends, from −166 to +10 days |
# | **H1c** clean re-dating of identical rows | **Confirmed for a 0.27 % core only** | 11,734 transaction clones re-dated by +0…+7 d; the other 99.7 % have no counterpart |
#
# **So the mismatch is *not* caused by a time shift.** The ~3 % of rows that share a key are positioned by a
# drifting **ID-sequence offset** between two generator runs, and 81 % of them still disagree on content (notebook 05).
# Re-dating the backup would therefore *not* make the folders comparable; for notebook 04 we align only
# where a defensible mapping exists — shared keys (with the measured per-month drift) and the complaint anchors — and
# keep everything else as independent replicates.
