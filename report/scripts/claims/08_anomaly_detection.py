"""Chapter 8 · Anomaly detection.

Reads the integrity-rule table, the daily-series summary and the detector results the exploratory notebooks 07–11
stored, and recomputes or extends them:

* the daily-volume screen (STL residuals, generalized ESD) on both copies, and the overlap of flagged days;
* the injected benchmark (positive control): average precision with intervals from resampling customers, paired
  differences between detectors, the ensemble gain on the test half with members selected on the validation half,
  recall by anomaly type, and the review budget that minimises cost over a range of cost ratios;
* the real fraud label: fraud rates by fraud-score band with customer-resampled intervals, and the notebook's
  supervised models refitted on the same split with DeLong intervals.

    uv run python scripts/claims/08_anomaly_detection.py
"""

from __future__ import annotations

import json
import re

import numpy as np
import pandas as pd
from scipy import stats
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.metrics import average_precision_score
from sklearn.model_selection import train_test_split
from statsmodels.tsa.seasonal import STL

from report_lib import db
from report_lib.build import Chapter
from report_lib.eda import anomaly
from report_lib.estimators import intervals
from report_lib.estimators.auc import delong
from report_lib.estimators.intervals import Interval
from report_lib.paths import BUILD, REPO, TABLES
from report_lib.texgen import render_table

DERIVED = REPO / "data" / "derived"
MAIN = REPO / "data" / "parquet"
NB = REPO / "eda" / "notebooks"
OUT = BUILD / "sources"
SEED = 7  # the notebooks' benchmark seed
B = 300  # customer-resampling replicates for the benchmark intervals
RATIOS = (10, 30, 100, 300, 1000)  # cost of a missed anomaly relative to reviewing one alert
SHORT = {"Isolation Forest": "iforest", "HBOS": "hbos", "COPOD": "copod", "ECOD": "ecod",
         "Robust Mahalanobis": "mahalanobis", "GMM (6 comp.)": "gmm", "kNN distance (k=20)": "knn",
         "LOF (k=30)": "lof", "One-Class SVM": "ocsvm", "PCA reconstruction": "pca", "Autoencoder": "ae",
         "VAE (neg. ELBO)": "vae", "Univariate max |robust z|": "univariate"}  # fmt: skip


def cell_text(nb: str, i: int) -> str:
    cell = json.loads((NB / nb).read_text())["cells"][i]
    return "".join(
        "".join(o.get("text", [])) or "".join(o.get("data", {}).get("text/plain", []))
        for o in cell["outputs"]
    )


def rules(ch: Chapter) -> None:
    p = TABLES / "integrity_rules.csv"
    r = pd.read_csv(p).set_index("rule")
    ch.count("rules", len(r), p, source_type="table")
    for rule in (
        "R01",
        "R02",
        "R03",
        "R05",
        "R06",
        "R08",
        "R09",
        "R10",
        "R15",
        "R16",
        "R17",
        "R18",
        "R19",
        "R20",
    ):
        ch.census(f"rate-{rule.lower()}", float(r.loc[rule, "rate_main_%"]), p, source_type="table", unit="percent",
                  digits=3)  # fmt: skip
    ch.census(
        "rate-r01-backup",
        float(r.loc["R01", "rate_backup_%"]),
        p,
        source_type="table",
        unit="percent",
        digits=3,
    )
    ch.count("viol-r04", int(r.loc["R04", "viol_main"]), p, source_type="table")
    ch.count("viol-r14", int(r.loc["R14", "viol_main"]), p, source_type="table")
    gap = (r["rate_main_%"] - r["rate_backup_%"]).abs().drop("R01")
    ch.census(
        "rule-gap-max", float(gap.max()), p, source_type="table", unit="percentage points", digits=2
    )
    render_table(p, "ch08-rules", "Integrity rules: predicates that should never hold, with the share of the rows each "
                 "applies to that violate it, per copy (notebook 07). Severity A breaks accounting logic, B business "
                 "plausibility, C is a data-quality smell.",
                 columns=["severity", "table", "description", "rate_main_%", "rate_backup_%"], digits=3)  # fmt: skip


def amounts(ch: Chapter, con) -> None:
    src = MAIN / "transactions.parquet"
    mx, ge = con.sql("""select max(coalesce(amount_usd, case when currency = 'USD' then amount end)),
                               count(*) filter (where coalesce(amount_usd, case when currency = 'USD' then amount end) >= 10000)
                        from m_transactions""").fetchone()  # fmt: skip
    ch.census("usd-max", float(mx), src, digits=6)
    ch.count("usd-at-or-above-cap", int(ge), src)
    t = cell_text("07_anomaly_detection_classical.ipynb", 14)
    m = re.search(r"\n0\s+(\d+)\s+(\d+)\s+(\d+)\s+(\d+)", t)
    nb = NB / "07_anomaly_detection_classical.ipynb"
    ch.count("impossible-travel", int(m.group(2)), nb, source_type="notebook")
    py = NB / "07_anomaly_detection_classical.py"
    assert "|z| > 3.5" in py.read_text()
    ch.constant("modz-cut", 3.5, py, source_type="notebook")
    assert "1.5 * (q3 - q1)" in py.read_text()
    ch.constant("tukey-k", 1.5, py, source_type="notebook")
    ch.count("rapid-repeat", int(m.group(3)), nb, source_type="notebook")


def gesd(x, max_out: int, alpha: float = 0.05) -> set[int]:
    """Generalized ESD test for up to `max_out` outliers (Rosner 1983), as notebook 07 runs it."""
    x = np.asarray(x, float).copy()
    n, ii = len(x), np.arange(len(x))
    R, lam, order = [], [], []
    for i in range(1, max_out + 1):
        mu, sd = x.mean(), x.std(ddof=1)
        if sd == 0:
            break
        dev = np.abs(x - mu) / sd
        j = int(dev.argmax())
        R.append(dev[j])
        order.append(int(ii[j]))
        t = stats.t.ppf(1 - alpha / (2 * (n - i + 1)), n - i - 1)
        lam.append((n - i) * t / np.sqrt((n - i - 1 + t**2) * (n - i + 1)))
        x, ii = np.delete(x, j), np.delete(ii, j)
    k = max([i for i in range(len(R)) if R[i] > lam[i]], default=-1) + 1
    return set(order[:k])


def volume(ch: Chapter, con) -> None:
    rows = []
    flagged = {}
    for t in (
        "transactions",
        "digital_events",
        "call_center_interactions",
        "campaign_sends",
        "complaints",
    ):
        for p, lab in (("m", "main"), ("b", "backup")):
            s = (
                con.sql(f"select process_date d, count(*) n from {p}_{t} group by 1 order by 1")
                .df()
                .set_index("d")
                .n
            )
            s.index = pd.DatetimeIndex(s.index)
            s = s.asfreq("D").fillna(0)
            fit = STL(np.log1p(s.to_numpy()), period=7, robust=True).fit()
            resid = fit.resid
            strength = max(0.0, 1 - np.var(resid) / np.var(resid + fit.seasonal))
            days = gesd(resid, max_out=max(5, int(0.05 * len(s))))
            flagged[(t, lab)] = set(s.index[sorted(days)])
            rows.append({"table": t, "dataset": lab, "days": len(s), "seasonal strength": strength,
                         "ESD days": len(days)})  # fmt: skip
    v = pd.DataFrame(rows)
    jac = []
    for t in v.table.unique():
        a, b = flagged[(t, "main")], flagged[(t, "backup")]
        inter, union = len(a & b), len(a | b)
        jac.append(
            {
                "table": t,
                "flagged both": inter,
                "flagged either": union,
                "jaccard": inter / union if union else np.nan,
            }
        )
    j = pd.DataFrame(jac)
    v = v.merge(j, on="table")
    v.to_csv(OUT / "ch08_volume.csv", index=False)
    src = MAIN / "transactions.parquet"
    stored = pd.read_csv(TABLES / "daily_series_anomalies.csv")
    both = v.merge(stored, left_on=["table", "dataset"], right_on=["table", "folder"])
    ch.count("esd-agree", int((both["ESD days"] == both.esd_days).sum()), TABLES / "daily_series_anomalies.csv",
             source_type="table")  # fmt: skip
    ch.count("esd-series", len(both), TABLES / "daily_series_anomalies.csv", source_type="table")
    ch.count("pelt-breaks", int(stored.pelt_changepoints.sum()), TABLES / "daily_series_anomalies.csv",
             source_type="table")  # fmt: skip
    m = v[v.dataset == "main"].set_index("table")
    ch.census(
        "strength-min", float(m.drop("digital_events")["seasonal strength"].min()), src, digits=2
    )
    ch.census(
        "strength-max", float(m.drop("digital_events")["seasonal strength"].max()), src, digits=2
    )
    ch.census("strength-events", float(m.loc["digital_events", "seasonal strength"]), src, digits=2)
    ch.count("esd-max", int(m["ESD days"].max()), src)
    for t in ("transactions", "complaints"):
        ch.census(f"jaccard-{t}", float(j.set_index("table").loc[t, "jaccard"]), src, digits=2)
    ch.census("jaccard-max-other", float(j[j.table != "complaints"].jaccard.max()), src, digits=2)
    render_table(OUT / "ch08_volume.csv", "ch08-volume", "Daily volume per table and copy: strength of the weekly "
                 "pattern, days flagged by the generalized ESD test on the STL residual, and how many flagged days the "
                 "copies share.", columns=["table", "dataset", "days", "seasonal strength", "ESD days", "flagged both",
                                           "jaccard"], digits=2)  # fmt: skip


def mcd(ch: Chapter) -> None:
    nb = NB / "07_anomaly_detection_classical.ipynb"
    t = cell_text("07_anomaly_detection_classical.ipynb", 24)
    m = re.search(
        r"customers: ([\d,]+) .*?χ²\(([\d.]+), df=(\d+)\) = ([\d.]+): ([\d,]+) \(([\d.]+)%\)", t
    )
    ch.count("mcd-customers", int(m.group(1).replace(",", "")), nb, source_type="notebook")
    ch.constant(
        "mcd-level", 100 * float(m.group(2)), nb, source_type="notebook", unit="percent", digits=3
    )
    ch.count("mcd-df", int(m.group(3)), nb, source_type="notebook")
    ch.census("mcd-cutoff", float(m.group(4)), nb, source_type="notebook", digits=3)
    ch.count("mcd-flagged", int(m.group(5).replace(",", "")), nb, source_type="notebook")
    ch.census(
        "mcd-nominal",
        100 * (1 - float(m.group(2))),
        nb,
        source_type="notebook",
        unit="percent",
        digits=2,
    )
    ch.census(
        "mcd-flagged-pct", float(m.group(6)), nb, source_type="notebook", unit="percent", digits=3
    )


def bench_scores() -> tuple[pd.DataFrame, list[str]]:
    a = pd.read_parquet(DERIVED / "bench_scores_main.parquet")
    b = pd.read_parquet(DERIVED / "bench_scores_deep.parquet")
    assert (a.transaction_id.to_numpy() == b.transaction_id.to_numpy()).all()
    scores = pd.concat([a, b[["Autoencoder", "VAE (neg. ELBO)"]]], axis=1)
    meta = [
        "transaction_id",
        "customer_id",
        "anomaly_type",
        "is_injected",
        "is_fraud",
        "fraud_score",
    ]
    methods = [c for c in scores.columns if c not in meta]
    # the notebooks' univariate screen, rebuilt from the cached features and the same injection
    feats = pd.read_parquet(DERIVED / "tx_features_m_300000.parquet")
    bench = anomaly.inject_anomalies(feats, rate=0.01, seed=SEED)
    ev = np.random.default_rng(SEED).choice(len(bench), 100_000, replace=False)
    assert (bench.iloc[ev].transaction_id.to_numpy() == scores.transaction_id.to_numpy()).all()
    X = bench[anomaly.FEATURES].astype(float).replace([np.inf, -np.inf], np.nan)
    X = X.fillna(X.median())
    cont = ["log_usd", "log_gap_prev", "n_last_24h", "ratio_to_cust_median", "cust_n_trx"]
    med = X[cont].median()
    mad = (X[cont] - med).abs().median().replace(0, 1)
    scores["Univariate max |robust z|"] = (
        (0.6745 * (X[cont].iloc[ev] - med) / mad).abs().max(axis=1).to_numpy()
    )
    return scores, [*methods, "Univariate max |robust z|"]


def boot_ap(y, cols: dict[str, np.ndarray], groups, rng) -> dict[str, np.ndarray]:
    """Average precision of every score on the same customer resamples, so differences are paired."""
    codes, _ = pd.factorize(groups)
    G = codes.max() + 1
    out = {k: np.empty(B) for k in cols}
    for b in range(B):
        w = np.bincount(rng.integers(0, G, G), minlength=G)[codes]
        keep = w > 0
        for k, s in cols.items():
            out[k][b] = average_precision_score(y[keep], s[keep], sample_weight=w[keep])
    return out


def pct_iv(est: float, draws: np.ndarray, method: str = "cluster-bootstrap") -> Interval:
    lo, hi = np.quantile(draws, [0.025, 0.975])
    return Interval(float(est), float(lo), float(hi), method, None)


def benchmark(ch: Chapter) -> None:
    ch.status = "positive-control"
    scores, methods = bench_scores()
    src = DERIVED / "bench_scores_main.parquet"
    y = scores.is_injected.to_numpy().astype(int)
    cust = scores.customer_id.to_numpy()
    ch.count("bench-rows", len(y), src)
    ch.count("bench-injected", int(y.sum()), src)
    ch.count("bench-customers", int(pd.Series(cust).nunique()), src)
    ch.constant("bench-boot", B, src)
    ch.count("bench-types", int(pd.Series(scores.anomaly_type[scores.is_injected]).nunique()), src)
    rng = np.random.default_rng(2026)

    # every detector on all evaluation rows
    full = {m: scores[m].to_numpy(float) for m in methods}
    draws = boot_ap(y, full, cust, rng)
    rows = []
    for m in methods:
        est = average_precision_score(y, full[m])
        iv = pct_iv(est, draws[m])
        ch.metric(f"ap-{SHORT[m]}", iv, len(y), src, digits=3)
        rows.append({"detector": m, "average precision": est, "lower": iv.lo, "upper": iv.hi,
                     "AUC": delong(y, full[m]).estimate})  # fmt: skip
    ap_tab = pd.DataFrame(rows).sort_values("average precision", ascending=False)
    good = ap_tab[
        ap_tab["average precision"] > 10 * y.mean()
    ]  # detectors that beat chance by an order of magnitude
    ch.census("auc-min", float(good.AUC.min()), src, digits=2)
    ch.census("auc-max", float(good.AUC.max()), src, digits=2)
    ap_tab.to_csv(OUT / "ch08_benchmark_ap.csv", index=False)
    ch.census("prevalence", float(y.mean()), src, digits=3)
    for a, b in (
        ("COPOD", "Robust Mahalanobis"),
        ("COPOD", "Isolation Forest"),
        ("Robust Mahalanobis", "Isolation Forest"),
    ):
        d = draws[a] - draws[b]
        est = average_precision_score(y, full[a]) - average_precision_score(y, full[b])
        ch.difference(f"ap-diff-{SHORT[a]}-{SHORT[b]}", pct_iv(est, d), src, "customer", digits=2)
    ch.metric("auc-copod", delong(y, full["COPOD"]), len(y), src, digits=3)

    # ensembles: members chosen on the validation half, judged on the test half (the notebook's split)
    idx = np.arange(len(y))
    va, te = idx[idx % 2 == 0], idx[idx % 2 == 1]
    ranks = scores[methods].rank(pct=True)
    val_ap = pd.Series(
        {m: average_precision_score(y[va], full[m][va]) for m in methods}
    ).sort_values(ascending=False)
    test_ap = pd.Series(
        {m: average_precision_score(y[te], full[m][te]) for m in methods}
    ).sort_values(ascending=False)
    top3_val, top3_test = list(val_ap.index[:3]), list(test_ap.index[:3])
    ch.count("top3-same", int(set(top3_val) == set(top3_test)), src)
    ens = ranks[top3_val].mean(axis=1).to_numpy()
    ens_all = ranks[methods].mean(axis=1).to_numpy()
    best = val_ap.index[0]
    cols = {"ens": ens[te], "best": full[best][te], "all": ens_all[te]}
    d2 = boot_ap(y[te], cols, cust[te], rng)
    est = {k: average_precision_score(y[te], v) for k, v in cols.items()}
    ch.metric("ens-test", pct_iv(est["ens"], d2["ens"]), len(te), src, digits=3)
    ch.metric("best-test", pct_iv(est["best"], d2["best"]), len(te), src, digits=3)
    ch.metric("all-test", pct_iv(est["all"], d2["all"]), len(te), src, digits=3)
    ch.difference(
        "ens-gain",
        pct_iv(est["ens"] - est["best"], d2["ens"] - d2["best"]),
        src,
        "customer",
        digits=2,
    )
    ch.count("methods", len(methods), src)

    # recall by type at a review budget of the top hundredth of rows
    k = len(y) // 100
    typ = scores.anomaly_type.to_numpy()
    rec = []
    for m in methods:
        top = np.zeros(len(y), bool)
        top[np.argsort(-full[m], kind="stable")[:k]] = True
        r = {"detector": m}
        for t in sorted(set(typ[y == 1])):
            num, den = int((top & (typ == t)).sum()), int((typ == t).sum())
            r[t.replace("_", " ")] = num / den
            if m in ("COPOD", "Robust Mahalanobis", "Isolation Forest", "LOF (k=30)"):
                ch.proportion(f"recall-{SHORT[m]}-{t.replace('_', '-')}", num, den, intervals.wilson(num, den), src,
                              digits=3)  # fmt: skip
        rec.append(r)
    rec_tab = pd.DataFrame(rec).set_index("detector").loc[ap_tab.detector].reset_index()
    rec_tab.to_csv(OUT / "ch08_recall_by_type.csv", index=False)
    ch.count("budget", k, src)
    ch.count("dormant-injected", int((typ == "dormant_reactivation").sum()), src)

    # cost: review the top k; a miss costs r, a review costs 1
    P = int(y.sum())
    crow = []
    for r in RATIOS:
        best_cost, best_m, best_k = None, None, None
        for m in methods:
            tp = np.concatenate([[0], np.cumsum(y[np.argsort(-full[m], kind="stable")])])
            cost = np.arange(len(tp)) + r * (P - tp)
            kk = int(cost.argmin())
            if best_cost is None or cost[kk] < best_cost:
                best_cost, best_m, best_k = float(cost[kk]), m, kk
            if r == 100 and m == "VAE (neg. ELBO)":
                ch.census("cost-vae-100", float(cost[kk]), src)
        crow.append({"miss cost / review cost": r, "best detector": best_m, "alerts reviewed": best_k,
                     "total cost": best_cost, "cost of reviewing nothing": float(r * P),
                     "saving": 1 - best_cost / (r * P)})  # fmt: skip
        ch.count(f"cost-k-{r}", best_k, src)
        ch.census(
            f"cost-saving-{r}", 100 * (1 - best_cost / (r * P)), src, unit="percent", digits=3
        )
    for r in RATIOS:
        ch.constant(f"ratio-{r}", r, src)
    pd.DataFrame(crow).to_csv(OUT / "ch08_cost.csv", index=False)
    ch.count("cost-best-detectors", pd.DataFrame(crow)["best detector"].nunique(), src)

    stab = pd.read_csv(TABLES / "ml_stability_main_vs_backup.csv").set_index("Unnamed: 0")
    sp = TABLES / "ml_stability_main_vs_backup.csv"
    ch.census("stab-copod", float(stab.loc["COPOD", "Δ"]), sp, source_type="table", digits=2)
    ch.census(
        "stab-max-other",
        float(stab.drop("COPOD")["Δ"].abs().max()),
        sp,
        source_type="table",
        digits=2,
    )
    ch.status = None

    render_table(OUT / "ch08_benchmark_ap.csv", "ch08-benchmark", "Injected benchmark (positive control): average "
                 "precision of each detector on the evaluation rows, with a 95\\,\\% interval from resampling customers, "
                 "and the ROC AUC.", digits=3)  # fmt: skip
    render_table(OUT / "ch08_recall_by_type.csv", "ch08-recall", "Injected benchmark (positive control): share of each "
                 "anomaly type among the top hundredth of rows by score.", digits=2)  # fmt: skip
    render_table(OUT / "ch08_cost.csv", "ch08-cost", "Injected benchmark (positive control): for each ratio of the cost "
                 "of a missed anomaly to the cost of reviewing an alert, the detector and review budget with the lowest "
                 "total cost, and the saving against reviewing nothing.", digits=3)  # fmt: skip


def fraud(ch: Chapter, con) -> None:
    src = MAIN / "transactions.parquet"
    d = con.sql("""select customer_id,
                          case when fraud_score is null then 'missing' when fraud_score < 30 then 'under 30'
                               when fraud_score < 35 then '30 to 35' else '35 and above' end as band,
                          count(*) as rows, sum(is_fraud::int) as fraud
                   from m_transactions group by all""").df()  # fmt: skip
    total = int(d.fraud.sum())
    ch.count("fraud-total", total, src)
    ch.census("fraud-rate", 100 * total / d.rows.sum(), src, unit="percent", digits=3)
    rows = []
    for band, g in d.groupby("band"):
        k, n = int(g.fraud.sum()), int(g.rows.sum())
        if 0 < k < n:
            iv, unit = intervals.cluster_bootstrap_ratio(g.fraud.to_numpy(), g.rows.to_numpy(), g.customer_id.to_numpy(),
                                                         seed=8), "customer"  # fmt: skip
        else:  # every resample of an all-or-nothing band repeats it; the Wilson bound is the honest one
            iv, unit = intervals.wilson(k, n), "none"
        tag = band.replace(" ", "-")
        ch.proportion(f"band-{tag}", k, n, iv, src, cluster_unit=unit, digits=3)
        ch.census(f"band-{tag}-share", 100 * g.fraud.sum() / total, src, unit="percent", digits=3)
        ch.count(f"band-{tag}-fraud", int(g.fraud.sum()), src)
        rows.append({"fraud score": band, "transactions": int(g.rows.sum()), "fraud": int(g.fraud.sum()),
                     "fraud rate": g.fraud.sum() / g.rows.sum(), "lower": iv.lo, "upper": iv.hi,
                     "share of all fraud": g.fraud.sum() / total})  # fmt: skip
    order = ["35 and above", "30 to 35", "under 30", "missing"]
    pd.DataFrame(rows).set_index("fraud score").loc[order].reset_index().to_csv(
        OUT / "ch08_fraud_bands.csv", index=False
    )
    render_table(OUT / "ch08_fraud_bands.csv", "ch08-fraud-bands", "The fraud label by band of the shipped fraud score, "
                 "main copy: transactions, fraud cases, fraud rate with a 95\\,\\% interval from resampling customers, "
                 "and the band's share of all fraud.", digits=3)  # fmt: skip

    # the notebook's supervised models, refitted on its split, with DeLong intervals
    fp = DERIVED / "tx_features_m_300000_fraudall.parquet"
    real = pd.read_parquet(fp)
    X = real[anomaly.FEATURES + ["fraud_score"]].astype(float).replace([np.inf, -np.inf], np.nan)
    yr = real.is_fraud.astype(int).to_numpy()
    tr, te = train_test_split(np.arange(len(real)), test_size=0.3, stratify=yr, random_state=SEED)
    ch.count("leak-rows", len(real), fp)
    ch.count("leak-fraud", int(yr.sum()), fp)
    ch.count("leak-test-fraud", int(yr[te].sum()), fp)
    for tag, cols in (
        ("features", anomaly.FEATURES),
        ("with-score", anomaly.FEATURES + ["fraud_score"]),
        ("score", ["fraud_score"]),
    ):
        model = HistGradientBoostingClassifier(max_iter=150, learning_rate=0.1, max_depth=4, early_stopping=False,
                                               class_weight="balanced", random_state=SEED).fit(X.iloc[tr][cols], yr[tr])  # fmt: skip
        pr = model.predict_proba(X.iloc[te][cols])[:, 1]
        ch.metric(f"leak-auc-{tag}", delong(yr[te], pr), len(te), fp, digits=3)
        ch.census(f"leak-ap-{tag}", float(average_precision_score(yr[te], pr)), fp, digits=3)
    ch.census("leak-prevalence", float(yr[te].mean()), fp, digits=3)


def consensus(ch: Chapter) -> None:
    nbi = NB / "10_method_comparison_and_consensus.ipynb"
    t = cell_text("10_method_comparison_and_consensus.ipynb", 15)
    m = re.search(r"([\d,]+) consensus alerts \(([\d.]+)%\)", t)
    ch.count("consensus-alerts", int(m.group(1).replace(",", "")), nbi, source_type="notebook")
    ch.census(
        "consensus-pct", float(m.group(2)), nbi, source_type="notebook", unit="percent", digits=2
    )
    t = cell_text("10_method_comparison_and_consensus.ipynb", 20)
    rows = dict(re.findall(r"\d\s+(False|True)\s+\d+\s+([\d.]+)", t))
    ch.census(
        "r03-alerts", float(rows["True"]), nbi, source_type="notebook", unit="percent", digits=3
    )
    ch.census(
        "r03-rest", float(rows["False"]), nbi, source_type="notebook", unit="percent", digits=3
    )
    py = NB / "10_method_comparison_and_consensus.py"
    rho = re.search(r"Spearman ρ = ([\d.]+)", py.read_text())
    ch.census("profile-rho", float(rho.group(1)), py, source_type="notebook", digits=2)


def main() -> None:
    con = db.connect()
    ch = Chapter(8, "ch08")
    OUT.mkdir(parents=True, exist_ok=True)
    rules(ch)
    amounts(ch, con)
    volume(ch, con)
    mcd(ch)
    benchmark(ch)
    fraud(ch, con)
    consensus(ch)
    print(f"{len(ch.claims)} claims -> {ch.write()}")


if __name__ == "__main__":
    main()
