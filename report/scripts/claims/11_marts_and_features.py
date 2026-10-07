"""Chapter 11 · Marts and features.

Reads the built lakehouse (data/lake/lakehouse.duckdb, read-only, the Airflow run the notebooks of pipeline/07–09
describe) and measures:

* the out-of-time split of the fraud features and its embargo;
* the single-feature AUC of every numeric feature on the validation split, with DeLong intervals;
* the peer statistics of the AML mart, whose median absolute deviation is zero, and why;
* credit eligibility and its reasons, the collections score by days-past-due bucket, dispute linkage, and the
  consent and treatment structure of campaign sends.

    uv run python scripts/claims/11_marts_and_features.py
"""

from __future__ import annotations

import re

import duckdb
import pandas as pd

from report_lib import protocol
from report_lib.build import Chapter
from report_lib.estimators.auc import delong
from report_lib.paths import BUILD, REPO
from report_lib.texgen import render_table

LAKE = REPO / "data" / "lake" / "lakehouse.duckdb"
OUT = BUILD / "sources"
THIS = REPO / "report" / "scripts" / "claims" / "11_marts_and_features.py"
SKIP = {"transaction_id", "customer_id", "product_id", "anchor_ts", "label_is_fraud"}


def split(ch: Chapter, con) -> None:
    d = con.sql("""select 'train' as part, min(anchor_ts) lo, max(anchor_ts) hi, count(*) n, sum(label_is_fraud::int) k
                   from features.ml_fraud_train
                   union all select 'valid', min(anchor_ts), max(anchor_ts), count(*), sum(label_is_fraud::int)
                   from features.ml_fraud_valid
                   union all select 'test', min(anchor_ts), max(anchor_ts), count(*), sum(label_is_fraud::int)
                   from features.ml_fraud_test""").df().set_index("part")  # fmt: skip
    for p in d.index:
        ch.count(f"rows-{p}", int(d.loc[p, "n"]), LAKE)
        ch.count(f"fraud-{p}", int(d.loc[p, "k"]), LAKE)
    gap1 = (d.loc["valid", "lo"] - d.loc["train", "hi"]).total_seconds() / 86400
    gap2 = (d.loc["test", "lo"] - d.loc["valid", "hi"]).total_seconds() / 86400
    ch.census("gap-train-valid", gap1, LAKE, unit="days", digits=2)
    ch.census("gap-valid-test", gap2, LAKE, unit="days", digits=2)


def single_auc(ch: Chapter, con) -> None:
    v = con.sql("select * from features.ml_fraud_valid").df()
    y = v.label_is_fraud.astype(bool).to_numpy()
    rows = []
    for c in v.columns:
        if c in SKIP:
            continue
        x = v[c]
        if x.dtype == bool or str(x.dtype) == "boolean":
            x = x.astype(float)
        if not pd.api.types.is_numeric_dtype(x):
            continue
        x = x.astype(float).fillna(
            x.astype(float).median()
        )  # missing as the median: no information either way
        iv = delong(y, x.to_numpy())
        rows.append({"feature": c, "AUC": iv.estimate, "lower": iv.lo, "upper": iv.hi,
                     "excludes chance": not (iv.lo <= 0.5 <= iv.hi)})  # fmt: skip
    t = pd.DataFrame(rows).sort_values("AUC", key=lambda s: (s - 0.5).abs(), ascending=False)
    t.to_csv(OUT / "ch11_single_auc.csv", index=False)
    ch.count("features", len(t), LAKE)
    ch.count("features-off-chance", int(t["excludes chance"].sum()), LAKE)
    ch.census("auc-max-dev", float((t.AUC - 0.5).abs().max()), LAKE, digits=2)
    ch.count("valid-fraud", int(y.sum()), LAKE)
    off = t[t["excludes chance"]]
    if len(off):
        ch.census("auc-off-dev", float((off.AUC - 0.5).abs().max()), LAKE, digits=2)
        ch.census("auc-off-width", float((off.upper - off.lower).max()), LAKE, digits=2)
    top = t.iloc[0]
    ch.census("auc-top", float(top.AUC), LAKE, digits=3)
    render_table(OUT / "ch11_single_auc.csv", "ch11-single-auc", "Each numeric fraud feature alone on the validation "
                 "split: ROC AUC against the fraud label with a DeLong 95\\,\\% interval, ordered by distance from "
                 "chance.", digits=3)  # fmt: skip
    return t


def aml(ch: Chapter, con) -> None:
    g = con.sql("""select segment, country_code, month_start, count(*) n, mad(inflow_usd) mad_in,
                          avg((inflow_usd = 0)::int) zero_share
                   from gold.mart_aml_customer_month group by all""").df()  # fmt: skip
    ch.count("peer-groups", len(g), LAKE)
    ch.count("peer-mad-zero", int((g.mad_in == 0).sum()), LAKE)
    ch.count("peer-majority-zero", int((g.zero_share > 0.5).sum()), LAKE)
    ch.census("peer-zero-min", 100 * float(g.zero_share.min()), LAKE, unit="percent", digits=3)
    r = con.sql("""select count(*), avg((inflow_usd = 0)::int), count(*) filter (where inflow_robust_z_vs_peers is not null),
                          count(*) filter (where list_contains(typology_hits, 'PEER_OUTLIER_INFLOW'))
                   from gold.mart_aml_customer_month""").fetchone()  # fmt: skip
    ch.count("aml-rows", r[0], LAKE)
    ch.census("aml-zero-share", 100 * r[1], LAKE, unit="percent", digits=3)
    ch.count("aml-z-defined", r[2], LAKE)
    ch.count("aml-peer-hits", r[3], LAKE)
    # the conditional alternative: peers computed on months with inflow
    pos = con.sql("""with b as (select * from gold.mart_aml_customer_month where inflow_usd > 0),
                          p as (select segment, country_code, month_start, median(inflow_usd) m, mad(inflow_usd) s
                                from b group by all)
                     select count(*), count(*) filter (where p.s > 0),
                            count(*) filter (where (b.inflow_usd - p.m) / nullif(1.4826 * p.s, 0) >= 6)
                     from b join p using (segment, country_code, month_start)""").fetchone()  # fmt: skip
    ch.count("pos-rows", pos[0], LAKE)
    ch.count("pos-mad-positive", pos[1], LAKE)
    ch.count("pos-flags", pos[2], LAKE)


def marts(ch: Chapter, con) -> None:
    n, card, loan = con.sql("""select count(*), count(*) filter (where eligible_credit_card),
                                      count(*) filter (where eligible_personal_loan) from gold.mart_credit_eligibility""").fetchone()  # fmt: skip
    ch.count("elig-customers", n, LAKE)
    ch.count("elig-card", card, LAKE)
    ch.count("elig-loan", loan, LAKE)
    reasons = con.sql("""select r as reason, count(*) as customers from (select unnest(decline_reasons) r
                         from gold.mart_credit_eligibility) group by 1 order by 2 desc""").df()  # fmt: skip
    reasons["share"] = reasons.customers / n
    min_cell = int(protocol.load()["privacy"]["min_cell"])
    ch.count("reasons-suppressed", int((reasons.customers < min_cell).sum()), LAKE)
    reasons[reasons.customers >= min_cell].to_csv(OUT / "ch11_reasons.csv", index=False)
    ch.census("reason-income-share", 100 * float(reasons.set_index("reason").loc["R04_INSUFFICIENT_INCOME_HISTORY", "share"]),
              LAKE, unit="percent", digits=3)  # fmt: skip
    render_table(OUT / "ch11_reasons.csv", "ch11-reasons", "Credit eligibility: customers declined for each reason "
                 "code (a customer can carry several), and the share of all customers.", digits=3)  # fmt: skip

    ew = con.sql("""select coalesce(dpd_bucket, 'unknown') as bucket, count(*) as products,
                           avg(early_warning_score) as mean_score, quantile_cont(early_warning_score, 0.9) as p90_score
                    from gold.mart_collections_early_warning group by 1""").df()  # fmt: skip
    order = ["current", "unknown", "01-30", "31-60", "61-90", "90+"]
    ew = ew.set_index("bucket").loc[order].reset_index()
    ew.to_csv(OUT / "ch11_early_warning.csv", index=False)
    e = ew.set_index("bucket")
    for b, tag in (
        ("current", "current"),
        ("unknown", "unknown"),
        ("01-30", "dpd30"),
        ("31-60", "dpd60"),
        ("90+", "dpd90"),
    ):
        ch.census(f"ew-{tag}", float(e.loc[b, "mean_score"]), LAKE, digits=3)
    ch.count("ew-unknown-n", int(e.loc["unknown", "products"]), LAKE)
    render_table(OUT / "ch11_early_warning.csv", "ch11-early-warning", "Collections early-warning score by "
                 "days-past-due bucket: products, mean score and the score's ninetieth percentile.", digits=3)  # fmt: skip

    d = con.sql("""select count(*), count(n_candidates), count(*) filter (where n_candidates = 1),
                          count(*) filter (where link_confidence <> 'none'), max(n_candidates)
                   from gold.mart_transaction_disputes""").fetchone()  # fmt: skip
    for tag, v in zip(
        ("disputes", "disputes-candidates", "disputes-unique", "disputes-linked", "disputes-max"),
        d,
        strict=True,
    ):
        ch.count(tag, int(v), LAKE)

    c = con.sql("""select count(*), avg(sent_without_current_consent::int), avg(treatment_delivered::int),
                          avg(outcome_converted::int), avg(already_held_promoted_product::int)
                   from gold.mart_campaign_compliance_uplift""").fetchone()  # fmt: skip
    ch.count("sends", c[0], LAKE)
    for tag, v in zip(("no-consent", "delivered", "converted", "already-held"), c[1:], strict=True):
        ch.census(f"send-{tag}", 100 * v, LAKE, unit="percent", digits=3)


def main() -> None:
    con = duckdb.connect(str(LAKE), read_only=True)
    ch = Chapter(11, "ch11")
    OUT.mkdir(parents=True, exist_ok=True)
    split(ch, con)
    single_auc(ch, con)
    aml(ch, con)
    marts(ch, con)
    proj = REPO / "platform" / "dbt" / "dbt_project.yml"
    days = int(re.search(r"embargo_days:\s*(\d+)", proj.read_text()).group(1))
    ch.constant("embargo-days", days, proj)
    print(f"{len(ch.claims)} claims -> {ch.write()}")


if __name__ == "__main__":
    main()
