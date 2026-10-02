# %% [markdown]
# # 09 · Anomaly detection — deep learning and supervised references
# **CRISP-DM phases 4–5** · two questions that the classical and tree/density detectors of notebooks 07–08 cannot answer:
#
# 1. **Do neural reconstruction models (autoencoder, variational autoencoder) see anomalies that shallow methods miss?** — judged on the same injected benchmark.
# 2. **What is the ceiling?** A *supervised* model with access to labels gives an upper bound, and on the real `is_fraud` label it exposes a **label-leakage** problem
#    (`fraud_score`) that every fraud analysis on this dataset must handle.
#
# | model | what it learns | anomaly score |
# |---|---|---|
# | Autoencoder (AE) | compress to 6 dims and reconstruct | per-row reconstruction error |
# | Variational AE (VAE) | a Gaussian latent density | reconstruction error + KL (negative ELBO) |
# | Gradient boosting (supervised) | `label ~ features` | probability |

# %%
import sys
import time
import warnings

sys.path.insert(0, "../src")
warnings.filterwarnings("ignore")
import numpy as np
import pandas as pd
import plotly.graph_objects as go
import shap
import torch
import torch.nn as nn
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.metrics import average_precision_score, roc_auc_score
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import QuantileTransformer

from latam_eda import theme
from latam_eda.anomaly import (
    FEATURES,
    INJECTED,
    inject_anomalies,
    load_or_build,
    load_or_build_enriched,
)
from latam_eda.data import DERIVED, ROOT, connect

theme.register()
con = connect()
OUT = ROOT / "reports" / "tables"
SEED = 7
torch.manual_seed(SEED)
np.random.seed(SEED)
device = "mps" if torch.backends.mps.is_available() else "cpu"
print("device:", device)

# %% [markdown]
# ## 1 · Same benchmark as notebook 08
# The injection seed and the evaluation rows are re-derived exactly as in notebook 08, so scores are directly comparable (and we verify the evaluation rows match).

# %%
main = load_or_build(con, "m", n=300_000, seed=1)
bench = inject_anomalies(main, rate=0.01, seed=SEED)
X = bench[FEATURES].astype(float).replace([np.inf, -np.inf], np.nan)
X = X.fillna(X.median())
y, typ = bench.is_injected.values, bench.anomaly_type.values
rng = np.random.default_rng(SEED)
ev = rng.choice(len(bench), 100_000, replace=False)
Xq = (
    QuantileTransformer(n_quantiles=500, output_distribution="normal", random_state=0)
    .fit_transform(X)
    .astype(np.float32)
)
prev = pd.read_parquet(DERIVED / "bench_scores_main.parquet")
assert (prev.transaction_id.values == bench.iloc[ev].transaction_id.values).all(), (
    "evaluation rows differ from notebook 08"
)
print(
    f"{len(bench):,} rows • {y.sum():,} injected • evaluation rows verified identical to notebook 08"
)

# %% [markdown]
# ## 2 · Autoencoder and VAE
# Both are trained **without labels on the contaminated table** (the realistic setting). The AE uses a 14→32→6→32→14 MLP; the VAE the same width with a 6-d Gaussian latent.
# Because anomalies are only 1 % of the rows, the network mostly learns the normal structure and reconstructs anomalies poorly.


# %%
class AE(nn.Module):
    def __init__(self, d, h=32, z=6, vae=False):
        super().__init__()
        self.vae = vae
        self.enc = nn.Sequential(nn.Linear(d, h), nn.ReLU(), nn.Linear(h, h), nn.ReLU())
        self.mu = nn.Linear(h, z)
        self.lv = nn.Linear(h, z) if vae else None
        self.dec = nn.Sequential(
            nn.Linear(z, h), nn.ReLU(), nn.Linear(h, h), nn.ReLU(), nn.Linear(h, d)
        )

    def forward(self, x):
        h = self.enc(x)
        mu = self.mu(h)
        if self.vae:
            lv = self.lv(h).clamp(-8, 4)
            z = mu + torch.randn_like(mu) * torch.exp(0.5 * lv) if self.training else mu
            return self.dec(z), mu, lv
        return self.dec(mu), mu, None


def train(model, X, epochs=25, bs=1024, lr=2e-3, beta=0.5):
    model.to(device)
    opt = torch.optim.Adam(model.parameters(), lr=lr)
    Xt = torch.from_numpy(X)
    hist = []
    for ep in range(epochs):
        model.train()
        perm = torch.randperm(len(Xt))
        tot = 0
        for i in range(0, len(Xt), bs):
            b = Xt[perm[i : i + bs]].to(device)
            rec, mu, lv = model(b)
            loss = ((rec - b) ** 2).sum(1).mean()
            if model.vae:
                loss = loss + beta * (-0.5 * (1 + lv - mu**2 - lv.exp()).sum(1)).mean()
            opt.zero_grad()
            loss.backward()
            opt.step()
            tot += loss.item() * len(b)
        hist.append(tot / len(Xt))
    return hist


@torch.no_grad()
def score(model, X, per_feature=False):
    model.eval()
    xt = torch.from_numpy(X).to(device)
    rec, mu, lv = model(xt)
    err = ((rec - xt) ** 2).cpu().numpy()
    if per_feature:
        return err
    s = err.sum(1)
    if model.vae:
        s = s + 0.5 * (-0.5 * (1 + lv - mu**2 - lv.exp()).sum(1)).cpu().numpy()
    return s


t0 = time.time()
ae = AE(Xq.shape[1])
h_ae = train(ae, Xq)
vae = AE(Xq.shape[1], vae=True)
h_vae = train(vae, Xq)
print(f"trained both in {time.time() - t0:.0f}s on {device}")
fig = go.Figure()
fig.add_scatter(y=h_ae, name="AE loss", line=dict(color=theme.BLUE, width=2))
fig.add_scatter(y=h_vae, name="VAE loss (rec + 0.5·KL)", line=dict(color=theme.ORANGE, width=2))
fig.update_layout(height=320, title="Training curves", xaxis_title="epoch", yaxis_title="loss")
fig.show()

# %% [markdown]
# ## 3 · Accuracy vs the shallow detectors

# %%
scores = {"Autoencoder": score(ae, Xq[ev]), "VAE (neg. ELBO)": score(vae, Xq[ev])}
yev, tev = y[ev], typ[ev]


def metrics(s):
    k = int(yev.sum())
    top = np.argsort(-s)[:k]
    return dict(
        AUC=roc_auc_score(yev, s),
        AP=average_precision_score(yev, s),
        precision_at_k=yev[top].mean(),
    )


deep = pd.DataFrame({m: metrics(s) for m, s in scores.items()}).T
shallow = pd.read_csv(OUT / "ml_detector_benchmark.csv", index_col=0)[
    ["AUC", "AP", "precision_at_k"]
]
allm = pd.concat([deep, shallow]).sort_values("AP", ascending=False)
allm["family"] = ["deep" if m in scores else "shallow" for m in allm.index]
allm.to_csv(OUT / "deep_vs_shallow.csv")
allm.style.format(
    {"AUC": "{:.3f}", "AP": "{:.3f}", "precision_at_k": "{:.3f}"}
).background_gradient(subset=["AP"], cmap="Blues")

# %%
r = allm.sort_values("AP")
fig = go.Figure(
    go.Bar(
        y=r.index,
        x=r.AP,
        orientation="h",
        marker_color=[theme.ORANGE if f == "deep" else theme.BLUE for f in r.family],
    )
)
fig.add_vline(x=yev.mean(), line_dash="dot", line_color="#8a8984")
fig.update_layout(
    height=430,
    margin=dict(l=170),
    title="Average precision: deep (orange) vs shallow (blue) detectors",
    xaxis_title="average precision",
)
fig.show()

# %% [markdown]
# **Interpretation.** Neural detectors are **mid-pack, not winners**: the VAE reaches AUC 0.964 (3rd best) but AP 0.451 (8th of 12), the plain AE AP 0.328 — below COPOD (0.671), robust Mahalanobis (0.635) and Isolation Forest (0.626).
# On 14 tabular features the extra capacity buys no accuracy; the VAE's density-aware score is clearly better than the plain AE's raw reconstruction error (+0.12 AP). What the networks *do* add is a **per-feature explanation** of each alert (next section).

# %% [markdown]
# ## 4 · Explaining alerts: which feature drives the reconstruction error?
# For the top-1 % AE alerts of each anomaly type, the share of the squared error contributed by each feature. This should recover the *mechanism* we injected.

# %%
err = score(ae, Xq[ev], per_feature=True)
top = np.argsort(-err.sum(1))[: int(0.01 * len(ev))]
contrib = {}
for t in INJECTED:
    sel = top[tev[top] == t]
    contrib[t] = (
        (err[sel] / err[sel].sum(1, keepdims=True)).mean(0) if len(sel) else np.zeros(len(FEATURES))
    )
cdf = pd.DataFrame(contrib, index=FEATURES).T
fig = go.Figure(
    go.Heatmap(
        z=cdf.values * 100,
        x=FEATURES,
        y=cdf.index,
        text=np.round(cdf.values * 100).astype(int),
        texttemplate="%{text}",
        colorscale=[[0, "#f0efec"], [0.5, "#3987e5"], [1, "#0d366b"]],
        colorbar=dict(title="% of error"),
    )
)
fig.update_layout(
    height=360,
    title="Share of AE reconstruction error by feature, per injected anomaly type (top-1 % alerts)",
    xaxis_tickangle=-35,
)
fig.show()
cdf.round(2).to_csv(OUT / "ae_error_attribution.csv")
cdf.round(2).style.format("{:.0%}").background_gradient(cmap="Blues", axis=None)
print("alerts per type in the top 1 %:", {t: int((tev[top] == t).sum()) for t in INJECTED})
cdf.round(2).T.sort_values(INJECTED[0], ascending=False).head(14)

# %% [markdown]
# **Interpretation.** The attribution recovers the injected mechanisms: `amount_spike` → `ratio_to_cust_median` (40 %) and `log_usd` (15 %); `velocity_burst` → `n_last_24h` (33 %) and `log_gap_prev` (14 %); `dormant_reactivation` → `log_gap_prev` (32 %), `n_last_24h` (17 %), `log_usd` (13 %).
# It also exposes a **learned dependency**: for `foreign_burst` and `low_and_slow` the top contributors are `country_mismatch` (30 %) *and* `currency_code` (26–28 %) — in the real data a foreign-country transaction is almost always USD-denominated, so injected foreign rows that keep a
# local currency **break a relationship the network learned**. That is exactly the kind of insight a reconstruction model gives and a marginal detector cannot. The AE finds very few `dormant_reactivation` alerts (2 of the top 1 %), consistent with notebook 08's finding.

# %% [markdown]
# ## 5 · Supervised ceiling on the injected benchmark
# A gradient-boosting classifier trained **with** labels on half of the rows and scored on the other half. This is what perfect labelling would buy; the gap to the unsupervised methods is the
# *price of not having labels*.

# %%
idx = np.arange(len(bench))
tr, te = train_test_split(idx, test_size=0.4, stratify=y, random_state=SEED)
gb = HistGradientBoostingClassifier(max_iter=200, learning_rate=0.1, random_state=SEED).fit(
    X.iloc[tr], y[tr]
)
p = gb.predict_proba(X.iloc[te])[:, 1]
sup = dict(AUC=roc_auc_score(y[te], p), AP=average_precision_score(y[te], p))
print(
    f"supervised ceiling on injected anomalies: AUC {sup['AUC']:.3f}, AP {sup['AP']:.3f}  (best unsupervised AP: {allm.AP.iloc[0]:.3f}, {allm.index[0]})"
)

# %% [markdown]
# ## 6 · The real label: `is_fraud` and the `fraud_score` leakage
# `fraud_score` (0–100) ships with each transaction. We quantify how much of `is_fraud` it explains, and what a supervised model learns with and without it.

# %%
lk = con.sql("""select case when fraud_score is null then '4 null' when fraud_score < 30 then '1 under 30' when fraud_score < 35 then '2 30 to 35' when fraud_score < 40 then '3 35 to 40' else '5 40 and above' end band,
                       count(*) n, sum(is_fraud::int) fraud, round(100.0 * sum(is_fraud::int) / count(*), 3) fraud_rate_pct
                from m_transactions group by 1 order by 1""").df()
tot_fraud = lk.fraud.sum()
lk["share_of_all_fraud_%"] = 100 * lk.fraud / tot_fraud
lk.style.format(
    {
        "n": "{:,.0f}",
        "fraud": "{:,.0f}",
        "fraud_rate_pct": "{:.3f}",
        "share_of_all_fraud_%": "{:.1f}",
    }
)

# %%
# Fraud is 0.1 % of rows, so a plain sample holds ~300 positives. For supervised models we keep EVERY fraud row (4,316) plus 300k non-fraud rows.
real = load_or_build_enriched(con, "m", n=300_000, seed=1)
Xr = real[FEATURES + ["fraud_score"]].astype(float).replace([np.inf, -np.inf], np.nan)
yr = real.is_fraud.astype(int).values
print(
    f"enriched sample: {len(real):,} rows, {yr.sum():,} fraud ({yr.mean():.2%}) — prevalence is ~14× the real 0.098 %, so read AP relative to it"
)
tr2, te2 = train_test_split(np.arange(len(real)), test_size=0.3, stratify=yr, random_state=SEED)
res = {}
for name, cols in (
    ("features only", FEATURES),
    ("features + fraud_score", FEATURES + ["fraud_score"]),
    ("fraud_score only", ["fraud_score"]),
):
    m = HistGradientBoostingClassifier(
        max_iter=150,
        learning_rate=0.1,
        max_depth=4,
        early_stopping=False,
        class_weight="balanced",
        random_state=SEED,
    ).fit(Xr.iloc[tr2][cols], yr[tr2])
    pr = m.predict_proba(Xr.iloc[te2][cols])[:, 1]
    k = int(yr[te2].sum())
    res[name] = dict(
        AUC=roc_auc_score(yr[te2], pr),
        AP=average_precision_score(yr[te2], pr),
        precision_at_k=yr[te2][np.argsort(-pr)[:k]].mean(),
    )
    if name == "features + fraud_score":
        model_leak, cols_leak = m, cols
real_res = pd.DataFrame(res).T
real_res.loc["(random)", "AP"] = yr[te2].mean()
real_res.to_csv(OUT / "fraud_label_leakage.csv")
real_res.style.format("{:.3f}")

# %% [markdown]
# **Interpretation.** The leakage is stark: `fraud_score ≥ 35` ⇒ **100 %** fraud (2,198 transactions = **51 % of all fraud**), 30–35 ⇒ 22 %, while below 30 the fraud rate is ≈ 0.03 % and where the score is null ≈ 0.10 % — **≈ 45 % of all fraud (1,943 cases) sits where
# the score is low or missing**, and is therefore unreachable by score. Models agree: **features only → AUC 0.513, AP 0.0147 vs prevalence 0.0139 (chance)**; adding `fraud_score` → AUC 0.82, AP 0.565 (≈ 41× prevalence); `fraud_score` alone does just as well (0.82 / 0.548). Amount, time,
# channel, geography and velocity carry **no information** about `is_fraud`. Practical rules: never evaluate "behavioural" fraud models against `is_fraud` without removing `fraud_score`, and expect ≈ 45 % of the positives to be unfindable by score *or* behaviour.

# %%
bg = Xr.iloc[tr2][cols_leak].sample(100, random_state=0)
sv = shap.Explainer(
    lambda d: model_leak.predict_proba(pd.DataFrame(d, columns=cols_leak))[:, 1],
    bg,
    algorithm="permutation",
)  # model-agnostic: tree additivity check fails for HistGB + class weights
sample = Xr.iloc[te2][cols_leak].sample(400, random_state=1)
vals = sv(sample, max_evals=2 * len(cols_leak) + 1)
imp = pd.Series(np.abs(vals.values).mean(0), index=cols_leak).sort_values()
fig = go.Figure(
    go.Bar(
        y=imp.index,
        x=imp.values,
        orientation="h",
        marker_color=[theme.ORANGE if i == "fraud_score" else theme.BLUE for i in imp.index],
    )
)
fig.update_layout(
    height=420,
    margin=dict(l=170),
    title="SHAP: mean |contribution| to P(is_fraud) — one feature does all the work",
    xaxis_title="mean |SHAP|",
)
fig.show()

# %% [markdown]
# SHAP (model-agnostic permutation explainer, 400 test rows) confirms it from the model's own point of view: `fraud_score` carries essentially all the attribution; the 14 behavioural features are noise to the classifier.

# %% [markdown]
# ## 7 · Cost-based view
# A bank cares about money, not AUC. Assume missing a fraud costs **100** and reviewing an alert costs **1**. For each score, the review budget *k* that minimises total cost, evaluated on the injected benchmark.


# %%
def best_cost(s, yv, c_fn=100, c_fp=1):
    order = np.argsort(-s)
    hit = yv[order]
    tp = np.cumsum(hit)
    fp = np.cumsum(1 - hit)
    fn = hit.sum() - tp
    cost = c_fn * fn + c_fp * fp
    j = int(cost.argmin())
    return dict(
        best_k=j + 1,
        cost=float(cost[j]),
        recall=float(tp[j] / hit.sum()),
        precision=float(tp[j] / (j + 1)),
    )


costs = {m: best_cost(s, yev) for m, s in scores.items()}
for m in shallow.index[:4]:
    costs[m] = best_cost(prev[m].values, yev)
costs["(review nothing)"] = dict(best_k=0, cost=100.0 * yev.sum(), recall=0.0, precision=np.nan)
cdf2 = pd.DataFrame(costs).T.sort_values("cost")
cdf2.to_csv(OUT / "cost_based_comparison.csv")
cdf2.style.format(
    {"best_k": "{:,.0f}", "cost": "{:,.0f}", "recall": "{:.2f}", "precision": "{:.2f}"}
)

# %% [markdown]
# **Interpretation.** With a miss costing 100× an alert, the optimum is to **review a lot**: the VAE's best budget is ≈ 10,000 alerts (10 % of rows) for 92 % recall at total cost 17.5 k, kNN 10.2 k alerts / 91 % / 18.8 k, versus **100.9 k if nothing is reviewed**. COPOD reaches 80 % recall with only 2.5 k alerts
# (precision 0.32) at cost 21.8 k. The ranking by *cost* differs from the ranking by *AP* — it depends on the cost ratio, so the metric must be chosen with the business, not with the data scientist.

# %% [markdown]
# ## 8 · Save for the comparison notebook

# %%
out = prev[["transaction_id", "anomaly_type", "is_injected"]].copy()
for m, s in scores.items():
    out[m] = s
out.to_parquet(DERIVED / "bench_scores_deep.parquet")
print("saved", out.shape)

# %% [markdown]
# ## Findings
# 1. **Deep detectors** (AE/VAE) are mid-pack on AP (0.33 / 0.45 vs COPOD 0.67); their value is **per-feature explanation** and detection of broken learned dependencies, not accuracy.
# 2. A **supervised ceiling** (AP 0.997 on injected anomalies) quantifies the cost of having no labels: ≈ 0.33 AP.
# 3. **`fraud_score` is the label**: ≥ 35 ⇒ 100 % fraud (51 % of fraud); remove it and nothing predicts `is_fraud` (AUC 0.51); ≈ 45 % of positives sit at low/null score.
# 4. A **cost-based** view (§7) is the right way to choose a review budget; the best detector changes with the cost ratio.
