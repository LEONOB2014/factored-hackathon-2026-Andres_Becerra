# %% [markdown]
# # 09 · Features: point in time, out of time, no leakage
# **Pipeline series** · task group `features_graph_knowledge`, part 1: `models/features`
#
# ## What happens here
# Features are the inputs of models. In banking they must satisfy three properties, and the feature layer is built
# around them:
# 1. **Point in time (PIT).** A feature for an event uses only what was knowable at that moment. A "transactions in
#    the last 24 hours" feature computed with today's data would include transactions that happened *after* the event:
#    the model would look excellent offline and fail in production.
# 2. **Out of time.** Train on the past, validate and test on later periods, with an **embargo** between them so no
#    feature window straddles a boundary.
# 3. **No label leakage.** Nothing that encodes the label may be a feature: `fraud_score` is absent by design (it
#    deterministically produces `is_fraud`).
#
# | model | grain | purpose |
# |---|---|---|
# | `feat_fraud_realtime_pit` | transaction | velocity, history deviation, novelty, geo-velocity, digital context, label and split |
# | `ml_fraud_train` / `_valid` / `_test` | transaction | the out-of-time splits, embargo removed |
# | `feat_fraud_stream_parity` | transaction (holdout) | the batch reference the Flink streaming features must equal |
# | `feat_credit_eligibility_pit` | customer × month-end | 12 month-ends of PIT credit behaviour |
# | `ml_kumo_relational_complaint90d` | customer × cutoff | "files a complaint in the next 90 days" for relational models |
# | `ml_kumo_tabular_fraud` | transaction | a bounded context set for in-context tabular models |

# %%
import sys
import time

sys.path.insert(0, "../../src")
import ipywidgets as w
import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from IPython.display import display
from itables import show
from sklearn.metrics import roc_auc_score

from latam_eda import pipeline as pipe
from latam_eda import theme

theme.register()
t0 = time.time()
pl = pipe.session()
pl.ensure_until("gold")
FEATURES = sorted(n for n in pl.catalog()["node"] if n.startswith(("feat_", "ml_")))
built = pl.build_set(FEATURES)

# %% [markdown]
# ## 1 · How the windows avoid looking ahead
# The fraud features are window functions over each customer's transactions, ordered by time:
# * **velocity**: `RANGE BETWEEN INTERVAL 24 HOUR PRECEDING AND CURRENT ROW EXCLUDE CURRENT ROW`: other transactions
#   in the previous 24 hours, never the current one;
# * **history**: `ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING`: everything strictly before (an expanding window);
# * **digital context**: an `ASOF` join attaching the last login **at or before** the transaction.
#
# Transactions with the same timestamp count as prior to each other, which is what a streaming aggregator sees. The
# same definitions are written as Flink SQL for the online path, and `feat_fraud_stream_parity` is the batch result the
# stream must reproduce row by row.

# %%
print(
    "\n".join(
        ln for ln in pl.sql("feat_fraud_realtime_pit").splitlines() if "preceding" in ln.lower()
    )[:2500]
)

# %% [markdown]
# ## 2 · The out-of-time split and its embargo

# %%
sp = pl.q("""select split, count(*) as transactions, round(100 * avg(label_is_fraud::int), 4) as fraud_pct,
                    min(anchor_ts) as first_ts, max(anchor_ts) as last_ts
             from {feat_fraud_realtime_pit} group by 1 order by 4""")
show(sp, paging=False)
fig = go.Figure()
for r in sp.itertuples():
    fig.add_trace(
        go.Bar(
            x=[(r.last_ts - r.first_ts).days + 1],
            y=["split"],
            base=[r.first_ts],
            orientation="h",
            name=f"{r.split} ({r.transactions:,})",
        )
    )
fig.update_layout(
    barmode="overlay", height=220, title="Split timeline", xaxis_type="date", yaxis_visible=False
)
fig.show()

# %% [markdown]
# **Reading.**
# * **Train** (2023-06 → 2025-06-23), **valid** (2025-07 → 2025-12-24), **test** (2026-01 → 2026-05-17), each with its
#   own fraud rate (0.100 %, 0.094 %, 0.088 %): a slow decline the model must survive, which is exactly what an
#   out-of-time test measures and a random split hides.
# * The **embargo** rows (57,151, the 7 days before each boundary) are excluded from training: their 7-day windows
#   reach across the boundary.
# * **`stream_holdout`** (657 rows): transactions *timestamped* after the stream cutoff but delivered in the last
#   historical file (the batch window runs to 06:00 next day, notebook 04). They belong to the stream, and the split
#   keeps them out of all three sets. That is the batch-window convention handled correctly at the feature level.

# %% [markdown]
# ## 3 · Coverage: which features exist for how many transactions

# %%
cols = [
    c
    for c in pl.columns("feat_fraud_realtime_pit")["column_name"]
    if c
    not in ("transaction_id", "customer_id", "product_id", "anchor_ts", "split", "label_is_fraud")
]
cov = pl.q(
    "select "
    + ", ".join(f'round(100 * count("{c}") / count(*), 2) as "{c}"' for c in cols)
    + " from {feat_fraud_realtime_pit}"
).T.reset_index()
cov.columns = ["feature", "filled %"]
fig = px.bar(
    cov.sort_values("filled %"),
    x="filled %",
    y="feature",
    orientation="h",
    title="Share of transactions with each feature filled",
)
fig.update_layout(height=640, yaxis_title=None)
fig.show()

# %% [markdown]
# Almost every feature is filled for every transaction, with one exception: **geo-velocity** (`km_from_prev_tx`,
# `implied_speed_kmh`) exists for **3.3 %** of transactions. It needs two consecutive transactions that both carry
# coordinates, and 81 % of transactions have none (notebook 02). "Impossible travel", one of the strongest card-fraud
# signals in real banks, is therefore almost unavailable here, as notebook 02 predicted from the login data.

# %% [markdown]
# ## 4 · Is there anything to learn? Single-feature AUC on the validation split
# Each feature alone, against the label, on the 715 k validation transactions (676 frauds). AUC 0.5 is a coin toss.
# The 95 % interval uses the Hanley–McNeil standard error, which depends on the number of positives: with few
# positives, an AUC far from 0.5 can still be noise.

# %%
val = pl.q("select * from {ml_fraud_valid}")
y = val["label_is_fraud"].astype(int).to_numpy()
rows = []
for c in val.columns:
    if c == "label_is_fraud" or not (
        pd.api.types.is_numeric_dtype(val[c]) or pd.api.types.is_bool_dtype(val[c])
    ):
        continue
    x = val[c].astype(float).to_numpy()
    m = ~np.isnan(x)
    npos, nneg = int(y[m].sum()), int((1 - y[m]).sum())
    if npos < 5:
        continue
    a = roc_auc_score(y[m], x[m])
    q1, q2 = a / (2 - a), 2 * a * a / (1 + a)
    se = np.sqrt(
        (a * (1 - a) + (npos - 1) * (q1 - a * a) + (nneg - 1) * (q2 - a * a)) / (npos * nneg)
    )
    rows.append(
        {
            "feature": c,
            "auc": round(a, 4),
            "ci_low": round(a - 1.96 * se, 4),
            "ci_high": round(a + 1.96 * se, 4),
            "frauds": npos,
            "rows": int(m.sum()),
        }
    )
auc = pd.DataFrame(rows).sort_values("auc")
fig = go.Figure(
    go.Scatter(
        x=auc.auc,
        y=auc.feature,
        mode="markers",
        error_x=dict(
            type="data",
            symmetric=False,
            array=auc.ci_high - auc.auc,
            arrayminus=auc.auc - auc.ci_low,
        ),
    )
)
fig.add_vline(x=0.5, line_dash="dot")
fig.update_layout(
    title="Single-feature AUC with 95 % interval (validation split)", height=640, yaxis_title=None
)
fig.show()
show(auc.sort_values("auc", ascending=False), paging=False)

# %% [markdown]
# **No feature separates fraud from non-fraud.** Every 95 % interval contains 0.5. The widest are the geo-velocity
# features, measured on 24 k rows that contain only 26 frauds (interval 0.37–0.58): there is no evidence either way. This is the leakage finding of the EDA reproduced on the warehouse's own leak-free features: once
# `fraud_score` is excluded, **the label has no behavioural content**, so no model, however sophisticated, can learn
# fraud from it.
#
# **What the feature layer is still worth.** Everything here is correct engineering: PIT windows, embargo, stream
# parity, no leak. The day confirmed fraud labels arrive (chargebacks, analyst dispositions), this layer trains a real
# model without change. Until then, the honest uses are the **unsupervised anomaly ensemble** (which needs features,
# not labels) and rules.

# %% [markdown]
# ## 5 · The guards: PIT and leakage tests
# Three singular tests protect the layer: velocity recomputed by brute force must equal the windowed value (and
# history may never include later events); logins attached by the ASOF join must not be later than the transaction; no
# feature table may expose `fraud_score` or other label-carrying columns.

# %%
pl.ensure_until("features_graph_knowledge")
t = pl.run_tests("features_graph_knowledge")
show(
    t[t.attached_to.str.startswith(("feat_", "ml_"), na=False) | t.test.str.startswith("assert_")][
        ["test", "attached_to", "severity", "failures", "status"]
    ],
    paging=False,
)

# %% [markdown]
# ## 6 · Credit features: 12 month-ends, and which columns are safe for training

# %%
cr = pl.q("""select snapshot_date, count(*) as customers, round(avg(months_with_inflow_6m_pit), 2) as avg_months_with_inflow,
                    round(avg(tx_count_3m_pit), 2) as avg_tx_3m
             from {feat_credit_eligibility_pit} group by 1 order by 1""")
show(cr, paging=False)
cc = pl.columns("feat_credit_eligibility_pit")
cc["safe for training on past months"] = np.where(
    cc.column_name.str.endswith("_current"),
    "no (current state)",
    np.where(cc.column_name.str.endswith("_pit"), "yes", "key"),
)
show(cc[["column_name", "data_type", "safe for training on past months"]], paging=False)

# %% [markdown]
# * **One row per customer and month-end** (2025-05-31 → 2026-04-30). The eligibility mart reads the latest month-end,
#   which is up to a month old by design: monthly policy decisions on monthly features.
# * Columns ending in **`_current`** (score, income, segment) come from today's dimensions. Using them as features for
#   *past* months would leak the future (a score that was updated after a default "predicts" it). They become
#   PIT-safe once the SCD2 snapshots hold history. The naming convention makes this visible to every user of the
#   table; the governance check enforces `pit_required` on the features folder.

# %% [markdown]
# ## 7 · Tables for foundation models

# %%
kumo = pl.q("""select split, count(*) as rows_, count(distinct customer_id) as customers,
                      round(100 * avg(label_complaint_90d::int), 2) as positive_pct,
                      min(cutoff_ts) as first_cutoff, max(cutoff_ts) as last_cutoff
               from {ml_kumo_relational_complaint90d} group by 1 order by 5""")
show(kumo, paging=False)
show(
    pl.q("select label_is_fraud, count(*) as rows_ from {ml_kumo_tabular_fraud} group by 1"),
    paging=False,
)

# %% [markdown]
# * `ml_kumo_relational_complaint90d`: the entity table for a relational model (KumoRFM-style): customer × cutoff, label
#   = a complaint in the 90 days after the cutoff (3.6 % positive). The related tables are filtered to "before the
#   cutoff" when loaded. Complaints are the one target here that is **not derived from a score**, which makes this
#   the learned use case worth trying first; whether contacts, sentiment and activity predict it is the experiment.
# * `ml_kumo_tabular_fraud`: all fraud rows plus a fixed 1 % sample of non-fraud, for in-context tabular models with a
#   bounded context; evaluation must re-weight by the sampling rate. It inherits the label problem of section 4.

# %% [markdown]
# ## 8 · Explorer: one feature against the label

# %%
num_cols = auc["feature"].tolist()
w_f = w.Dropdown(options=num_cols, value="amount_zscore_vs_history", description="feature")
out_f = w.Output()


def draw_feature(*_):
    with out_f:
        out_f.clear_output()
        c = w_f.value
        d = val[[c, "label_is_fraud"]].dropna()
        d["decile"] = pd.qcut(d[c].rank(method="first"), 10, labels=False) + 1
        g = d.groupby("decile").agg(
            fraud_pct=("label_is_fraud", lambda s: 100 * s.mean()), rows=(c, "size")
        )
        fig = px.bar(
            g.reset_index(),
            x="decile",
            y="fraud_pct",
            title=f"Fraud rate by decile of {c} (validation)",
        )
        fig.add_hline(y=100 * d.label_is_fraud.mean(), line_dash="dot", annotation_text="base rate")
        fig.update_layout(height=320)
        fig.show()


w_f.observe(draw_feature, "value")
draw_feature()
display(w.VBox([w_f, out_f]))

# %% [markdown]
# ## Findings and what to do
# 1. **The feature layer is engineered correctly**: PIT windows that exclude the current row, ASOF logins, a 7-day
#    embargo, stream parity, and passing guards. Keep the three PIT tests mandatory.
# 2. **The label has no learnable content** (single-feature AUC ≈ 0.5 with intervals around it). Do not train a
#    supervised fraud model on `is_fraud`; use the anomaly ensemble and rules, and collect confirmed labels.
# 3. **Geo-velocity exists for 3.3 % of transactions** and time-of-day carries no information (notebook 04): two of
#    the strongest real-world fraud signals cannot be validated on this data.
# 4. **`_current` credit columns must never train a model on past months**; the naming convention and the
#    governance check keep them visible.
# 5. **The complaint-in-90-days task is the learned use case to try first** (3.6 % positives, a label not derived
#    from a score); evaluate it with average precision against its base rate and an out-of-time split.

# %%
pl.close()
print(f"notebook time {time.time() - t0:.0f}s")
