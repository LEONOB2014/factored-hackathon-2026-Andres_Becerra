"""Chapter 6 · Are the two copies the same process?

Reads notebook 06's marginal distances, classifier two-sample tests, null-rate scan and vocabulary scan; applies the
report-only paired main-backup estimator (customer halvings) to every null rate of the fact tables with a customer
key, against the row-level tolerance the notebook's z-test implied; recomputes Benford conformity of amounts.

    uv run python scripts/claims/06_statistical_equivalence.py
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from report_lib import db
from report_lib.build import Chapter
from report_lib.estimators import paired
from report_lib.paths import BUILD, REPO, TABLES
from report_lib.texgen import render_table

MAIN, BACKUP = REPO / "data" / "parquet", REPO / "data" / "parquet_backup"
OUT = BUILD / "sources"
FACTS = [
    "transactions",
    "digital_events",
    "call_center_interactions",
    "campaign_sends",
    "complaints",
]


def null_profile(con, p: str, t: str, cols: list[str]) -> pd.DataFrame:
    """Rows and null counts per customer and column (rows without a customer are left out)."""
    sel = ", ".join(f"count(*) - count({c}) as {c}" for c in cols)
    return con.sql(f"""select customer_id, count(*) n, {sel} from {p}_{t} where customer_id is not null
                       group by 1 order by 1""").df()  # fmt: skip


def main() -> None:
    con = db.connect()
    ch = Chapter(6, "ch06")
    OUT.mkdir(parents=True, exist_ok=True)

    # --- marginals against the half-versus-half baseline (stored, notebook 06)
    marg = pd.read_csv(TABLES / "marginal_comparison.csv")
    mp = TABLES / "marginal_comparison.csv"
    summ = (marg.groupby("table").agg(columns=("ratio", "size"), median_ratio=("ratio", "median"),
                                      above_two=("ratio", lambda r: int((r > 2).sum())))
            .reset_index())  # fmt: skip
    summ_path = OUT / "ch06_marginal_summary.csv"
    summ.to_csv(summ_path, index=False)
    ch.count("marginal-columns", len(marg), mp, source_type="table")
    nb06 = REPO / "eda" / "notebooks" / "06_statistical_equivalence.py"
    # the notebook's rule for a genuine difference
    ch.count("ratio-threshold", 2, nb06, source_type="notebook")
    core = summ[summ.table.isin(["customers", "products", "transactions"])]
    ch.census("core-median-ratio-min", core.median_ratio.min(), mp, source_type="table", digits=3)
    ch.census("core-median-ratio-max", core.median_ratio.max(), mp, source_type="table", digits=3)
    ch.count("core-above-two", int(core.above_two.sum()), mp, source_type="table")

    # --- classifier two-sample test (stored)
    c2 = pd.read_csv(TABLES / "c2st.csv").set_index("table")
    cp = TABLES / "c2st.csv"
    for t in c2.index:
        s = t.replace("_", "-")
        ch.census(f"auc-{s}", c2.loc[t, "auc_main_vs_backup"], cp, source_type="table", digits=3)
    ch.census("auc-baseline-min", c2.auc_baseline.min(), cp, source_type="table", digits=3)
    ch.census("auc-baseline-max", c2.auc_baseline.max(), cp, source_type="table", digits=3)

    # --- vocabulary (stored)
    voc = pd.read_csv(TABLES / "vocabulary_differences.csv").iloc[0]
    vp = TABLES / "vocabulary_differences.csv"
    ch.count("vocab-columns", len(pd.read_csv(vp)), vp, source_type="table")
    ch.census("vocab-share", 100 * voc.rows_backup / con.sql("select count(*) from b_call_center_interactions")
              .fetchone()[0], vp, source_type="table", unit="percent", digits=3)  # fmt: skip

    # --- null rates: notebook z-test (stored) against the paired estimator (customer halvings)
    nz = pd.read_csv(TABLES / "null_rate_comparison.csv")
    rows = []
    for t in FACTS:
        cols = [c[0] for c in con.sql(f"describe m_{t}").fetchall() if c[0] not in ("customer_id",)]
        pm, pb = null_profile(con, "m", t, cols), null_profile(con, "b", t, cols)
        n_m, n_b = pm.n.sum(), pb.n.sum()
        num = pm[cols].to_numpy(dtype=float)
        d0, inv = paired.halving_noise(num, pm.n.to_numpy(dtype=float), reps=400, seed=2026)
        tol = paired.tolerance(d0, inv, n_m, n_b)
        share_m, share_b = num.sum(0) / n_m, pb[cols].to_numpy(dtype=float).sum(0) / n_b
        iid = paired.iid_tolerance(share_m, n_m, n_b)
        for j, c in enumerate(cols):
            if share_m[j] == 0 and share_b[j] == 0:
                continue
            rows.append({"table": t, "column": c, "null_main_pct": 100 * share_m[j], "null_backup_pct": 100 * share_b[j],
                         "delta_pp": 100 * (share_b[j] - share_m[j]), "tolerance_pp": 100 * tol[j],
                         "iid_tolerance_pp": 100 * iid[j], "clusters": len(pm)})  # fmt: skip
    pn = pd.DataFrame(rows)
    pn["flag_paired"] = pn.delta_pp.abs() > pn.tolerance_pp
    pn["flag_iid"] = pn.delta_pp.abs() > pn.iid_tolerance_pp
    pn["widening"] = pn.tolerance_pp / pn.iid_tolerance_pp.replace(0, np.nan)
    pn_path = OUT / "ch06_paired_nulls.csv"
    pn.sort_values(["table", "column"]).to_csv(pn_path, index=False)
    src = MAIN / "transactions.parquet"
    ch.count("paired-columns", len(pn), src)
    ch.count("paired-flags", int(pn.flag_paired.sum()), src)
    ch.count("iid-flags", int(pn.flag_iid.sum()), src)
    ch.census("widening-median", float(pn.widening.median()), src, digits=2)
    ch.census("widening-max", float(pn.widening.max()), src, digits=2)
    z_flags = nz[(nz.table.isin(FACTS)) & (nz.z.abs() > 1.96)]
    ch.count(
        "notebook-z-flags", len(z_flags), TABLES / "null_rate_comparison.csv", source_type="table"
    )
    for t, c, topic in (("call_center_interactions", "duration_seconds", "duration"),
                        ("call_center_interactions", "wait_time_seconds", "wait"),
                        ("campaign_sends", "was_clicked", "clicked")):  # fmt: skip
        r = pn[(pn.table == t) & (pn.column == c)].iloc[0]
        ch.census(f"null-main-{topic}", r.null_main_pct, src, unit="percent", digits=3)
        ch.census(f"null-backup-{topic}", r.null_backup_pct, src, unit="percent", digits=3)
        ch.census(f"tol-{topic}", r.tolerance_pp, src, unit="percentage points", digits=2)
    flagged = pn[pn.flag_paired].sort_values("delta_pp", key=abs, ascending=False)
    flagged.to_csv(OUT / "ch06_paired_flags.csv", index=False)

    # --- Benford conformity of transaction amounts, both copies
    benford = np.log10(1 + 1 / np.arange(1, 10))
    mads = {}
    for p, name in (("m", "main"), ("b", "backup")):
        d = con.sql(f"""select cast(substr(regexp_replace(cast(abs(amount) as varchar), '^[0.]+', ''), 1, 1) as int) d,
                        count(*) n from {p}_transactions where amount <> 0 group by 1 order by 1""").df()  # fmt: skip
        d = d[d.d.between(1, 9)]
        obs = d.set_index("d").n.reindex(range(1, 10), fill_value=0)
        mads[name] = float(np.mean(np.abs(obs.to_numpy() / obs.sum() - benford)))
    ch.census("benford-mad-main", mads["main"], src, digits=3)
    ch.census("benford-mad-backup", mads["backup"], BACKUP / "transactions.parquet", digits=3)

    render_table(summ_path, "ch06-marginals", "Marginal distance of each column, main against backup, as a ratio "
                 "to the distance between random halves of main: median and number above two, per table "
                 "(notebook 06).", digits=3)  # fmt: skip
    render_table(cp, "ch06-c2st", "Classifier two-sample test: cross-validated AUC of a classifier separating main "
                 "rows from backup rows, against the same test between halves of main (notebook 06).", digits=3)  # fmt: skip
    render_table(OUT / "ch06_paired_flags.csv", "ch06-paired-flags", "Null rates whose main-backup difference "
                 "exceeds the paired tolerance (customer halvings), with the tolerance a row-level test would use.",
                 columns=["table", "column", "null_main_pct", "null_backup_pct", "delta_pp", "tolerance_pp",
                          "iid_tolerance_pp"], digits=3)  # fmt: skip
    print(f"{len(ch.claims)} claims -> {ch.write()}")


if __name__ == "__main__":
    main()
