"""Chapter 18 · Learnability.

Reads the learnability tables of the country series (seven candidate targets in eight scopes: main and backup, the
bank and each market) and adds:

* the transparent model the series recommended for 90-day dormancy, fitted here: a gamma-Poisson (negative binomial)
  model of each customer's monthly rate, two parameters by maximum likelihood on the training cutoffs, scored out of
  time by AUC (DeLong), calibration by decile, Brier score and the naive Poisson plug-in;
* the test that the complaint's "affected product" is a uniform random draw from the bank's products.

    uv run python scripts/claims/18_learnability.py
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from scipy import optimize, stats
from scipy.special import gammaln

from report_lib import db
from report_lib.build import Chapter
from report_lib.estimators.auc import delong
from report_lib.paths import BUILD, REPO, TABLES
from report_lib.texgen import render_table

MAIN = REPO / "data" / "parquet"
OUT = BUILD / "sources"
NB14 = REPO / "eda" / "notebooks" / "country_template" / "14_candidate_models.py"
PAST, FUT = 6, 3  # months of history before a cutoff, months of future after it
SPLIT = "2025-10-01"  # the series' out-of-time split for the dormancy target
SCOPES = [(p, c) for p in ("country", "backup") for c in ("all", "mx", "co", "ar")]
SHORT = {"fraud (honest)": "fraud", "fraud with fraud_score (leak)": "leak", "complaint in next 90 days": "complaint",
         "dormant in next 90 days": "dormant", "more than 30 days past due": "dpd",
         "campaign conversion": "conversion", "complaint within 14 days of a contact": "escalation"}  # fmt: skip


def mapping(ch: Chapter) -> None:
    frames = []
    for p, c in SCOPES:
        t = pd.read_csv(TABLES / f"{p}_{c}_learnability.csv")
        frames.append(t.assign(scope=f"{'main' if p == 'country' else 'backup'} {c.upper()}"))
    L = pd.concat(frames)
    src = TABLES / "country_all_learnability.csv"
    piv = L.pivot_table(index="name", columns="scope", values="auc").loc[list(SHORT)]
    piv.index = [SHORT[i] for i in piv.index]
    piv.reset_index(names="target").to_csv(OUT / "ch18_map.csv", index=False)
    same = L.groupby("name").verdict.nunique()
    ch.count("targets", len(SHORT), src, source_type="table")
    ch.count("scopes", len(SCOPES), src, source_type="table")
    ch.count("verdict-stable", int((same == 1).sum()), src, source_type="table")
    for name, tag in SHORT.items():
        x = L[L.name == name]
        ch.census(f"auc-min-{tag}", float(x.auc.min()), src, source_type="table", digits=3)
        ch.census(f"auc-max-{tag}", float(x.auc.max()), src, source_type="table", digits=3)
    d = L[L.name == "dormant in next 90 days"]
    ch.census(
        "single-min-dormant", float(d.best_single_auc.min()), src, source_type="table", digits=3
    )
    ch.census(
        "single-max-dormant", float(d.best_single_auc.max()), src, source_type="table", digits=3
    )
    ch.census("ap-lift-dormant", float(d.ap_lift.median()), src, source_type="table", digits=2)
    cv = L[L.name == "campaign conversion"]
    ch.census("ap-lift-conversion", float(cv.ap_lift.median()), src, source_type="table", digits=2)
    ch.census(
        "gain-conversion",
        float((cv.auc - cv.best_single_auc).median()),
        src,
        source_type="table",
        digits=2,
    )
    nos = L[L.verdict == "no evidence of signal"]
    ch.count("no-signal", len(nos), src, source_type="table")
    ch.count("cells", len(L), src, source_type="table")
    a = L[(L.name == "dormant in next 90 days") & (L.scope == "main ALL")].iloc[0]
    ch.census("nb-dormant-auc", float(a.auc), src, source_type="table", digits=3)
    ch.census("nb-dormant-lo", float(a.auc_lo), src, source_type="table", digits=3)
    ch.census("nb-dormant-hi", float(a.auc_hi), src, source_type="table", digits=3)
    rule = REPO / "eda" / "src" / "latam_eda" / "country.py"
    text = rule.read_text()
    assert 'row["auc"] < 0.6 or row["ap_lift"] < 1.5' in text and 'row["auc"] < 0.7' in text
    ch.constant("rule-weak-auc", 0.6, rule)
    ch.constant("rule-weak-lift", 1.5, rule)
    ch.constant("rule-learnable-auc", 0.7, rule)
    render_table(OUT / "ch18_map.csv", "ch18-map", "The learnability map: out-of-time ROC AUC of each candidate target "
                 "in each scope, main and backup copy, the bank and each market (country series, notebook 14). The "
                 "leak row uses the shipped fraud score, the positive control of the protocol; a blank cell was not evaluable "
                 "in that copy.", digits=3)  # fmt: skip


def dormancy(ch: Chapter, con) -> None:
    src = MAIN / "transactions.parquet"
    m = con.sql(
        "select customer_id, date_trunc('month', process_date)::date as m, count(*) as n from m_transactions group by all"
    ).df()
    m["m"] = pd.to_datetime(m.m)
    cust = con.sql("select customer_id from m_customers").df().customer_id
    rows = []
    for c in pd.date_range("2024-01-01", "2026-01-01", freq="QS"):
        past = m[(m.m >= c - pd.DateOffset(months=PAST)) & (m.m < c)].groupby("customer_id").n.sum()
        fut = m[(m.m >= c) & (m.m < c + pd.DateOffset(months=FUT))].groupby("customer_id").n.sum()
        d = pd.DataFrame(
            {
                "k": past.reindex(cust).fillna(0).to_numpy(),
                "f": fut.reindex(cust).fillna(0).to_numpy(),
            }
        )
        d = d[d.k > 0].assign(cutoff=c)  # customers active in the six months before the cutoff
        rows.append(d)
    D = pd.concat(rows)
    D["y"] = (D.f == 0).astype(int)
    tr, te = D[D.cutoff < SPLIT], D[D.cutoff >= SPLIT]
    k = tr.k.to_numpy()

    def nll(par):
        a, b = np.exp(par)
        q = b / (b + PAST)
        logp = gammaln(a + k) - gammaln(a) - gammaln(k + 1) + a * np.log(q) + k * np.log1p(-q)
        return -(logp - np.log1p(-(q**a))).sum()  # truncated at one or more transactions

    a, b = np.exp(optimize.minimize(nll, np.log([1.0, 1.0]), method="Nelder-Mead").x)
    p = ((b + PAST) / (b + PAST + FUT)) ** (a + te.k.to_numpy())
    y = te.y.to_numpy()
    ch.count("rows-train", len(tr), src)
    ch.count("rows-test", len(te), src)
    ch.census("gp-a", float(a), src, digits=3)
    ch.census("gp-b", float(b), src, digits=3)
    ch.census("gp-mean-rate", float(a / b), src, digits=3)
    ch.metric("gp-auc", delong(y, p), len(y), src, digits=3)
    ch.census("gp-mean-pred", float(p.mean()), src, digits=3)
    ch.census("gp-obs", float(y.mean()), src, digits=3)
    brier, base = float(np.mean((p - y) ** 2)), float(np.mean((y.mean() - y) ** 2))
    ch.census("gp-brier", brier, src, digits=3)
    ch.census("gp-brier-base", base, src, digits=3)
    ch.census("gp-brier-skill", 100 * (1 - brier / base), src, unit="percent", digits=3)
    pn = np.exp(-te.k.to_numpy() / PAST * FUT)
    ch.census("naive-mean-pred", float(pn.mean()), src, digits=3)
    ch.census(
        "naive-brier-skill",
        100 * (1 - float(np.mean((pn - y) ** 2)) / base),
        src,
        unit="percent",
        digits=3,
    )
    dec = pd.qcut(p, 10, labels=False, duplicates="drop")
    cal = (
        pd.DataFrame({"decile": dec + 1, "predicted": p, "observed": y})
        .groupby("decile")
        .mean()
        .reset_index()
    )
    cal["rows"] = pd.Series(dec).value_counts().sort_index().to_numpy()
    cal.to_csv(OUT / "ch18_calibration.csv", index=False)
    ch.census("cal-gap-max", float((cal.predicted - cal.observed).abs().max()), src, digits=2)
    for k_, v in (("past", PAST), ("future", FUT)):
        ch.constant(f"months-{k_}", v, NB14, source_type="notebook")
    render_table(OUT / "ch18_calibration.csv", "ch18-calibration", "Calibration of the gamma-Poisson dormancy model out "
                 "of time: by decile of predicted probability, the mean prediction, the observed share of customers "
                 "with no transaction in the following months, and the rows in each decile.", digits=3)  # fmt: skip


def random_product(ch: Chapter, con) -> None:
    src = MAIN / "complaints.parquet"
    r = con.sql("""with k as (select ck.country as cc, p.customer_id as prod_owner, k.customer_id as filer, co.country as oc
                              from m_complaints k join m_customers ck on ck.customer_id = k.customer_id
                              join m_products p on p.product_id = k.affected_product_id
                              join m_customers co on co.customer_id = p.customer_id)
                   select cc, count(*) as n, sum((prod_owner <> filer)::int) as other,
                          sum((oc = cc)::int) as same_country from k group by 1 order by 1""").df()  # fmt: skip
    share = con.sql("""select c.country as cc, count(*) / (select count(*) from m_products) as s
                       from m_products p join m_customers c using (customer_id) group by 1""").df().set_index("cc").s  # fmt: skip
    r["expected"] = r.n * r.cc.map(share)
    chi2 = float(
        (((r.same_country - r.expected) ** 2) / (r.expected * (1 - r.cc.map(share)))).sum()
    )
    ch.count("cp-with-product", int(r.n.sum()), src)
    ch.count("cp-other-owner", int(r.other.sum()), src)
    ch.census("cp-chi2-p", float(stats.chi2.sf(chi2, len(r))), src, digits=2)
    ch.census(
        "cp-max-gap", float((r.same_country / r.n - r.cc.map(share)).abs().max()), src, digits=2
    )
    ch.count("cp-total", con.sql("select count(*) from m_complaints").fetchone()[0], src)


def main() -> None:
    con = db.connect()
    ch = Chapter(18, "ch18")
    OUT.mkdir(parents=True, exist_ok=True)
    mapping(ch)
    dormancy(ch, con)
    random_product(ch, con)
    print(f"{len(ch.claims)} claims -> {ch.write()}")


if __name__ == "__main__":
    main()
