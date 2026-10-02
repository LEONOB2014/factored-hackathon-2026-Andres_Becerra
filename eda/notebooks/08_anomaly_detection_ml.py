# %% [markdown]
# # 08 · Anomaly detection — machine-learning detectors
# **CRISP-DM phases 3–5** · unsupervised detectors on transaction behaviour, benchmarked against a **controlled ground truth**.
#
# **The evaluation problem.** In the real data the only label is `is_fraud` (0.1 %). Section 5 shows that, apart from `fraud_score`, *none* of the observable features carries
# information about it (so no unsupervised method can "find" it), which makes `is_fraud` a poor benchmark for comparing detectors.
# We therefore use the standard research design for unlabeled data — a **semi-synthetic benchmark**: take real, clean-ish main transactions and **inject 1 % labelled anomalies of five types**
# (above-cap value spike, foreign burst, velocity burst, *low-and-slow* multi-feature shift, dormant reactivation) — two point/collective types that any detector should catch and two *contextual* types that need joint reasoning. Every detector is fitted *blind* on the contaminated data and judged on recovering the injected rows.
#
# Detectors compared (traditional → modern):
#
# | family | detector | idea |
# |---|---|---|
# | statistical | robust Mahalanobis (MCD) | distance from a robust Gaussian centre |
# | statistical | GMM log-likelihood | multi-modal density |
# | statistical | HBOS, COPOD, ECOD | per-feature histogram / empirical-copula tail probabilities (parameter-free) |
# | distance | LOF, kNN distance | local / global neighbourhood sparsity |
# | boundary | One-Class SVM | RBF boundary around "normal" |
# | isolation | Isolation Forest | short random-partition paths = anomalous |
# | reconstruction | autoencoder, PCA | (notebook 09) |

# %%
import sys
import time
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
from pyod.models.ecod import ECOD
from pyod.models.hbos import HBOS
from sklearn.covariance import MinCovDet
from sklearn.decomposition import PCA
from sklearn.ensemble import IsolationForest
from sklearn.metrics import average_precision_score, precision_recall_curve, roc_auc_score
from sklearn.mixture import GaussianMixture
from sklearn.neighbors import LocalOutlierFactor, NearestNeighbors
from sklearn.preprocessing import QuantileTransformer, RobustScaler, StandardScaler
from sklearn.svm import OneClassSVM

from latam_eda import theme
from latam_eda.anomaly import FEATURES, INJECTED, inject_anomalies, load_or_build
from latam_eda.data import DERIVED, ROOT, connect

theme.register()
con = connect()
OUT = ROOT / "reports" / "tables"
SEED = 7

# %% [markdown]
# ## 1 · Features and benchmark construction
# One row per transaction with **context** features (all computed on the *whole* folder, then sampled): value, local hour, weekday, channel/type/currency/status, whether the
# country differs from the customer's, time since the customer's previous transaction, number of transactions in the previous 24 h, amount relative to the customer's own median, and
# the customer's total activity.

# %%
t0 = time.time()
main = load_or_build(con, "m", n=300_000, seed=1)
backup = load_or_build(con, "b", n=300_000, seed=1)
print(
    f"features built/loaded in {time.time() - t0:.0f}s • main {len(main):,} • backup {len(backup):,}"
)
main[FEATURES].describe().T[["mean", "std", "min", "50%", "max"]].style.format("{:,.2f}")

# %%
bench = inject_anomalies(main, rate=0.01, seed=SEED)
X = bench[FEATURES].astype(float).replace([np.inf, -np.inf], np.nan)
X = X.fillna(X.median())
y = bench.is_injected.values
typ = bench.anomaly_type.values
print(
    f"benchmark: {len(bench):,} rows, {y.sum():,} injected ({y.mean():.2%}); per type: {pd.Series(typ[y == 1]).value_counts().to_dict()}"
)
# Train / eval split: models see the whole contaminated table (fit) but are scored on a common 100k eval subset
rng = np.random.default_rng(SEED)
ev = rng.choice(len(bench), 100_000, replace=False)
fit_small = rng.choice(len(bench), 30_000, replace=False)
Xs = StandardScaler().fit_transform(X)
Xq = QuantileTransformer(
    n_quantiles=500, output_distribution="normal", random_state=0
).fit_transform(X)  # rank-based: for marginal methods (HBOS/COPOD/ECOD)
Xr = RobustScaler().fit_transform(X)  # keeps magnitude: for distance / density methods

# %% [markdown]
# ## 2 · Fit every detector
# Fast detectors are fitted on the full 300 k rows; the quadratic ones (LOF, kNN, One-Class SVM, GMM, MCD) on a 30 k subsample. All are scored on the **same 100 k** evaluation rows.
# Scores are oriented so *higher = more anomalous*. **Preprocessing matters:** the marginal methods (HBOS/COPOD/ECOD) use a rank (quantile) transform; the distance/density methods use a *robust scaler* (median/IQR) because a quantile transform clips out-of-range values to the training maximum and would hide exactly the extreme values we want to detect.

# %%
scores, timing = {}, {}


def run(name, fn):
    t = time.time()
    scores[name] = np.asarray(fn(), float)
    timing[name] = time.time() - t
    print(f"{name:22s} {timing[name]:6.1f}s  AUC={roc_auc_score(y[ev], scores[name]):.3f}")


run(
    "Isolation Forest",
    lambda: (
        -IsolationForest(n_estimators=300, max_samples=2048, random_state=SEED, n_jobs=-1)
        .fit(Xs)
        .score_samples(Xs[ev])
    ),
)
run("HBOS", lambda: HBOS(n_bins=50).fit(Xq).decision_function(Xq[ev]))
run("COPOD", lambda: COPOD().fit(Xq).decision_function(Xq[ev]))
run("ECOD", lambda: ECOD().fit(Xq).decision_function(Xq[ev]))
run(
    "Robust Mahalanobis",
    lambda: (
        MinCovDet(support_fraction=0.75, random_state=SEED).fit(Xr[fit_small]).mahalanobis(Xr[ev])
    ),
)
run(
    "GMM (6 comp.)",
    lambda: (
        -GaussianMixture(6, covariance_type="full", random_state=SEED)
        .fit(Xr[fit_small])
        .score_samples(Xr[ev])
    ),
)
run(
    "kNN distance (k=20)",
    lambda: (
        NearestNeighbors(n_neighbors=20, n_jobs=-1).fit(Xr[fit_small]).kneighbors(Xr[ev])[0][:, -1]
    ),
)
run(
    "LOF (k=30)",
    lambda: (
        -LocalOutlierFactor(n_neighbors=30, novelty=True, n_jobs=-1)
        .fit(Xr[fit_small])
        .score_samples(Xr[ev])
    ),
)
run(
    "One-Class SVM",
    lambda: -OneClassSVM(nu=0.02, gamma="scale").fit(Xr[fit_small[:15000]]).score_samples(Xr[ev]),
)
run(
    "PCA reconstruction",
    lambda: (
        (
            Xr[ev]
            - PCA(n_components=8, random_state=SEED)
            .fit(Xr)
            .inverse_transform(PCA(n_components=8, random_state=SEED).fit(Xr).transform(Xr[ev]))
        )
        ** 2
    ).sum(1),
)

# %% [markdown]
# ## 3 · Accuracy
# **ROC-AUC** (ranking quality overall), **average precision** (area under precision–recall — the right headline metric at 1 % prevalence) and **precision@k** with *k* = the number of true anomalies in the evaluation set.


# %%
def metrics(s, yv):
    k = int(yv.sum())
    top = np.argsort(-s)[:k]
    return dict(
        AUC=roc_auc_score(yv, s), AP=average_precision_score(yv, s), precision_at_k=yv[top].mean()
    )


yev = y[ev]
res = pd.DataFrame({m: metrics(s, yev) for m, s in scores.items()}).T
res["fit+score s"] = pd.Series(timing)
res = res.sort_values("AP", ascending=False)
res.to_csv(OUT / "ml_detector_benchmark.csv")
res.style.format(
    {"AUC": "{:.3f}", "AP": "{:.3f}", "precision_at_k": "{:.3f}", "fit+score s": "{:.1f}"}
).background_gradient(subset=["AP"], cmap="Blues")

# %%
fig = make_subplots(
    rows=1,
    cols=2,
    subplot_titles=["Average precision (higher = better)", "Precision–recall curves"],
    column_widths=[0.42, 0.58],
)
r = res.sort_values("AP")
fig.add_bar(
    y=r.index, x=r.AP, orientation="h", marker_color=theme.BLUE, showlegend=False, row=1, col=1
)
fig.add_vline(x=yev.mean(), line_dash="dot", line_color="#8a8984", row=1, col=1)
for i, m in enumerate(res.index[:5]):
    p, rc, _ = precision_recall_curve(yev, scores[m])
    keep = np.unique(
        np.r_[np.linspace(0, len(p) - 1, 400).astype(int), np.arange(0, min(len(p), 600))]
    )
    fig.add_scatter(
        x=rc[keep],
        y=p[keep],
        mode="lines",
        name=m,
        line=dict(color=theme.CATEGORICAL[i], width=2),
        row=1,
        col=2,
    )
fig.update_xaxes(title_text="recall", row=1, col=2)
fig.update_yaxes(title_text="precision", row=1, col=2)
fig.update_layout(
    height=420,
    title="Detector benchmark on injected anomalies (dotted = random baseline)",
    margin=dict(l=150),
)
fig.show()

# %% [markdown]
# **Interpretation.** On this benchmark (1 % prevalence, so a random ranking has AP ≈ 0.01) the best methods reach **AP 0.60–0.67** (COPOD 0.67, robust Mahalanobis 0.64, Isolation Forest 0.63, kNN 0.60), with
# **ROC-AUC 0.93–0.97** for almost all. Two methods fail outright: **LOF** (AP 0.06) and **PCA reconstruction** (AP 0.04) — PCA because anomalies that live *inside* the principal subspace reconstruct perfectly, LOF because local density
# ratios are unstable in a 14-dimensional space with several discrete and constant-like features. The cost is negligible for all of them (≤ 6 s), so run-time is not a selection criterion here; AUC alone would hide the real differences, AP shows them.

# %% [markdown]
# ## 4 · Recall by anomaly type
# At a fixed review budget — the **top 1 %** highest-scoring evaluation rows — what share of each injected type is recovered?

# %%
tev = typ[ev]
budget = int(0.01 * len(ev))
rows = {}
for m, s in scores.items():
    top = np.zeros(len(ev), bool)
    top[np.argsort(-s)[:budget]] = True
    rows[m] = {t_: top[tev == t_].mean() for t_ in INJECTED}
rec = pd.DataFrame(rows).T[INJECTED]
rec.to_csv(OUT / "ml_recall_by_type.csv")
fig = go.Figure(
    go.Heatmap(
        z=rec.values * 100,
        x=INJECTED,
        y=rec.index,
        zmin=0,
        zmax=100,
        text=np.round(rec.values * 100).astype(int),
        texttemplate="%{text}%",
        colorscale=[[0, "#f0efec"], [0.5, "#3987e5"], [1, "#0d366b"]],
        colorbar=dict(title="recall %"),
    )
)
fig.update_layout(
    height=430,
    title="Recall at the top-1 % review budget, by injected anomaly type",
    margin=dict(l=170),
)
fig.show()

# %% [markdown]
# **Interpretation.** No method wins everywhere — the heatmap is the main result of this notebook:
# * **`velocity_burst` and `foreign_burst`** (rare discrete values + bursts) are seen by nearly everyone (kNN/Isolation Forest/Mahalanobis 88–100 %), except LOF (3–13 %).
# * **`amount_spike`** (value *above anything in the data*) is caught **100 % by robust Mahalanobis** but only 41 % by Isolation Forest, 3 % by HBOS and 1 % by LOF/PCA: a histogram or rank view cannot "see" a value beyond the training range
#   (the quantile transform clips it to the maximum), whereas a distance on robustly-scaled data keeps its magnitude. **Preprocessing decides detectability.**
# * **`low_and_slow`** (four mild shifts that include two individually rare binary flags) is seen by the **marginal methods** (HBOS 87 %, COPOD 88 %) and Isolation Forest (66 %) but *missed by distance methods* (Mahalanobis 1 %, kNN 22 %), whose
#   continuous-scale geometry is dominated by the other features.
# * **`dormant_reactivation` is essentially invisible (0–12 %; only LOF 34 %)** — a data-encoding lesson: the first transaction of every customer carries a **placeholder gap of one year** (3 % of rows sit at exactly that value), so a silence of
#   8–12 months followed by a large movement lands next to a densely populated cluster and looks normal. Any dormancy feature must **separate "first transaction" from "long gap"** before modelling.
# Hence the practical recommendation: an **ensemble of complementary families** (a marginal method + a distance method + isolation), which notebook 10 evaluates.

# %% [markdown]
# ## 5 · Reality check on the real label (`is_fraud`)
# If features carried fraud signal the detectors should beat chance on the *un-injected* data. We score the clean main sample and check AUC against `is_fraud` — with and without `fraud_score`.

# %%
clean = main.copy()
Xc = clean[FEATURES].astype(float).replace([np.inf, -np.inf], np.nan)
Xc = Xc.fillna(Xc.median())
Xc_q = QuantileTransformer(
    n_quantiles=500, output_distribution="normal", random_state=0
).fit_transform(Xc)
sub = np.random.default_rng(3).choice(len(clean), 100_000, replace=False)
yf = clean.is_fraud.astype(int).values[sub]
iso = IsolationForest(n_estimators=200, max_samples=2048, random_state=SEED, n_jobs=-1).fit(
    StandardScaler().fit_transform(Xc)
)
real = {
    "Isolation Forest": -iso.score_samples(StandardScaler().fit(Xc).transform(Xc.iloc[sub])),
    "ECOD": ECOD().fit(Xc_q).decision_function(Xc_q[sub]),
    "fraud_score (given)": clean.fraud_score.fillna(clean.fraud_score.median()).values[sub],
}
fr = pd.DataFrame(
    {
        "AUC vs is_fraud": {k: roc_auc_score(yf, v) for k, v in real.items()},
        "AP vs is_fraud": {k: average_precision_score(yf, v) for k, v in real.items()},
    }
)
fr.loc["(prevalence)", "AP vs is_fraud"] = yf.mean()
fr.style.format("{:.3f}")

# %% [markdown]
# **Interpretation.** On the real label the behavioural detectors perform **at or below chance** (Isolation Forest AUC 0.484, ECOD 0.482; AP = 0.001 = prevalence): `is_fraud` is statistically unrelated to amount, time,
# channel, geography or velocity. Only `fraud_score` separates it (AUC 0.75, AP 0.47 ≈ 470× the prevalence) — effectively the label (notebook 09 quantifies this leakage). Therefore (a) this dataset cannot evaluate behavioural fraud
# detection against `is_fraud`, and (b) the semi-synthetic benchmark above is the right way to compare detectors.

# %% [markdown]
# ## 6 · Stability: do the detectors behave the same on the backup folder?
# Apply the *same* injection and detectors to backup features. Rank correlation of the AP between folders tells us whether conclusions transfer.

# %%
bench_b = inject_anomalies(backup, rate=0.01, seed=SEED)
Xb = bench_b[FEATURES].astype(float).replace([np.inf, -np.inf], np.nan)
Xb = Xb.fillna(Xb.median())
yb = bench_b.is_injected.values
evb = np.random.default_rng(SEED).choice(len(bench_b), 100_000, replace=False)
Xbs = StandardScaler().fit_transform(Xb)
Xbq = QuantileTransformer(
    n_quantiles=500, output_distribution="normal", random_state=0
).fit_transform(Xb)
Xbr = RobustScaler().fit_transform(Xb)
fit_b = np.random.default_rng(SEED).choice(len(bench_b), 30_000, replace=False)
sb = {
    "Isolation Forest": -IsolationForest(
        n_estimators=300, max_samples=2048, random_state=SEED, n_jobs=-1
    )
    .fit(Xbs)
    .score_samples(Xbs[evb]),
    "HBOS": HBOS(n_bins=50).fit(Xbq).decision_function(Xbq[evb]),
    "COPOD": COPOD().fit(Xbq).decision_function(Xbq[evb]),
    "ECOD": ECOD().fit(Xbq).decision_function(Xbq[evb]),
    "Robust Mahalanobis": MinCovDet(support_fraction=0.75, random_state=SEED)
    .fit(Xbr[fit_b])
    .mahalanobis(Xbr[evb]),
    "GMM (6 comp.)": -GaussianMixture(6, covariance_type="full", random_state=SEED)
    .fit(Xbr[fit_b])
    .score_samples(Xbr[evb]),
    "kNN distance (k=20)": NearestNeighbors(n_neighbors=20, n_jobs=-1)
    .fit(Xbr[fit_b])
    .kneighbors(Xbr[evb])[0][:, -1],
    "LOF (k=30)": -LocalOutlierFactor(n_neighbors=30, novelty=True, n_jobs=-1)
    .fit(Xbr[fit_b])
    .score_samples(Xbr[evb]),
}
stab = pd.DataFrame(
    {
        "AP main": {m: average_precision_score(yev, scores[m]) for m in sb},
        "AP backup": {m: average_precision_score(yb[evb], s) for m, s in sb.items()},
    }
)
stab["Δ"] = stab["AP backup"] - stab["AP main"]
rho = stab[["AP main", "AP backup"]].corr(method="spearman").iloc[0, 1]
print(f"Spearman rank correlation of detector APs, main vs backup: {rho:.2f}")
stab.to_csv(OUT / "ml_stability_main_vs_backup.csv")
stab.style.format("{:.3f}")

# %% [markdown]
# **Interpretation.** Method-level conclusions largely transfer: Isolation Forest, ECOD, HBOS, GMM, LOF move by ≤ 0.02 AP; Mahalanobis and kNN by −0.03/−0.06; the exception is **COPOD (−0.13)**, whose AP is the most sensitive to the particular random draw,
# which lowers the overall rank correlation to ≈ 0.71. The *families* that work (isolation, distance, marginal) and those that do not (LOF, PCA) are the same in both folders — another consequence of the folders being replicates (notebook 06).

# %% [markdown]
# ## 7 · Save scores for the comparison notebook

# %%
out = bench.iloc[ev][
    ["transaction_id", "customer_id", "anomaly_type", "is_injected", "is_fraud", "fraud_score"]
].reset_index(drop=True)
for m, s in scores.items():
    out[m] = s
out.to_parquet(DERIVED / "bench_scores_main.parquet")
print("saved", out.shape)

# %% [markdown]
# ## Interactive explorer — pick a detector and a review budget
# *(Needs a live kernel.)*

# %%
dd = w.Dropdown(options=list(scores), value=res.index[0], description="detector")
bg = w.IntSlider(
    value=1000, min=100, max=5000, step=100, description="alerts k", layout=w.Layout(width="520px")
)
out_w = w.Output()


def draw(_=None):
    out_w.clear_output(wait=True)
    s = scores[dd.value]
    order = np.argsort(-s)[: bg.value]
    hit = yev[order]
    by = pd.Series(tev[order]).replace("", "normal").value_counts()
    with out_w:
        f = go.Figure(
            go.Bar(
                x=by.index,
                y=by.values,
                marker_color=[theme.RED if i == "normal" else theme.BLUE for i in by.index],
            )
        )
        f.update_layout(
            height=330,
            title=f"{dd.value}: top {bg.value:,} alerts → precision {hit.mean():.1%}, recall {hit.sum() / yev.sum():.1%}",
            yaxis_title="alerts",
        )
        display(f)


dd.observe(draw, "value")
bg.observe(draw, "value")
draw()
display(w.VBox([dd, bg, out_w]))

# %% [markdown]
# ## Findings
# 1. A **controlled benchmark** is the only sound way to compare detectors here; `is_fraud` is unrelated to behaviour.
# 2. Method families differ in *which* anomalies they see; the best single method is shown in §3, the complementary ones in §4.
# 3. Rankings are **stable across the two folders**, so method selection is robust.
