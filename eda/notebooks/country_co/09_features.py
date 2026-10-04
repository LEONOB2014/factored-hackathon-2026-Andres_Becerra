# %% [markdown]
# # 09 · Point-in-time features plus the country calendar (Colombia)
# **Country series · Colombia** · *generated from `notebooks/country_template`: edit the template*
#
# The feature layer (point-in-time windows, out-of-time splits with an embargo, leakage guards; pipeline series,
# notebook 09) rebuilt on Colombia, then **enriched with the country's local calendar** from notebook 04:
# local hour, weekday, holiday, long weekend, payday window, days since payday, month end, bonus month. Each feature
# is checked alone against the fraud label, with an interval, on this country's validation period.

# %%
import sys
import time

sys.path.insert(0, "../../src")
import numpy as np
import pandas as pd
import plotly.graph_objects as go
from IPython.display import Markdown, display
from itables import show
from sklearn.metrics import roc_auc_score

from latam_eda import country, theme

COUNTRY = "CO"
DATASET = "main"
PREFIX = "country"
CTRY = country.SCOPES[COUNTRY]
theme.register()
t0 = time.time()
pl = country.session(COUNTRY, DATASET)
country.prepare(pl, "gold")
FEATURES = sorted(n for n in pl.catalog()["node"] if n.startswith(("feat_", "ml_")))
built = pl.build_set(FEATURES)
country.enrich_transactions(pl)

# %% [markdown]
# ## 1 · Splits and label rates in this country

# %%
sp = pl.q("""select split, count(*) as transactions, sum(label_is_fraud::int) as frauds,
                    round(100 * avg(label_is_fraud::int), 4) as fraud_pct, min(anchor_ts) as first_ts, max(anchor_ts) as last_ts
             from {feat_fraud_realtime_pit} group by 1 order by 5""")
show(sp, paging=False)
nval = int(sp.loc[sp.split == "valid", "frauds"].sum())
nval_rows = int(sp.loc[sp.split == "valid", "transactions"].sum())
display(
    Markdown(
        f"**{nval} frauds in {CTRY.name}'s validation period ({nval_rows:,} transactions).** "
        + (
            "The validation period is **empty**: the fixed split dates of `feat_fraud_realtime_pit` fall after the last "
            "transaction of this dataset, so the fraud model would have nothing to be validated or tested on. The "
            "single-feature check below cannot run; notebook 14 uses its own time split on the rows that exist."
            if nval_rows == 0
            else "Enough for an AUC interval of about ±0.03."
            if nval >= 300
            else "Few positives: every AUC below carries a wide interval, and a country-level fraud model would be evaluated on "
            "too few cases to be approved by a model-risk reviewer."
        )
    )
)

# %% [markdown]
# ## 2 · Point-in-time features plus calendar features, each alone

# %%
val = pl.q("""
    select f.*, t.local_hour_customer, t.iso_weekday, t.is_holiday, t.is_long_weekend, t.is_payday,
           t.days_since_payday, t.is_month_end, t.is_bonus_month
    from {ml_fraud_valid} f join main.tx_local t using (transaction_id)""")
y = val["label_is_fraud"].astype(int).to_numpy() if len(val) else np.array([], dtype=int)
CAL = [
    "local_hour_customer",
    "iso_weekday",
    "is_holiday",
    "is_long_weekend",
    "is_payday",
    "days_since_payday",
    "is_month_end",
    "is_bonus_month",
]
rows = []
for c in val.columns:
    if c == "label_is_fraud" or not (
        pd.api.types.is_numeric_dtype(val[c]) or pd.api.types.is_bool_dtype(val[c])
    ):
        continue
    x = val[c].astype(float).to_numpy()
    m = ~np.isnan(x)
    npos, nneg = int(y[m].sum()), int((1 - y[m]).sum())
    if npos < 5 or np.unique(x[m]).size < 2:
        continue
    a = roc_auc_score(y[m], x[m])
    se = country.hanley_mcneil(a, npos, nneg)
    rows.append(
        {
            "feature": c,
            "kind": "calendar" if c in CAL else "point-in-time",
            "auc": round(a, 4),
            "ci_low": round(a - 1.96 * se, 4),
            "ci_high": round(a + 1.96 * se, 4),
            "frauds": npos,
        }
    )
auc = pd.DataFrame(
    rows, columns=["feature", "kind", "auc", "ci_low", "ci_high", "frauds"]
).sort_values("auc")
fig = go.Figure()
for kind, color in (("point-in-time", "#3987e5"), ("calendar", "#e6943b")):
    d = auc[auc.kind == kind]
    fig.add_trace(
        go.Scatter(
            x=d.auc,
            y=d.feature,
            mode="markers",
            name=kind,
            marker=dict(color=color),
            error_x=dict(
                type="data", symmetric=False, array=d.ci_high - d.auc, arrayminus=d.auc - d.ci_low
            ),
        )
    )
fig.add_vline(x=0.5, line_dash="dot")
fig.update_layout(
    title=f"{CTRY.title}: single-feature AUC on the validation period (95 % CI)",
    height=760,
    yaxis_title=None,
)
fig.show()
show(auc.sort_values("auc", ascending=False), paging=False)
signal = auc[(auc.ci_low > 0.5) | (auc.ci_high < 0.5)]
display(
    Markdown(
        f"**{len(signal)} of {len(auc)} features have an interval that excludes 0.5 in {CTRY.name}.** "
        + (
            "Nothing to test: the validation period has no frauds."
            if not len(auc)
            else "None does: the fraud label carries no behavioural or calendar signal here either."
            if not len(signal)
            else "Those with an interval excluding 0.5: "
            + ", ".join(signal.feature)
            + ". With this many features tested, about one in twenty would cross by chance at 95 %: treat isolated crossings "
            "as noise unless notebook 14's multivariate out-of-time test confirms them."
        )
    )
)

# %% [markdown]
# ## 3 · Guards

# %%
pl.ensure_until("features_graph_knowledge")
t = pl.run_tests("features_graph_knowledge")
show(t[t.test.str.startswith("assert_")][["test", "failures", "status"]], paging=False)

# %% [markdown]
# ## Findings for Colombia and what to do
# The computed statements above. The feature layer is correct in every country; the calendar enrichment is kept for
# real data; the learnability verdict across all candidate targets, with every feature at once, is notebook 14.

# %%
pl.close()
print(f"notebook time {time.time() - t0:.0f}s")
