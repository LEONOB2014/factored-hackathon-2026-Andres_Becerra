# %% [markdown]
# # 10 · Method comparison and consensus
# **CRISP-DM phase 5 (evaluation)** — we now hold 12 scoring methods (notebooks 08–09) plus a classical univariate baseline. Four questions:
#
# 1. **Do the methods agree?** (rank correlation, overlap of top alerts, method families)
# 2. **Does combining them help?** (rank-fusion ensembles, selected on a validation half and judged on a test half)
# 3. **Which method should I trust for which kind of anomaly?** (scorecard)
# 4. **What do the detectors flag in the *real* data, and do the findings replicate in the backup?**

# %%
import sys
import warnings

sys.path.insert(0, "../src")
warnings.filterwarnings("ignore")
import ipywidgets as w
import numpy as np
import pandas as pd
import plotly.graph_objects as go
from IPython.display import display
from plotly.subplots import make_subplots
from pyod.models.copod import COPOD
from scipy import stats
from scipy.cluster import hierarchy
from sklearn.ensemble import IsolationForest
from sklearn.metrics import average_precision_score
from sklearn.preprocessing import QuantileTransformer, RobustScaler, StandardScaler

from latam_eda import theme
from latam_eda.anomaly import FEATURES, INJECTED, inject_anomalies, load_or_build
from latam_eda.data import DERIVED, ROOT, connect

theme.register()
con = connect()
OUT = ROOT / "reports" / "tables"
SEED = 7

# %% [markdown]
# ## 1 · Assemble all scores on the common evaluation rows
# Notebook 08 scored 10 methods, notebook 09 two neural ones, all on the **same 100 k rows** (verified there). We add a classical **univariate** baseline —
# the maximum robust z-score (median/MAD) over the continuous features, i.e. what a rule-of-thumb "outlier on any column" screen would do.

# %%
a = pd.read_parquet(DERIVED / "bench_scores_main.parquet")
b = pd.read_parquet(DERIVED / "bench_scores_deep.parquet")
assert (a.transaction_id.values == b.transaction_id.values).all()
scores = pd.concat([a, b[["Autoencoder", "VAE (neg. ELBO)"]]], axis=1)
meta = scores[
    ["transaction_id", "customer_id", "anomaly_type", "is_injected", "is_fraud", "fraud_score"]
].copy()
methods = [c for c in scores.columns if c not in meta.columns]

main = load_or_build(con, "m", n=300_000, seed=1)
bench = inject_anomalies(main, rate=0.01, seed=SEED)
rng = np.random.default_rng(SEED)
ev = rng.choice(len(bench), 100_000, replace=False)
assert (bench.iloc[ev].transaction_id.values == meta.transaction_id.values).all()
Xb = bench[FEATURES].astype(float).replace([np.inf, -np.inf], np.nan)
Xb = Xb.fillna(Xb.median())
cont = ["log_usd", "log_gap_prev", "n_last_24h", "ratio_to_cust_median", "cust_n_trx"]
med = Xb[cont].median()
mad = (Xb[cont] - med).abs().median().replace(0, 1)
scores["Univariate max |robust z|"] = (
    (0.6745 * (Xb[cont].iloc[ev] - med) / mad).abs().max(axis=1).values
)
methods.append("Univariate max |robust z|")
y = meta.is_injected.values
typ = meta.anomaly_type.values
print(f"{len(methods)} methods on {len(y):,} rows, {y.sum():,} injected")

FAMILY = {
    "Isolation Forest": "isolation",
    "HBOS": "marginal",
    "COPOD": "marginal",
    "ECOD": "marginal",
    "Robust Mahalanobis": "distance",
    "GMM (6 comp.)": "density",
    "kNN distance (k=20)": "distance",
    "LOF (k=30)": "density",
    "One-Class SVM": "boundary",
    "PCA reconstruction": "reconstruction",
    "Autoencoder": "reconstruction",
    "VAE (neg. ELBO)": "reconstruction",
    "Univariate max |robust z|": "classical univariate",
}

# %% [markdown]
# ## 2 · Do the methods agree?
# *Rank correlation* (Spearman) of the scores over all rows, and the *Jaccard overlap* of the top-1,000 alerts. Methods are ordered by hierarchical clustering so families appear as blocks.

# %%
R = scores[methods].rank(pct=True)
sp = R.corr(method="spearman")
k = 1000
tops = {m: set(np.argsort(-scores[m].values)[:k]) for m in methods}
jac = pd.DataFrame(
    [[len(tops[i] & tops[j]) / len(tops[i] | tops[j]) for j in methods] for i in methods],
    index=methods,
    columns=methods,
)
order = hierarchy.leaves_list(
    hierarchy.linkage(1 - sp.values[np.triu_indices(len(methods), 1)], "average")
)
om = [methods[i] for i in order]
fig = make_subplots(
    rows=1,
    cols=2,
    subplot_titles=[
        "Spearman rank correlation of scores",
        f"Jaccard overlap of the top-{k:,} alerts",
    ],
    horizontal_spacing=0.2,
)
fig.add_heatmap(
    z=sp.loc[om, om].values,
    x=om,
    y=om,
    zmin=-1,
    zmax=1,
    colorscale=[[0, "#a62b2b"], [0.5, "#f0efec"], [1, "#184f95"]],
    colorbar=dict(x=0.43, len=0.8, title="ρ"),
    row=1,
    col=1,
)
fig.add_heatmap(
    z=jac.loc[om, om].values,
    x=om,
    y=om,
    zmin=0,
    zmax=1,
    colorscale=[[0, "#f0efec"], [1, "#184f95"]],
    colorbar=dict(len=0.8, title="J"),
    row=1,
    col=2,
)
fig.update_layout(height=560, title="Method agreement (clustered order)", margin=dict(l=170, b=170))
fig.update_xaxes(tickangle=-45)
fig.update_yaxes(autorange="reversed")
fig.show()

# %% [markdown]
# **Interpretation.** Agreement is only moderate: methods that look at *different geometry* produce different alert lists. The clustered order separates families — marginal/rank methods (HBOS, COPOD, ECOD), distance methods,
# isolation, reconstruction (PCA/AE/VAE) — and the Jaccard panel shows that even strong methods share only part of their top alerts. This is the quantitative argument for **ensembling**: if all methods agreed,
# combining them could not help.

# %% [markdown]
# ## 3 · Ensembles by rank fusion
# We split the evaluation rows into a **validation** and a **test** half. *Greedy forward selection* adds, at each step, the method whose inclusion in the **mean-rank** ensemble most improves validation AP; the ensemble is then scored on the
# untouched test half. We also report the full 13-method mean rank and **reciprocal-rank fusion (RRF)**. Selecting on validation and judging on test avoids the optimism of choosing the best combination on the same data.

# %%
idx = np.arange(len(y))
va, te = idx[idx % 2 == 0], idx[idx % 2 == 1]
Rn = scores[methods].rank(pct=True)


def ap(cols, rows, how="mean"):
    s = (
        Rn.iloc[rows][cols].mean(axis=1)
        if how == "mean"
        else (1 / (60 + scores[cols].iloc[rows].rank(ascending=False))).sum(axis=1)
    )
    return average_precision_score(y[rows], s)


chosen, hist = [], []
for _ in range(5):
    cand = [(ap(chosen + [m], va), m) for m in methods if m not in chosen]
    best = max(cand)
    chosen.append(best[1])
    hist.append((len(chosen), best[1], best[0], ap(chosen, te)))
sel = pd.DataFrame(hist, columns=["size", "added", "val AP", "test AP"])
sel

# %%
single = pd.Series(
    {m: average_precision_score(y[te], scores[m].values[te]) for m in methods}
).sort_values(ascending=False)
board = (
    pd.concat(
        [
            single.rename("test AP"),
            pd.Series(
                {
                    f"ENSEMBLE greedy-{len(chosen)} (mean rank)": ap(chosen, te),
                    "ENSEMBLE all 13 (mean rank)": ap(methods, te),
                    "ENSEMBLE all 13 (RRF)": ap(methods, te, "rrf"),
                    "ENSEMBLE top-3 singles (mean rank)": ap(list(single.index[:3]), te),
                }
            ).rename("test AP"),
        ]
    )
    .sort_values(ascending=False)
    .to_frame()
)
board.to_csv(OUT / "ensemble_leaderboard.csv")
fig = go.Figure(
    go.Bar(
        y=board.index[::-1],
        x=board["test AP"][::-1],
        orientation="h",
        marker_color=[
            theme.ORANGE if i.startswith("ENSEMBLE") else theme.BLUE for i in board.index[::-1]
        ],
    )
)
fig.add_vline(x=y[te].mean(), line_dash="dot", line_color="#8a8984")
fig.update_layout(
    height=520,
    margin=dict(l=260),
    title="Test-half average precision: single detectors (blue) vs ensembles (orange)",
    xaxis_title="average precision",
)
fig.show()
print("greedy selection:", " + ".join(chosen))

# %% [markdown]
# **Interpretation.** Fusing complementary detectors helps, **but selection matters more than size**. The best single detector (COPOD) scores AP 0.687 on the test half; fusing the three best singles (COPOD + robust Mahalanobis + Isolation Forest — one marginal, one distance, one isolation method)
# gives **0.773 (+0.09)** and the validation-selected greedy ensemble 0.76; reciprocal-rank fusion of all 13 gets 0.70. Simply **averaging all 13 ranks collapses to 0.26** — weak or blind members (LOF, PCA, the univariate screen, the autoencoder) drown the signal. Greedy selection stops improving after 3 members
# (validation AP 0.731 → 0.718 at size 5), a sign that a small, diverse committee is the right size.

# %% [markdown]
# ## 4 · Scorecard — which method for which anomaly?
# Recall at the top-1 % budget per type, plus the **worst-case type** (a method that is blind to one class is dangerous in production), stability across folders (notebook 08) and a qualitative explainability grade.

# %%
budget = int(0.01 * len(y))
rows = {}
allc = {m: scores[m].values for m in methods}
allc["ENSEMBLE greedy"] = Rn[chosen].mean(axis=1).values
for m, s in allc.items():
    top = np.zeros(len(y), bool)
    top[np.argsort(-s)[:budget]] = True
    rows[m] = {t: top[typ == t].mean() for t in INJECTED}
rec = pd.DataFrame(rows).T
rec["mean recall"] = rec[INJECTED].mean(axis=1)
rec["worst type"] = rec[INJECTED].min(axis=1)
rec["AP"] = pd.Series({m: average_precision_score(y, s) for m, s in allc.items()})
stab = pd.read_csv(OUT / "ml_stability_main_vs_backup.csv", index_col=0)
rec["Δ AP on backup"] = stab["Δ"].reindex(rec.index)
EXPL = {
    "Isolation Forest": "medium",
    "HBOS": "high",
    "COPOD": "high",
    "ECOD": "high",
    "Robust Mahalanobis": "medium",
    "GMM (6 comp.)": "low",
    "kNN distance (k=20)": "low",
    "LOF (k=30)": "low",
    "One-Class SVM": "low",
    "PCA reconstruction": "medium",
    "Autoencoder": "medium (per-feature error)",
    "VAE (neg. ELBO)": "medium (per-feature error)",
    "Univariate max |robust z|": "very high",
    "ENSEMBLE greedy": "medium",
}
rec["explainability"] = pd.Series(EXPL)
rec = rec.sort_values("mean recall", ascending=False)
rec.to_csv(OUT / "method_scorecard.csv")
rec.style.format(
    {
        **dict.fromkeys(INJECTED + ["mean recall", "worst type"], "{:.0%}"),
        "AP": "{:.3f}",
        "Δ AP on backup": "{:+.3f}",
    }
).background_gradient(subset=INJECTED + ["mean recall"], cmap="Blues", vmin=0, vmax=1)

# %% [markdown]
# **Interpretation.** The scorecard exposes where each family is blind. **No detector is good on every class** — the best *worst-type* recall is only 12 %, always on `dormant_reactivation`, the anomaly that the first-transaction placeholder hides (notebook 08): only LOF (34 %), GMM (12 %), the VAE (8 %) and One-Class SVM (7 %) see anything of it.
# The ensemble raises the **mean** recall to 72 % (amount spike 90 %, foreign and velocity bursts 100 %, low-and-slow 71 %) but cannot rescue a class that all its members miss — **ensembling combines strengths, it cannot create information the features lack**; the fix for dormancy is feature engineering (flag first transactions), not another model.
# The *classical univariate* screen is perfect on the point anomaly (100 % amount spike) yet at ≈ 0 % on every combination, and it is the most explainable; the opposite holds for density/neural methods. A bank would typically run the explainable screen for point anomalies plus a small ensemble for combinations.

# %% [markdown]
# ## 5 · What do the detectors flag in the *real* data?
# Fit three complementary detectors on the clean (un-injected) main sample, take the rows flagged by **≥ 2 of 3** at the 0.5 % level, and profile them against the rest.


# %%
def real_flags(df, seed=0):
    X = df[FEATURES].astype(float).replace([np.inf, -np.inf], np.nan)
    X = X.fillna(X.median())
    Xs = StandardScaler().fit_transform(X)
    Xq = QuantileTransformer(
        n_quantiles=500, output_distribution="normal", random_state=0
    ).fit_transform(X)
    s = {
        "iforest": -IsolationForest(
            n_estimators=200, max_samples=2048, random_state=seed, n_jobs=-1
        )
        .fit(Xs)
        .score_samples(Xs),
        "copod": COPOD().fit(Xq).decision_function(Xq),
    }
    Xr = RobustScaler().fit_transform(X)
    s["maha"] = (
        (Xr - np.median(Xr, 0)) ** 2 / (np.median(np.abs(Xr - np.median(Xr, 0)), 0) + 1e-6) ** 2
    ).sum(1)
    flags = pd.DataFrame({k: v >= np.quantile(v, 0.995) for k, v in s.items()})
    return flags, X


flags_m, Xm = real_flags(main)
cons_m = flags_m.sum(axis=1) >= 2
prof = pd.DataFrame({"consensus alerts": Xm[cons_m].mean(), "all other rows": Xm[~cons_m].mean()})
prof["ratio"] = prof["consensus alerts"] / prof["all other rows"].replace(0, np.nan)
print(
    f"{cons_m.sum():,} consensus alerts ({cons_m.mean():.2%}); pairwise overlap of the 3 detectors: "
    f"{(flags_m.iforest & flags_m.copod).sum():,} (IF∩COPOD), {(flags_m.iforest & flags_m.maha).sum():,} (IF∩Maha), {(flags_m.copod & flags_m.maha).sum():,} (COPOD∩Maha)"
)
prof.sort_values("ratio", ascending=False).style.format("{:,.2f}")

# %% [markdown]
# **Interpretation.** 972 rows (0.32 %) are flagged by at least two of three detectors. They are **bursts of activity** — a transaction already in the previous 24 h is ≈ 19× more common (`n_last_24h` 0.69 vs 0.04) — that are **declined, pending or reversed** (`status_code` ×13), often in a **foreign country** (×9) and more often on weekends.
# That is a recognisable *card-testing* signature (rapid attempts, failures, foreign location) in the genuine data, and it comes from rare discrete states rather than from amounts. Remember (notebook 08/09) that none of this is related to `is_fraud`.

# %%
backup = load_or_build(con, "b", n=300_000, seed=1)
flags_b, Xbk = real_flags(backup)
cons_b = flags_b.sum(axis=1) >= 2
prof_b = pd.DataFrame(
    {"main": prof["ratio"], "backup": (Xbk[cons_b].mean() / Xbk[~cons_b].mean().replace(0, np.nan))}
)
rho = stats.spearmanr(prof_b.main.fillna(0), prof_b.backup.fillna(0))[0]
fig = go.Figure()
fig.add_bar(x=prof_b.index, y=prof_b.main, name="main", marker_color=theme.MAIN_C)
fig.add_bar(x=prof_b.index, y=prof_b.backup, name="backup", marker_color=theme.BACKUP_C)
fig.add_hline(y=1, line_dash="dot", line_color="#8a8984")
fig.update_layout(
    barmode="group",
    height=380,
    bargap=0.3,
    title=f"Profile of consensus alerts (feature mean ÷ rest): main vs backup — Spearman ρ = {rho:.2f}",
    yaxis_type="log",
    yaxis_title="ratio (log)",
    xaxis_tickangle=-35,
)
fig.show()

# %% [markdown]
# **Interpretation.** The *kind* of row that detectors single out is **the same in both folders** (Spearman ρ = 0.94 between the two feature profiles), although the individual rows differ (independent draws, notebook 06). Findings about the **structure** of anomalies therefore replicate; findings about specific days or records (notebook 07 §3) do not.

# %% [markdown]
# ## 6 · Do ML alerts coincide with the integrity rules of notebook 07?
# If integrity defects (e.g. Approved without a response code) were also behavioural anomalies, consensus alerts would be enriched in them. We test two such rules.

# %%
ids = main.loc[cons_m, "transaction_id"]
con.register("alerts", pd.DataFrame({"transaction_id": ids.values}))
enr = con.sql("""
    with t as (select transaction_id, (transaction_status = 'Approved' and response_code is null) r03,
                      (channel = 'Branch' and branch_id is null) r10, (currency <> 'USD' and amount_usd is null) r18,
                      (transaction_id in (select transaction_id from alerts)) is_alert
               from m_transactions)
    select is_alert, count(*) n, round(100*avg(r03::int),2) r03_pct, round(100*avg(r10::int),2) r10_pct, round(100*avg(r18::int),2) r18_pct from t group by 1 order by 1""").df()
enr

# %% [markdown]
# **Interpretation.** The consensus alerts show **no enrichment** in integrity defects — if anything fewer (R03 2.9 % vs 4.6 %, R10 and R18 0 %), simply because alerts are dominated by non-approved statuses, where "Approved without response code" cannot occur. **Data-integrity defects and behavioural anomalies are independent**
# in this dataset, so a bank would need *two* controls — a data-quality gate (notebook 07 §1) and a behavioural monitor (this notebook): neither catches the other's problems.

# %% [markdown]
# ## Interactive explorer — compare any two methods
# *(Needs a live kernel.)*

# %%
d1 = w.Dropdown(
    options=methods + ["ENSEMBLE greedy"], value="Isolation Forest", description="method A"
)
d2 = w.Dropdown(options=methods + ["ENSEMBLE greedy"], value="COPOD", description="method B")
sl = w.IntSlider(
    value=1000, min=200, max=5000, step=200, description="top-k", layout=w.Layout(width="520px")
)
out_w = w.Output()


def draw(_=None):
    out_w.clear_output(wait=True)
    A, B = allc[d1.value], allc[d2.value]
    ta, tb_ = set(np.argsort(-A)[: sl.value]), set(np.argsort(-B)[: sl.value])
    both, only_a, only_b = ta & tb_, ta - tb_, tb_ - ta

    def prec(sx):
        return float(np.mean([y[i] for i in sx])) if sx else np.nan

    with out_w:
        f = go.Figure(
            go.Bar(
                x=["only A", "both", "only B"],
                y=[prec(only_a), prec(both), prec(only_b)],
                marker_color=[theme.BLUE, "#8a8984", theme.ORANGE],
                text=[len(only_a), len(both), len(only_b)],
                textposition="outside",
            )
        )
        f.update_layout(
            height=340,
            yaxis_title="precision (share truly injected)",
            yaxis_range=[0, 1.1],
            title=f"Top-{sl.value:,}: alerts unique to A ({len(only_a):,}), shared ({len(both):,}), unique to B ({len(only_b):,})",
        )
        display(f)


for ww in (d1, d2, sl):
    ww.observe(draw, "value")
draw()
display(w.VBox([d1, d2, sl, out_w]))

# %% [markdown]
# ## Findings
# 1. **Agreement is moderate** and structured by family; a single method is never enough.
# 2. A small, diverse **ensemble** (marginal + distance + isolation) beats the best single detector by ≈ 0.09 AP (0.77 vs 0.69), whereas averaging all 13 collapses to 0.26; but it cannot recover a class every member misses (`dormant_reactivation`).
# 3. The **univariate classical screen** is a strong, fully explainable baseline for point anomalies but cannot see combinations.
# 4. In the real data, consensus alerts are **bursts of declined, foreign transactions** (card-testing-like) — not related to `is_fraud` nor to data-integrity defects.
# 5. The **kind** of anomaly found replicates across folders (profile ρ = 0.94); **specific records and days do not**.
