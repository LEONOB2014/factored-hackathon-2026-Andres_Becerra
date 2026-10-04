#!/usr/bin/env python3
"""Export compact JSON for the three D3 dashboards into reports/dashboards/data/.

Run after notebooks 02–10 (needs <repo>/data/derived/*.parquet and reports/tables/*.csv):
    uv run scripts/export_dashboard_data.py
"""

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
from sklearn.decomposition import PCA  # noqa: E402
from sklearn.preprocessing import RobustScaler  # noqa: E402

from latam_eda.anomaly import FEATURES, INJECTED, inject_anomalies, load_or_build  # noqa: E402
from latam_eda.data import DERIVED, FACTS, connect  # noqa: E402

OUT = ROOT / "reports" / "dashboards" / "data"
TABLES = ROOT / "reports" / "tables"


def dump(out: Path, name: str, obj) -> None:
    text = json.dumps(obj, separators=(",", ":"), default=float)
    (out / f"{name}.json").write_text(text)
    # .js twin: lets the dashboards open from file:// (fetch() of local JSON is blocked by browsers)
    path = out / f"{name}.js"
    path.write_text(f"window.DATA_{name} = {text};\n")
    print(f"{name}.json/.js  {path.stat().st_size / 1024:,.0f} KB")


def main(out: Path = OUT) -> None:
    out.mkdir(parents=True, exist_ok=True)
    con = connect()

    # ---------------------------------------------------------------- D1 overlap & coverage
    pk = pd.read_csv(TABLES / "set_difference_summary.csv")
    overlap = pk[
        ["table", "main_keys", "backup_keys", "shared", "only_main", "only_backup", "status"]
    ].to_dict("records")
    months = [str(m) for m in pd.period_range("2023-06", "2026-06", freq="M")]
    cov = []
    for t in FACTS:
        m = (
            con.sql(f"select strftime(process_date,'%Y-%m') ym, count(*) n from m_{t} group by 1")
            .df()
            .set_index("ym")
            .n
        )
        try:
            b = (
                con.sql(
                    f"select strftime(process_date,'%Y-%m') ym, count(*) n from b_{t} group by 1"
                )
                .df()
                .set_index("ym")
                .n
            )
        except Exception:
            b = pd.Series(dtype=float)
        for ym in months:
            cov.append(dict(table=t, month=ym, main=int(m.get(ym, 0)), backup=int(b.get(ym, 0))))
    dump(out, "overlap", dict(overlap=overlap, coverage=cov, months=months, tables=FACTS))

    # ---------------------------------------------------------------- D2 time shift
    off = {}
    for t in ["transactions", "digital_events", "call_center_interactions", "campaign_sends"]:
        d = pd.read_parquet(DERIVED / f"offsets_{t}.parquet")
        d["month"] = d.md.dt.strftime("%Y-%m")
        groups = {"all": d}
        if t == "transactions":
            pairs = pd.read_parquet(DERIVED / "transaction_pairs.parquet")
            flag = pairs.set_index("pk").is_clone
            d = d.assign(is_clone=d.pk.map(flag))
            groups = {
                "all": d,
                "clones": d[d.is_clone.eq(True)],
                "collisions": d[d.is_clone.eq(False)],
            }
        off[t] = {}
        for g, dd in groups.items():
            hist = dd.groupby(["month", "k_days"]).size().reset_index(name="n")
            off[t][g] = {
                m: {int(k): int(n) for k, n in zip(h.k_days, h.n)} for m, h in hist.groupby("month")
            }
    dump(out, "timeshift", off)

    # ---------------------------------------------------------------- D3 anomaly explorer
    a = pd.read_parquet(DERIVED / "bench_scores_main.parquet")
    b = pd.read_parquet(DERIVED / "bench_scores_deep.parquet")
    scores = pd.concat([a, b[["Autoencoder", "VAE (neg. ELBO)"]]], axis=1)
    methods = [
        c
        for c in scores.columns
        if c
        not in (
            "transaction_id",
            "customer_id",
            "anomaly_type",
            "is_injected",
            "is_fraud",
            "fraud_score",
        )
    ]
    main = load_or_build(con, "m", n=300_000, seed=1)
    bench = inject_anomalies(main, rate=0.01, seed=7)
    ev = np.random.default_rng(7).choice(len(bench), 100_000, replace=False)
    ev_df = bench.iloc[ev].reset_index(drop=True)
    assert (ev_df.transaction_id.values == scores.transaction_id.values).all()
    # rank-percentile of every method over all 100k rows (so thresholds are comparable), then keep a stratified sample
    rank = scores[methods].rank(pct=True)
    rng = np.random.default_rng(1)
    inj = np.where(ev_df.is_injected == 1)[0]
    norm = rng.choice(np.where(ev_df.is_injected == 0)[0], 5000, replace=False)
    # make sure the very top alerts of every method are present so top-k thresholds behave
    top = np.unique(np.concatenate([np.argsort(-scores[m].values)[:300] for m in methods]))
    keep = np.unique(np.concatenate([inj, norm, top]))
    X = (
        ev_df[FEATURES]
        .astype(float)
        .replace([np.inf, -np.inf], np.nan)
        .fillna(ev_df[FEATURES].median())
    )
    xy = PCA(2, random_state=0).fit_transform(RobustScaler().fit_transform(X))
    rows = []
    for i in keep:
        r = ev_df.iloc[i]
        rows.append(
            dict(
                id=r.transaction_id,
                type=r.anomaly_type or "normal",
                usd=round(float(np.exp(r.log_usd)), 2),
                hour=int(0 if pd.isna(r["hour"]) else r["hour"]),
                n24=int(r.n_last_24h),
                gap_days=round(float(np.expm1(r.log_gap_prev) / 86400), 2),
                foreign=int(0 if pd.isna(r.country_mismatch) else r.country_mismatch),
                x=round(float(xy[i, 0]), 3),
                y=round(float(xy[i, 1]), 3),
                s={m: round(float(rank[m].iloc[i]), 4) for m in methods},
            )
        )
    # exact precision / recall curves over the full 100k evaluation rows
    types_all = ev_df.anomaly_type.replace("", "normal").values
    grid = list(range(50, 1000, 50)) + list(range(1000, 5001, 250))
    curves = {}
    for m in methods:
        order = np.argsort(-scores[m].values)
        t_sorted = types_all[order]
        cum = {t: np.cumsum(t_sorted == t) for t in INJECTED + ["normal"]}
        curves[m] = {str(k): {t: int(cum[t][k - 1]) for t in cum} for k in grid}
    sc = (
        pd.read_csv(TABLES / "method_scorecard.csv", index_col=0)
        .reset_index()
        .rename(columns={"index": "method"})
    )
    dump(
        out,
        "anomalies",
        dict(
            methods=methods,
            types=INJECTED,
            grid=grid,
            curves=curves,
            rows=rows,
            scorecard=sc.round(4).to_dict("records"),
            n_total=int(len(ev_df)),
            n_injected=int(ev_df.is_injected.sum()),
        ),
    )


if __name__ == "__main__":
    main()
