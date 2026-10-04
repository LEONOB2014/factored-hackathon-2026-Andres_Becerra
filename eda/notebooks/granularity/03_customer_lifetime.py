# %% [markdown]
# # 03 · The customer over a lifetime: value, and when attrition starts
# **Granularity series** · grain: one row per customer (`agg.fct_customer_snapshot`), plus the monthly history
#
# **Stakeholders.** The head of retail (who are the valuable customers, and how concentrated is value), the
# retention team (how long until a customer lapses, and who lapses first) and finance (customer lifetime value for
# acquisition budgets).
#
# **What this grain adds.** A month is too short to see a relationship; the lifetime summarises it. Two questions only
# exist at this grain: how value is distributed across customers, and how long a customer stays engaged before the
# first lapse.
#
# **Methods.**
# 1. **RFM** (recency, frequency, monetary) scores and a **Lorenz curve** of value: how much of the bank's spend comes
#    from its top decile of customers.
# 2. **Survival to the first lapse.** A lapse is the first run of three months without a transaction (the 90-day
#    dormancy of the country series). Customers who never lapse before the last full month are **right-censored**:
#    we know only that their time to lapse exceeds what we observed. Kaplan–Meier curves estimate the survival
#    function S(t) = P(no lapse by month t) without bias from censoring; log-rank tests compare groups; a **Cox
#    proportional-hazards** model estimates hazard ratios for baseline covariates measured in the customer's first
#    three months only, and is judged on its concordance index on held-out customers.
# 3. **Restricted mean survival time** (the area under S(t) up to a horizon) turns survival into "expected engaged
#    months", the basis of a lifetime-value proxy.
#
# Customers already active when the data starts are left-truncated (their real start is earlier). Their clock starts at
# the window start: the curves describe engagement **from a given month on**, which is the question a retention team
# asks, not the time since account opening.

# %%
import sys
import time
from pathlib import Path

sys.path.insert(0, "../../src")
import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from IPython.display import Markdown, display
from itables import show
from lifelines import CoxPHFitter, KaplanMeierFitter
from lifelines.statistics import multivariate_logrank_test, proportional_hazard_test
from lifelines.utils import concordance_index, restricted_mean_survival_time
from scipy import stats

from latam_eda import country, theme
from latam_eda import granularity as g

OUT = Path("../../reports/tables")
OUT.mkdir(parents=True, exist_ok=True)
theme.register()
t0 = time.time()
pl = country.session("ALL", "main")
country.prepare(pl, "gold")
star = g.open_star(pl)
star.build(["fct_customer_month", "fct_customer_snapshot"], verbose=False)
FULL = star.q("select month_start from {dim_month} where not is_partial order by 1").month_start
FIRST, LAST = FULL.min(), FULL.max()

# %% [markdown]
# ## 1 · How concentrated is value?

# %%
snap = star.q("select * from {fct_customer_snapshot} order by customer_id")
v = snap.lifetime_outflow_usd.fillna(0).sort_values().to_numpy()
cum = np.cumsum(v) / v.sum()
gini = 1 - 2 * np.trapezoid(cum, dx=1 / len(v))
top10 = 1 - cum[int(0.9 * len(v)) - 1]
fig = go.Figure()
fig.add_trace(
    go.Scatter(
        x=np.linspace(0, 1, 200), y=np.quantile(cum, np.linspace(0, 1, 200)), name="customers"
    )
)
fig.add_trace(go.Scatter(x=[0, 1], y=[0, 1], name="equality", line=dict(dash="dot")))
fig.update_layout(
    title="Lorenz curve of lifetime spend (outflow)",
    xaxis_title="share of customers (poorest first)",
    yaxis_title="share of spend",
    height=380,
)
fig.show()
display(
    Markdown(
        f"**The top 10 % of customers account for {100 * top10:.1f} % of lifetime spend (Gini {gini:.3f}).** "
        + (
            "Value is only moderately concentrated: no small group of customers carries the business. In real retail "
            "banking the top decile typically holds well over half of the value; a value-tiered service model would "
            "have little to tier on this data."
            if top10 < 0.3
            else "Value is concentrated: retention effort should be tiered by value."
        )
    )
)

# %%
snap["R"] = pd.qcut(-snap.recency_months.fillna(99), 5, labels=False, duplicates="drop") + 1
snap["F"] = pd.qcut(snap.tx_per_active_month.fillna(0).rank(method="first"), 5, labels=False) + 1
snap["M"] = (
    pd.qcut(snap.outflow_per_active_month.fillna(0).rank(method="first"), 5, labels=False) + 1
)
rfm = (
    snap.groupby(["R", "F"])
    .agg(customers=("customer_id", "size"), spend=("lifetime_outflow_usd", "sum"))
    .reset_index()
)
fig = px.density_heatmap(
    rfm,
    x="F",
    y="R",
    z="customers",
    histfunc="sum",
    text_auto=True,
    title="Customers by recency (R, 5 = most recent) and frequency (F, 5 = most frequent) quintiles",
)
fig.update_layout(height=380)
fig.show()
corr = snap[
    ["recency_months", "tx_per_active_month", "outflow_per_active_month", "lifetime_contacts"]
].corr(method="spearman")
show(corr.round(3), paging=False)

# %% [markdown]
# ## 2 · Survival to the first 90-day lapse

# %%
hist = star.q(f"""select customer_id, month_start, n_tx, sessions, contacts, products_held
                  from {{fct_customer_month}} where month_start between '{FIRST}' and '{LAST}'
                  order by customer_id, month_start""")
tx = hist.pivot(index="customer_id", columns="month_start", values="n_tx").fillna(0).to_numpy()
ses = hist.pivot(index="customer_id", columns="month_start", values="sessions").fillna(0).to_numpy()
con = hist.pivot(index="customer_id", columns="month_start", values="contacts").fillna(0).to_numpy()
prd = (
    hist.pivot(index="customer_id", columns="month_start", values="products_held")
    .fillna(0)
    .to_numpy()
)
ids = hist.customer_id.drop_duplicates().to_numpy()
n_m = tx.shape[1]
active = tx > 0
start = np.where(active.any(axis=1), active.argmax(axis=1), -1)
zero = ~active
run3 = np.zeros_like(zero)
run3[:, 2:] = (
    zero[:, 2:] & zero[:, 1:-1] & zero[:, :-2]
)  # month m closes a 3-month zero run (m-2, m-1, m)
# Landmark design: covariates are measured in the customer's first three months of activity (s .. s+2) and the risk
# clock starts at the landmark L = s+3, so no covariate overlaps the outcome it predicts. A lapse counts only if its
# three empty months all fall at or after L (a run closing at m >= L+2); duration is months from L to the lapse start.
dur, event = np.full(len(ids), np.nan), np.zeros(len(ids), dtype=bool)
for i in range(len(ids)):
    s = start[i]
    if s < 0 or s + 3 + 2 >= n_m:  # never active, or too little follow-up after the landmark
        continue
    landmark = s + 3
    after = np.nonzero(run3[i, landmark + 2 :])[0]
    if len(after):
        dur[i], event[i] = after[0] + 1, True
    else:
        dur[i] = n_m - landmark
surv = pd.DataFrame({"customer_id": ids, "duration": dur, "lapsed": event, "start_index": start})
first3 = lambda m: [m[i, s : s + 3].sum() if s >= 0 else 0 for i, s in enumerate(start)]  # noqa: E731
surv["sessions_first3"] = first3(ses)
surv["contacts_first3"] = first3(con)
surv["tx_first3"] = first3(tx)
surv["products_at_start"] = [prd[i, s] if s >= 0 else 0 for i, s in enumerate(start)]
surv = surv.merge(
    snap[
        [
            "customer_id",
            "country_code",
            "segment",
            "age_years",
            "credit_score",
            "monthly_income_usd",
        ]
    ],
    on="customer_id",
).dropna(subset=["duration"])
surv["digital_first3"] = surv.sessions_first3 > 0
display(
    Markdown(
        f"**{len(surv):,} customers with at least one transaction and follow-up after their first three months; "
        f"{100 * surv.lapsed.mean():.1f} % lapse (three months without a transaction) after the landmark, "
        f"{100 * (1 - surv.lapsed.mean()):.1f} % are censored.** Never-active customers: {int((start < 0).sum()):,}."
    )
)

# %%
km_rows = []
fig = go.Figure()
for grp in ["country_code", "segment", "digital_first3"]:
    for val, d in surv.groupby(grp):
        km = KaplanMeierFitter().fit(d.duration, d.lapsed, label=f"{grp}={val}")
        rmst = restricted_mean_survival_time(km, t=24)
        km_rows.append(
            {
                "group": grp,
                "value": str(val),
                "customers": len(d),
                "lapsed %": round(100 * d.lapsed.mean(), 1),
                "median months to lapse": km.median_survival_time_,
                "S(12)": round(float(km.predict(12)), 4),
                "RMST 24 months": round(float(rmst), 2),
            }
        )
        if grp == "country_code":
            fig.add_trace(
                go.Scatter(
                    x=km.survival_function_.index,
                    y=km.survival_function_.iloc[:, 0],
                    name=str(val),
                    line_shape="hv",
                )
            )
fig.update_layout(
    title="Kaplan–Meier: probability of no 90-day lapse, by market",
    xaxis_title="months since the landmark (first activity + 3 months)",
    yaxis_title="S(t)",
    height=380,
)
fig.show()
kmt = pd.DataFrame(km_rows)
lr = {
    grp: multivariate_logrank_test(surv.duration, surv[grp], surv.lapsed).p_value
    for grp in ["country_code", "segment", "digital_first3"]
}
kmt["logrank_p"] = kmt.group.map(lr)
show(kmt, paging=False)
display(
    Markdown(
        f"**Half of all customers have had a 90-day lapse after {KaplanMeierFitter().fit(surv.duration, surv.lapsed).median_survival_time_:.0f} "
        "months.** Log-rank tests by group: "
        + ", ".join(f"{k} p = {v:.3g}" for k, v in lr.items())
        + ". "
        + (
            "No group lapses at a different rate: market, segment and early digital use do not change how long a "
            "customer stays engaged."
            if all(p > 0.01 for p in lr.values())
            else f"Some differences are statistically significant (p < 0.01), but the survival at 12 months differs by "
            f"at most {100 * kmt.groupby('group')['S(12)'].agg(lambda x: x.max() - x.min()).max():.1f} points between "
            "groups: with 134,000 customers a negligible difference is detectable. Significant, not material: no group "
            "needs its own retention treatment."
            if kmt.groupby("group")["S(12)"].agg(lambda x: x.max() - x.min()).max() < 0.02
            else "Some groups lapse at materially different rates: see the table."
        )
    )
)

# %% [markdown]
# ## 3 · Cox proportional hazards: who lapses first?
# Baseline covariates only (profile, plus behaviour in the first three months of activity), so the model could score
# a customer three months after the window opens. Customers are split 70/30 at random (by a hash of the id) to judge
# the model on customers it has not seen; the concordance index (C) is the probability that, of two customers, the
# one the model ranks riskier lapses first (0.5 = chance). Proportionality of hazards is tested with the Schoenfeld
# residual test.

# %%
cox_df = surv[
    [
        "duration",
        "lapsed",
        "country_code",
        "segment",
        "age_years",
        "credit_score",
        "monthly_income_usd",
        "products_at_start",
        "tx_first3",
        "sessions_first3",
        "contacts_first3",
    ]
].copy()
for c in ["monthly_income_usd", "tx_first3", "sessions_first3", "contacts_first3"]:
    cox_df[c] = np.log1p(cox_df[c].fillna(0))
cox_df = pd.get_dummies(
    cox_df, columns=["country_code", "segment"], drop_first=True, dtype=float
).fillna(0)
# a deterministic 30 % of customers: a stable hash of the id (Python's hash() is salted per process)
held_out = pd.util.hash_pandas_object(surv.customer_id, index=False).to_numpy() % 10 >= 7
cph = CoxPHFitter(penalizer=0.01).fit(cox_df[~held_out], "duration", "lapsed")
hr = cph.summary[["exp(coef)", "exp(coef) lower 95%", "exp(coef) upper 95%", "p"]].rename(
    columns={"exp(coef)": "hazard ratio"}
)
show(hr.round(4), paging=False)
risk = cph.predict_partial_hazard(cox_df[held_out])
c_idx = concordance_index(cox_df[held_out].duration, -risk, cox_df[held_out].lapsed)
rng = np.random.default_rng(7)
te = cox_df[held_out].reset_index(drop=True)
rk = risk.reset_index(drop=True)
boot = []
for _ in range(100):
    i = rng.integers(0, len(te), len(te))
    boot.append(concordance_index(te.duration[i], -rk[i], te.lapsed[i]))
c_lo, c_hi = np.quantile(boot, [0.025, 0.975])
ph = proportional_hazard_test(cph, cox_df[~held_out], time_transform="rank")
viol = ph.summary[ph.summary.p < 0.01]
sig = hr[(hr.p < 0.01)]
display(
    Markdown(
        f"**Held-out concordance {c_idx:.3f} [{c_lo:.3f}, {c_hi:.3f}].** "
        + (
            "The baseline profile and early behaviour do not rank who lapses first better than chance."
            if c_lo <= 0.5
            else f"{len(sig)} covariates have a hazard ratio significant at 1 %: "
            + ", ".join(f"{k} (HR {r['hazard ratio']:.2f})" for k, r in sig.iterrows())
            + "."
        )
        + (
            f" The proportional-hazards assumption is rejected (p < 0.01) for {', '.join(viol.index)}: their effect "
            "changes over time, so their hazard ratios are averages."
            if len(viol)
            else " The proportional-hazards assumption holds for every covariate."
        )
    )
)
se = (c_hi - c_lo) / 3.92
targets = pd.DataFrame(
    [
        {
            "grain": "customer (lifetime)",
            "target": "time to first 90-day lapse",
            "kind": "survival",
            "train_rows": int((~held_out).sum()),
            "test_rows": int(held_out.sum()),
            "test_positives": int(cox_df[held_out].lapsed.sum()),
            "base_rate": float(cox_df[held_out].lapsed.mean()),
            "metric": "concordance",
            "value": c_idx,
            "ci_low": c_lo,
            "ci_high": c_hi,
            "baseline": 0.5,
            "p_value": float(stats.norm.sf((c_idx - 0.5) / se)) if se > 0 else np.nan,
            "best_single_feature": hr["hazard ratio"].sub(1).abs().idxmax(),
            "verdict": (
                "learnable: rank customers by lapse risk"
                if c_lo > 0.55
                else "weak: rules, not models"
                if c_lo > 0.5
                else "no evidence of signal"
            ),
        }
    ]
).reindex(columns=g.TARGET_COLUMNS)
targets.to_csv(OUT / "granularity_targets_customer.csv", index=False)
kmt.to_csv(OUT / "granularity_survival_customer.csv", index=False)

# %% [markdown]
# ## 4 · From survival to a lifetime-value proxy
# Expected engaged months in the next two years (RMST at 24 months) times the customer's spend per active month gives
# a transparent value proxy: what the bank stands to keep if the customer stays engaged. It is a proxy (spend, not
# margin; no product economics in the data), but it ranks customers in the way a value-based retention budget needs.

# %%
km_all = KaplanMeierFitter().fit(surv.duration, surv.lapsed)
rmst24 = float(restricted_mean_survival_time(km_all, t=24))
snap["value_proxy_usd"] = rmst24 * snap.outflow_per_active_month.fillna(0)
tiers = snap.groupby(
    pd.qcut(snap.value_proxy_usd.rank(method="first"), 10, labels=range(1, 11))
).agg(
    customers=("customer_id", "size"),
    mean_value_proxy=("value_proxy_usd", "mean"),
    mean_contacts=("lifetime_contacts", "mean"),
    mean_complaints=("lifetime_complaints", "mean"),
)
show(tiers.round(2), paging=False)
ratio = tiers.mean_contacts.iloc[-1] / max(tiers.mean_contacts.iloc[0], 1e-9)
display(
    Markdown(
        f"**Expected engaged months over the next 24: {rmst24:.1f}.** The top value decile averages "
        f"{tiers.mean_value_proxy.iloc[-1]:,.0f} USD of proxy value against {tiers.mean_value_proxy.iloc[0]:,.0f} for "
        f"the bottom decile, and contacts the bank {ratio:.2f}× as often. "
        + (
            "Cost to serve does not rise with value: service is not where value is protected or lost."
            if 0.8 <= ratio <= 1.25
            else "Cost to serve moves with value: budget service effort by value tier."
        )
    )
)

# %% [markdown]
# ## Findings, decisions and what they mean downstream
# * **KPIs at this grain:** value concentration (top-decile share, Gini), the Kaplan–Meier lapse curve per market (S(12),
#   median time to lapse), expected engaged months (RMST) and the value-proxy distribution. They are reported, not
#   predicted: the dashboard of the head of retail.
# * **Models:** the Cox verdict above decides whether a lapse-risk ranking is worth building; the 90-day dormancy rate
#   model (ADR-012) remains the operational tool, because it updates every month with the latest behaviour.
# * **Downstream:** `fct_customer_snapshot` is cheap (one row per customer, rebuilt from the monthly fact) and is the
#   natural input of a relationship-manager assistant ("summarise this customer"); survival estimates belong in the
#   analytics layer, refreshed monthly, with censoring handled explicitly (never an average of the lapsed customers'
#   durations).

# %%
pl.close()
print(f"notebook time {time.time() - t0:.0f}s")
