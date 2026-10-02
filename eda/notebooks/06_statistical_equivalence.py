# %% [markdown]
# # 06 · Are the two folders the same *process*?
# **CRISP-DM phase 4 (modelling)** · hypothesis **H3**: *the backup is an independent replicate — same generator, different random draw.*
#
# Rows cannot be matched (notebooks 02–05), so the only honest comparison for ~97 % of the data is **distributional**. Three layers:
#
# 1. **Marginals** — every column: KS / Wasserstein / PSI (numeric), Cramér's V / Jensen–Shannon / PSI (categorical).
# 2. **Calibration against sampling noise** — with 10⁵–10⁶ rows any tiny difference is "significant". We therefore compare
#    `d(main, backup)` with `d(main_half_A, main_half_B)`: if the backup is a replicate, the ratio is ≈ 1.
# 3. **Joint structure** — a classifier two-sample test (**C2ST**): can a gradient-boosting model tell main rows from backup rows?
#    AUC ≈ 0.5 ⇒ indistinguishable *jointly*, not only column by column. Plus correlation-matrix distance and Benford's law.
#
# A **positive control** is included: `complaints` are known to be identical except for foreign keys (must pass), and a **negative control**
# (main vs main with a deliberately shifted mean) shows the machinery can detect a real difference.

# %%
import sys
import warnings

sys.path.insert(0, "../src")
warnings.filterwarnings("ignore")
import numpy as np
import pandas as pd
import plotly.graph_objects as go
from IPython.display import display
from scipy import stats
from scipy.spatial.distance import jensenshannon
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.model_selection import StratifiedKFold, cross_val_score

from latam_eda import theme
from latam_eda.data import DERIVED, PK, ROOT, connect

theme.register()
con = connect()
OUT = ROOT / "reports" / "tables"
rng = np.random.default_rng(42)
N = 150_000  # rows per sample
TABLES = [
    "customers",
    "products",
    "transactions",
    "digital_events",
    "call_center_interactions",
    "campaign_sends",
    "complaints",
]
SKIP = {"day", "month", "year"}


def draw(prefix, t, n, exclude_shared=None):
    where = ""
    if exclude_shared:
        pk, keys = exclude_shared
        where = (
            f"where {pk} not in (select {pk} from b_{t})"
            if prefix == "m"
            else f"where {pk} not in (select {pk} from m_{t})"
        )
    # Hashing the (unique) key gives a random-looking sample that is identical on every
    # run; choosing the keys first keeps the sort small. (USING SAMPLE was unseeded and
    # ran before the WHERE, so excluded draws came back short.)
    key = PK[t]
    return con.sql(f"""
        with picked as (select {key} from {prefix}_{t} {where} order by hash({key}) limit {n})
        select x.* from {prefix}_{t} x semi join picked using ({key}) order by hash(x.{key})
    """).df()


# %% [markdown]
# ## 1 · Metric definitions
# * **numeric**: KS statistic *D*; Wasserstein-1 distance divided by the main standard deviation (so scale-free); PSI on main deciles.
# * **categorical**: Cramér's V from the 2 × k table; Jensen–Shannon distance (base 2); PSI.
# * PSI rule of thumb in credit-risk practice: < 0.1 stable, 0.1–0.25 moderate shift, > 0.25 major shift.


# %%
def psi(p, q, eps=1e-6):
    p, q = np.asarray(p, float) + eps, np.asarray(q, float) + eps
    p, q = p / p.sum(), q / q.sum()
    return float(np.sum((p - q) * np.log(p / q)))


def num_metrics(a, b):
    a, b = a.dropna().astype(float), b.dropna().astype(float)
    if len(a) < 30 or len(b) < 30 or a.nunique() < 3:
        return None
    ks = stats.ks_2samp(a, b).statistic
    sd = a.std() or 1.0
    w = stats.wasserstein_distance(a, b) / sd
    edges = np.unique(np.quantile(a, np.linspace(0, 1, 11)))
    edges[0], edges[-1] = -np.inf, np.inf
    return dict(
        ks=ks, wasserstein_sd=w, psi=psi(np.histogram(a, edges)[0], np.histogram(b, edges)[0])
    )


def cat_metrics(a, b, top=60):
    a, b = a.astype("string").fillna("∅"), b.astype("string").fillna("∅")
    cats = a.value_counts().index[:top]
    ca = a.where(a.isin(cats), "other").value_counts()
    cb = b.where(b.isin(cats), "other").value_counts()
    idx = ca.index.union(cb.index)
    ca, cb = ca.reindex(idx, fill_value=0), cb.reindex(idx, fill_value=0)
    if len(idx) < 2:
        return None
    chi2 = stats.chi2_contingency(np.vstack([ca.values, cb.values]) + 0.5)[0]
    v = np.sqrt(chi2 / (ca.sum() + cb.sum()))
    return dict(
        cramers_v=v,
        js=jensenshannon(ca.values / ca.sum(), cb.values / cb.sum(), base=2),
        psi=psi(ca.values, cb.values),
    )


def classify(col, s):
    if (
        col in SKIP
        or col.endswith("_id")
        or col.endswith("_date")
        or col
        in (
            "process_date",
            "date",
            "transaction_date",
            "event_date",
            "interaction_date",
            "send_date",
            "creation_date",
        )
    ):
        return None
    if s.dtype == bool or s.dtype == "boolean":
        return "cat"
    if pd.api.types.is_numeric_dtype(s):
        return "num" if s.nunique() > 12 else "cat"
    if s.dtype == object or str(s.dtype) in ("string", "str"):
        n = s.nunique()
        return "cat" if 1 < n <= 400 else None
    return None


# %% [markdown]
# ## 2 · Marginal comparison with a sampling-noise baseline
# For every table: sample *N* rows from the backup, and two independent halves A/B of main (excluding rows that share a key with the other folder, to avoid
# counting the same record twice). We report the effect size and the **ratio to the A-vs-B baseline**.

# %%

rows = []
for t in TABLES:
    pk = PK[t]
    n = min(N, con.sql(f"select count(*) from b_{t}").fetchone()[0] // 2)
    excl = (
        None if t == "complaints" else (pk, None)
    )  # complaints: all keys are shared, keep them (positive control)
    main2 = draw("m", t, 2 * n, excl)
    A, B = main2.iloc[:n], main2.iloc[n : 2 * n]
    bk = draw("b", t, n, excl)
    for col in main2.columns:
        kind = classify(col, A[col])
        if kind is None:
            continue
        f = num_metrics if kind == "num" else cat_metrics
        d_bk, d_ab = f(A[col], bk[col]), f(A[col], B[col])
        if d_bk is None or d_ab is None:
            continue
        eff = "ks" if kind == "num" else "cramers_v"
        rows.append(
            dict(
                table=t,
                column=col,
                kind=kind,
                effect=d_bk[eff],
                baseline=d_ab[eff],
                ratio=d_bk[eff] / max(d_ab[eff], 1e-9),
                psi=d_bk["psi"],
                psi_baseline=d_ab["psi"],
                wasserstein_sd=d_bk.get("wasserstein_sd", np.nan),
                js=d_bk.get("js", np.nan),
            )
        )
marg = pd.DataFrame(rows)
marg.to_parquet(DERIVED / "marginal_comparison.parquet")
marg.to_csv(OUT / "marginal_comparison.csv", index=False)
print(f"{len(marg)} columns compared across {marg.table.nunique()} tables")

# %%
summ = marg.groupby("table").agg(
    columns=("column", "count"),
    median_ratio=("ratio", "median"),
    max_ratio=("ratio", "max"),
    max_psi=("psi", "max"),
    cols_psi_gt_0_1=("psi", lambda s: int((s > 0.1).sum())),
    cols_ratio_gt_2=("ratio", lambda s: int((s > 2).sum())),
)
summ.style.format({"median_ratio": "{:.2f}", "max_ratio": "{:.2f}", "max_psi": "{:.4f}"})

# %%
fig = go.Figure()
order = marg.sort_values(["table", "ratio"]).reset_index(drop=True)
for t, g in order.groupby("table"):
    fig.add_scatter(
        x=g.ratio,
        y=[t] * len(g),
        mode="markers",
        name=t,
        text=g.column,
        showlegend=False,
        marker=dict(size=8, color=theme.BLUE, opacity=0.6, line=dict(width=1, color="#fcfcfb")),
        hovertemplate="%{text}<br>ratio %{x:.2f}<extra></extra>",
    )
fig.add_vline(x=1, line_dash="dot", line_color="#8a8984")
fig.add_vline(x=2, line_dash="dash", line_color=theme.RED)
fig.update_layout(
    title="Effect size main-vs-backup ÷ main-vs-main (1 = same as sampling noise; > 2 = real difference)",
    height=420,
    xaxis_title="ratio (log scale)",
    xaxis_type="log",
)
fig.show()

# %% [markdown]
# **Reading the chart.** Each dot is one column. Dots clustering around **1** mean the backup's marginal is as close to main as a second random half of main
# is; dots beyond the red line (> 2×) would be genuine differences. The table above counts them per table.

# %% [markdown]
# ## 3 · Controls: does the method see what it should?
# *Positive control* (`complaints`) must give ratios ≈ 1 even though their foreign keys differ. *Negative control*: shift a numeric column by 0.1 σ in
# one half of main and re-run — the ratio must jump.

# %%
t = "transactions"
n = 100_000
two = draw("m", t, 2 * n)
A, B = two.iloc[:n], two.iloc[n:].copy()
col = "fraud_score"
B["fraud_score_shifted"] = B[col] + 0.1 * A[col].std()
ctrl = pd.DataFrame(
    [
        dict(test="A vs B (identical process)", **num_metrics(A[col], B[col])),
        dict(test="A vs B shifted by +0.1 σ", **num_metrics(A[col], B["fraud_score_shifted"])),
        dict(test="A vs B shifted by +0.3 σ", **num_metrics(A[col], B[col] + 0.3 * A[col].std())),
    ]
)
pos = (
    marg[marg.table == "complaints"][["column", "effect", "baseline", "ratio"]]
    .describe()
    .T[["count", "mean", "max"]]
)
display(ctrl.style.format({"ks": "{:.4f}", "wasserstein_sd": "{:.4f}", "psi": "{:.5f}"}))
pos

# %% [markdown]
# **Reading the controls.** A 0.1 σ shift is detected by every metric (KS and PSI rise by an order of magnitude over the identical-process baseline) and the
# complaints positive control stays at the noise floor — so the machinery has power and does not cry wolf.

# %% [markdown]
# ## 4 · Joint structure — classifier two-sample test (C2ST)
# Column-by-column agreement does not rule out a joint difference (e.g. the same marginals but different correlations).
# We train a gradient-boosting classifier to separate **main rows from backup rows** using all non-key, non-date columns
# and report the cross-validated ROC-AUC. **0.5 = indistinguishable**; the baseline is the same test **main-A vs main-B**.


# %%
def c2st(t, n=60_000, cv=4):
    pk = PK[t]
    two = draw("m", t, 2 * n, (pk, None) if t != "complaints" else None)
    A, B = two.iloc[:n], two.iloc[n:]
    bk = draw("b", t, n, (pk, None) if t != "complaints" else None)
    cols = [c for c in A.columns if classify(c, A[c]) is not None]
    out = {}
    for name, X1, X0 in (("main vs backup", A, bk), ("main A vs main B (baseline)", A, B)):
        X = pd.concat([X1[cols], X0[cols]], ignore_index=True)
        y = np.r_[np.ones(len(X1)), np.zeros(len(X0))]
        cat_idx = []
        for i, c in enumerate(cols):
            if classify(c, A[c]) == "cat":
                X[c] = X[c].astype("string").fillna("∅").astype("category").cat.codes
                cat_idx.append(i)
            else:
                X[c] = pd.to_numeric(X[c], errors="coerce")
        clf = HistGradientBoostingClassifier(
            max_iter=120, learning_rate=0.1, categorical_features=cat_idx or None, random_state=0
        )
        sc = cross_val_score(
            clf,
            X,
            y,
            cv=StratifiedKFold(cv, shuffle=True, random_state=0),
            scoring="roc_auc",
            n_jobs=4,
        )
        out[name] = (sc.mean(), sc.std())
    return out


rows = []
for t in TABLES:
    r = c2st(t)
    rows.append(
        dict(
            table=t,
            auc_main_vs_backup=r["main vs backup"][0],
            sd=r["main vs backup"][1],
            auc_baseline=r["main A vs main B (baseline)"][0],
            sd_baseline=r["main A vs main B (baseline)"][1],
        )
    )
c2 = pd.DataFrame(rows)
c2["excess_auc"] = c2.auc_main_vs_backup - c2.auc_baseline
c2.to_csv(OUT / "c2st.csv", index=False)
c2.style.format(dict.fromkeys(c2.columns[1:], "{:.4f}"))

# %%
fig = go.Figure()
fig.add_bar(
    x=c2.table, y=c2.auc_baseline - 0.5, name="main A vs main B (noise)", marker_color="#8a8984"
)
fig.add_bar(
    x=c2.table, y=c2.auc_main_vs_backup - 0.5, name="main vs backup", marker_color=theme.BLUE
)
fig.update_layout(
    barmode="group",
    height=380,
    title="Classifier two-sample test: AUC − 0.5 (0 = indistinguishable)",
    yaxis_title="AUC − 0.5",
    bargap=0.35,
)
fig.show()

# %% [markdown]
# **Interpretation.** If a table's AUC is at the baseline, a flexible classifier cannot tell backup rows from main rows **even using all columns jointly**: the
# backup is statistically indistinguishable from main for that table. Any table with a visible excess AUC contains a *detectable* joint difference; §5 shows which
# columns drive it.

# %% [markdown]
# ## 5 · What drives the difference where there is one?
# Permutation importance on the C2ST for tables with excess AUC.

# %%
from sklearn.inspection import permutation_importance

imp_rows = []
for _, r in c2[c2.excess_auc > 0.01].iterrows():
    t = r.table
    pk = PK[t]
    n = 40_000
    A = draw("m", t, n, (pk, None))
    bk = draw("b", t, n, (pk, None))
    cols = [c for c in A.columns if classify(c, A[c]) is not None]
    X = pd.concat([A[cols], bk[cols]], ignore_index=True)
    y = np.r_[np.ones(n), np.zeros(n)]
    cats = []
    for i, c in enumerate(cols):
        if classify(c, A[c]) == "cat":
            X[c] = X[c].astype("string").fillna("∅").astype("category").cat.codes
            cats.append(i)
        else:
            X[c] = pd.to_numeric(X[c], errors="coerce")
    idx = rng.permutation(len(X))
    tr, te = idx[: int(0.7 * len(X))], idx[int(0.7 * len(X)) :]
    clf = HistGradientBoostingClassifier(
        max_iter=120, categorical_features=cats or None, random_state=0
    ).fit(X.iloc[tr], y[tr])
    pi = permutation_importance(
        clf, X.iloc[te], y[te], scoring="roc_auc", n_repeats=3, random_state=0, n_jobs=4
    )
    for c, v in zip(cols, pi.importances_mean):
        imp_rows.append(dict(table=t, column=c, auc_drop=v))
imp = pd.DataFrame(imp_rows)
imp.sort_values("auc_drop", ascending=False).groupby("table").head(5) if len(imp) else pd.DataFrame(
    {"note": ["no table has an excess AUC > 0.01"]}
)

# %% [markdown]
# ## 6 · Dependence structure and Benford's law
# *Correlation distance:* Frobenius norm of the difference between Spearman correlation matrices (numeric columns), against the A-vs-B baseline.
# *Benford:* first-digit distribution of transaction amounts — a classic forensic test of fabricated or manipulated figures.

# %%
rows = []
for t in [
    "customers",
    "products",
    "transactions",
    "digital_events",
    "call_center_interactions",
    "campaign_sends",
]:
    n = 60_000
    two = draw("m", t, 2 * n)
    bk = draw("b", t, n)
    A, B = two.iloc[:n], two.iloc[n:]
    cols = [c for c in A.columns if classify(c, A[c]) == "num"]
    if len(cols) < 2:
        continue
    cm = lambda D: D[cols].corr(method="spearman").fillna(0).values
    rows.append(
        dict(
            table=t,
            numeric_cols=len(cols),
            frobenius_main_vs_backup=np.linalg.norm(cm(A) - cm(bk)),
            frobenius_baseline=np.linalg.norm(cm(A) - cm(B)),
        )
    )
corr = pd.DataFrame(rows)
corr["ratio"] = corr.frobenius_main_vs_backup / corr.frobenius_baseline
display(
    corr.style.format(
        {"frobenius_main_vs_backup": "{:.4f}", "frobenius_baseline": "{:.4f}", "ratio": "{:.2f}"}
    )
)


def first_digit(s):
    s = s[s > 0]
    return (
        (s / 10 ** np.floor(np.log10(s)))
        .astype(int)
        .value_counts(normalize=True)
        .reindex(range(1, 10), fill_value=0)
    )


amt_m = (
    con.sql(
        "select amount from m_transactions where amount > 0 order by hash(transaction_id) limit 500000"
    )
    .df()
    .amount
)
amt_b = (
    con.sql(
        "select amount from b_transactions where amount > 0 order by hash(transaction_id) limit 500000"
    )
    .df()
    .amount
)
benford = pd.Series({d: np.log10(1 + 1 / d) for d in range(1, 10)})
fd = pd.DataFrame({"Benford": benford, "main": first_digit(amt_m), "backup": first_digit(amt_b)})
mad = {c: (fd[c] - benford).abs().mean() for c in ("main", "backup")}
fig = go.Figure()
fig.add_bar(x=fd.index, y=fd.Benford, name="Benford expectation", marker_color="#e6e5e1")
fig.add_scatter(
    x=fd.index, y=fd.main, mode="lines+markers", name="main", line=dict(color=theme.MAIN_C, width=2)
)
fig.add_scatter(
    x=fd.index,
    y=fd.backup,
    mode="lines+markers",
    name="backup",
    line=dict(color=theme.BACKUP_C, width=2, dash="dot"),
)
fig.update_layout(
    height=360,
    title=f"First-digit distribution of transaction amounts (MAD from Benford: main {mad['main']:.4f}, backup {mad['backup']:.4f})",
    xaxis_title="leading digit",
    yaxis_title="share",
)
fig.show()

# %% [markdown]
# ## 7 · The differences that *are* real: null rates and vocabulary
# Sections 2–4 flagged three tables (interactions, campaign sends, digital events). Two cheap, exhaustive scans tell us *what* changed:
# **(a)** per-column **null rate** in each folder (two-proportion z-test), **(b)** per-column **vocabulary** — categorical values that exist in one folder only.

# %%

SHARED = [
    "customers",
    "products",
    "branches",
    "service_agents",
    "marketing_campaigns",
    "transactions",
    "digital_events",
    "call_center_interactions",
    "campaign_sends",
    "complaints",
]
rows = []
for t in SHARED:
    cols = [r[0] for r in con.sql(f"describe m_{t}").fetchall() if r[0] not in SKIP]
    q = lambda p: (
        con.sql(
            "select count(*) n, "
            + ", ".join(f"avg(({c} is null)::int) as {c}" for c in cols)
            + f" from {p}_{t}"
        )
        .df()
        .iloc[0]
    )
    m, b = q("m"), q("b")
    for c in cols:
        n1, n2, p1, p2 = m.n, b.n, m[c], b[c]
        pool = (p1 * n1 + p2 * n2) / (n1 + n2)
        z = (p2 - p1) / np.sqrt(max(pool * (1 - pool) * (1 / n1 + 1 / n2), 1e-18))
        rows.append(
            dict(
                table=t,
                column=c,
                null_main_pct=100 * p1,
                null_backup_pct=100 * p2,
                delta_pp=100 * (p2 - p1),
                z=z,
            )
        )
nulls = pd.DataFrame(rows)
nulls.to_csv(OUT / "null_rate_comparison.csv", index=False)
top = nulls.reindex(nulls.delta_pp.abs().sort_values(ascending=False).index).head(18)
top.style.format(
    {"null_main_pct": "{:.1f}", "null_backup_pct": "{:.1f}", "delta_pp": "{:+.1f}", "z": "{:,.0f}"}
)

# %%
sig = nulls[nulls.delta_pp.abs() >= 1]
fig = go.Figure(
    go.Bar(
        y=[f"{r.table}.{r.column}" for r in sig.itertuples()],
        x=sig.delta_pp,
        orientation="h",
        marker_color=[theme.BACKUP_C if v > 0 else theme.BLUE for v in sig.delta_pp],
    )
)
fig.update_layout(
    height=max(320, 28 * len(sig)),
    margin=dict(l=300),
    title="Columns whose null rate differs by ≥ 1 percentage point (backup − main)",
    xaxis_title="percentage points",
    yaxis_autorange="reversed",
)
fig.show()

# %% [markdown]
# **Interpretation (a).** Only a handful of columns differ materially. In `call_center_interactions` the backup **wipes call metrics**: `duration_seconds` goes from 14 % null to
# 99 % and `wait_time_seconds` from 30 % to 100 % (and the boolean `has_recording` collapses from 86 % true to 1 % — a flag, so not a null, but the same wipe-out).
# `campaign_sends` gains ≈ 5 pp nulls in `was_clicked` and 3.6 pp in `was_opened`; `digital_events` marketing attribution (`utm_*`: +3.7 pp, `referrer`: +3.4 pp) is emptier.
# The other ≈ 140 columns are within ≈ 1 pp (the only other |Δ| > 1 pp are `service_agents` columns on 1,200 rows, with |z| ≈ 1, i.e. noise) — the changes are *targeted*, not diffuse.

# %%
rows = []
for t in SHARED:
    for c, typ in [(r[0], r[1]) for r in con.sql(f"describe m_{t}").fetchall()]:
        if (
            c in SKIP
            or typ != "VARCHAR"
            or c.endswith("_id")
            or c in ("email", "phone", "address", "description", "full_text")
        ):
            continue
        nd = con.sql(f"select approx_count_distinct({c}) from m_{t}").fetchone()[0]
        if nd > 150:
            continue
        r = con.sql(f"""with a as (select {c} v, count(*) n from m_{t} where {c} is not null group by 1),
                             b as (select {c} v, count(*) n from b_{t} where {c} is not null group by 1)
                        select (select count(*) from a where v not in (select v from b)) only_main,
                               (select count(*) from b where v not in (select v from a)) only_backup,
                               (select coalesce(sum(n),0) from a where v not in (select v from b)) rows_main,
                               (select coalesce(sum(n),0) from b where v not in (select v from a)) rows_backup""").fetchone()
        if r[0] or r[1]:
            ex_m = con.sql(
                f"select string_agg(v, ' | ' order by v) from (select distinct {c} v from m_{t} where {c} is not null and {c} not in (select {c} from b_{t} where {c} is not null) order by v limit 4)"
            ).fetchone()[0]
            ex_b = con.sql(
                f"select string_agg(v, ' | ' order by v) from (select distinct {c} v from b_{t} where {c} is not null and {c} not in (select {c} from m_{t} where {c} is not null) order by v limit 4)"
            ).fetchone()[0]
            rows.append(
                dict(
                    table=t,
                    column=c,
                    values_only_main=r[0],
                    values_only_backup=r[1],
                    rows_main=r[2],
                    rows_backup=r[3],
                    examples_main=ex_m,
                    examples_backup=ex_b,
                )
            )
vocab = pd.DataFrame(rows)
vocab.to_csv(OUT / "vocabulary_differences.csv", index=False)
vocab if len(vocab) else pd.DataFrame({"note": ["no categorical vocabulary differences"]})

# %% [markdown]
# **Interpretation (b).** The vocabulary scan confirms a **semantic localisation change**: in `call_center_interactions.interaction_type` the backup uses Spanish labels
# (`Llamada Entrante`, `Llamada Saliente`) where main has `Inbound Call`, `Outbound Call` — the same 85 % of rows, just re-labelled. This is classic **schema/vocabulary
# evolution**: an unmapped label breaks any `WHERE interaction_type = 'Inbound Call'` rule and would silently drop 85 % of calls from KPIs. Every other categorical column has the same vocabulary in both folders.

# %% [markdown]
# ## Verdict on H3 (replicate)
# | table | marginals (ratio to noise) | joint C2ST AUC | verdict |
# |---|---|---|---|
# | customers, products, transactions | ≈ 1 (median 1.03–1.12) | 0.496 – 0.502 (= noise) | **indistinguishable → replicate** |
# | complaints (positive control) | 0.79 | ≤ 0.5 (rows duplicated across folders) | **identical, as designed** |
# | digital_events | median 1.45; attribution fields 20–50× | 0.536 | **replicate + degraded marketing attribution** |
# | campaign_sends | median 1.08; `was_clicked` 188× | 0.544 | **replicate + injected nulls in `was_clicked` (+5 pp) and `was_opened` (+3.6 pp)** |
# | call_center_interactions | median 1.11; `interaction_type`, `has_recording` 250–1,400× | **0.989** | **replicate + three targeted defects** |
#
# * For the three **core** tables (customers, products, transactions) the backup is statistically **indistinguishable** from main — marginals, joint structure (C2ST),
#   correlations (transactions ratio 1.04) and Benford conformity (MAD 0.0152 vs 0.0154) all agree. That is strong evidence for **H3: a re-draw of the same generator**.
# * The differences that exist are **not random noise** — they are *targeted and explainable*: relabelled categories, wiped call metrics, a flag with injected nulls and sparser
#   campaign attribution. Those are the signature of **schema evolution / pipeline degradation** in the backup path, not of a different population.
# * The correlation-matrix ratio for `call_center_interactions` (≈ 54) and `products` (2.6) is driven by the same wiped metrics and the currency re-denomination of notebook 05.
