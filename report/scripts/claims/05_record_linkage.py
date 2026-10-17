"""Chapter 5 · Record linkage and comparable rows.

Re-runs notebook 04's Fellegi-Sunter linkage of customers (same blocking, fields, EM and 10-bit threshold) with one
change: the random cross-copy pairs that estimate chance agreement are a deterministic hash-ordered sample instead of
an unseeded DuckDB sample, so the weights reproduce exactly. Re-runs the clone search with placebo windows and
notebook 05's identity and credit-score checks; reads the stored alignment and comparison tables.

    uv run python scripts/claims/05_record_linkage.py
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.metrics import roc_auc_score

from report_lib import db
from report_lib.build import Chapter
from report_lib.paths import BUILD, REPO, TABLES
from report_lib.texgen import render_table

MAIN, BACKUP = REPO / "data" / "parquet", REPO / "data" / "parquet_backup"
OUT = BUILD / "sources"
FIELDS = ["document_number", "first_name", "last_name", "date_of_birth", "email", "mobile_phone", "city", "country",
          "gender"]  # fmt: skip
HELD = ["address", "landline_phone", "registration_date", "credit_score", "segment", "occupation"]
IDENTITY = ["document_number", "first_name", "last_name", "date_of_birth"]
CUT = 10.0  # bits, notebook 04
SEED = "2026"


def random_pairs_sql(select: str) -> str:
    """Agreement over a fixed set of random cross-copy pairs: the main and backup customers with the lowest seeded
    hash (deterministic, unlike an unseeded sample)."""
    return f"""select {select} from
        (select * from m_customers order by hash(customer_id || '{SEED}') limit 20000) m
        cross join (select * from b_customers order by hash(customer_id || '{SEED}m') limit 2000) b"""


def em_m(A: np.ndarray, u: np.ndarray, iters: int = 300, p0: float = 0.5):
    """EM for the m-probabilities and the match prevalence with u fixed (notebook 04)."""
    m, p = np.full(A.shape[1], 0.9), p0
    for _ in range(iters):
        lm = np.log(p) + (A * np.log(m) + (1 - A) * np.log(1 - m)).sum(1)
        lu = np.log(1 - p) + (A * np.log(u) + (1 - A) * np.log(1 - u)).sum(1)
        g = 1 / (1 + np.exp(np.clip(lu - lm, -60, 60)))
        p = float(np.clip(g.mean(), 1e-3, 0.99))
        m = np.clip((g[:, None] * A).sum(0) / g.sum(), 1e-4, 1 - 1e-4)
    return m, p, g


def main() -> None:
    con = db.connect()
    ch = Chapter(5, "ch05")
    OUT.mkdir(parents=True, exist_ok=True)
    cust = MAIN / "customers.parquet"

    # --- customers sharing an ID: how many agree on the identity fields (notebook 05, section 1)
    agree = " + ".join(f"coalesce((m.{f} = b.{f})::int, 0)" for f in IDENTITY)
    k = (
        con.sql(f"select {agree} k from m_customers m join b_customers b using (customer_id)")
        .df()
        .k
    )
    ch.count("shared-id", len(k), cust)
    ch.census("shared-id-all-four", 100 * (k == 4).mean(), cust, unit="percent", digits=3)
    ch.census("shared-id-none", 100 * (k == 0).mean(), cust, unit="percent", digits=3)
    ch.census("shared-id-partial", 100 * k.between(1, 3).mean(), cust, unit="percent", digits=2)
    ch.count("shared-id-none-n", int((k == 0).sum()), cust)

    # --- Fellegi-Sunter linkage (notebook 04, L2)
    cmp = ",\n".join(f"(m.{f} = b.{f})::int as a_{f}" for f in FIELDS)
    cand = con.sql(f"""
        with c as (
          select m.customer_id mid, b.customer_id bid from m_customers m join b_customers b using (document_number)
          union select m.customer_id, b.customer_id from m_customers m join b_customers b
                on m.date_of_birth = b.date_of_birth and m.last_name = b.last_name
          union select m.customer_id, b.customer_id from m_customers m join b_customers b using (mobile_phone)
          union select m.customer_id, b.customer_id from m_customers m join b_customers b
                on m.email = b.email and m.date_of_birth = b.date_of_birth)
        select c.mid, c.bid, (c.mid = c.bid)::int same_id, {cmp}
        from c join m_customers m on m.customer_id = c.mid join b_customers b on b.customer_id = c.bid
        order by c.mid, c.bid""").df().fillna(0)  # fmt: skip
    A = cand[[f"a_{f}" for f in FIELDS]].to_numpy(dtype=float)
    u = con.sql(
        random_pairs_sql(", ".join(f"avg(coalesce((m.{f} = b.{f})::int, 0)) a_{f}" for f in FIELDS))
    ).df()
    u = np.clip(u.iloc[0].to_numpy(dtype=float), 1e-6, 1 - 1e-6)
    m, p, _ = em_m(A, u)
    w_agree, w_dis = np.log2(m / u), np.log2((1 - m) / (1 - u))
    cand["score"] = (A * w_agree + (1 - A) * w_dis).sum(1)
    hist = (cand.assign(bin=np.floor(cand.score), cls=np.where(cand.same_id == 1, "shares an ID", "different ID"))
            .groupby(["cls", "bin"]).size().rename("n").reset_index().sort_values(["cls", "bin"]))  # fmt: skip
    hist.to_csv(OUT / "ch05_fs_scores.csv", index=False)
    weights = pd.DataFrame(
        {"field": FIELDS, "m": m, "u": u, "agree_bits": w_agree, "disagree_bits": w_dis}
    )
    w_path = OUT / "ch05_fs_weights.csv"
    weights.to_csv(w_path, index=False)
    ch.count("candidates", len(cand), cust)
    ch.count("candidates-same-id", int(cand.same_id.sum()), cust)
    ch.census("em-prevalence", p, cust, digits=3)
    for f in ("document_number", "mobile_phone", "date_of_birth", "country", "gender"):
        ch.census(f"w-{f.replace('_', '-')}", float(weights.set_index("field").loc[f, "agree_bits"]), w_path,
                  digits=3)  # fmt: skip
    ch.census("auc-vs-id", roc_auc_score(cand.same_id, cand.score), cust, digits=2)
    linked = cand[cand.score >= CUT]
    ch.count("cut", CUT, w_path)
    ch.count("linked-people", linked.mid.nunique(), cust)
    ch.census("linked-share", 100 * linked.mid.nunique() / 150000, cust, unit="percent", digits=2)
    ch.count("linked-same-id", int((linked.same_id == 1).sum()), cust)
    ch.count("linked-other-id", int((linked.same_id == 0).sum()), cust)
    sens = pd.DataFrame([{"cut_bits": c, "linked_people": cand[cand.score >= c].mid.nunique(),
                          "different_id_pairs": int(((cand.score >= c) & (cand.same_id == 0)).sum())}
                         for c in (5.0, 10.0, 15.0, 20.0)])  # fmt: skip
    sens_path = OUT / "ch05_fs_sensitivity.csv"
    sens.to_csv(sens_path, index=False)
    for c in (5, 15):
        ch.count(
            f"linked-at-{c}",
            int(sens.set_index("cut_bits").loc[float(c), "linked_people"]),
            sens_path,
        )

    # --- blind validation on fields the score never saw
    con.register("linked_pairs", linked[["mid", "bid"]])
    sel = ", ".join(f"avg(coalesce((m.{f} = b.{f})::int, 0)) {f}" for f in HELD)
    base = con.sql(random_pairs_sql(sel)).df().iloc[0]
    got = con.sql(f"""select {sel} from linked_pairs s join m_customers m on m.customer_id = s.mid
                      join b_customers b on b.customer_id = s.bid""").df().iloc[0]  # fmt: skip
    val = pd.DataFrame({"field": HELD, "linked_pct": 100 * got.to_numpy(dtype=float),
                        "random_pct": 100 * base.to_numpy(dtype=float)})  # fmt: skip
    val["lift"] = val.linked_pct / val.random_pct.replace(0, np.nan)
    v_path = OUT / "ch05_fs_validation.csv"
    val.to_csv(v_path, index=False)
    vv = val.set_index("field")
    for f in ("address", "registration_date", "landline_phone", "segment"):
        ch.census(
            f"held-{f.replace('_', '-')}", vv.loc[f, "linked_pct"], v_path, unit="percent", digits=3
        )
    ch.census(
        "held-address-random", vv.loc["address", "random_pct"], v_path, unit="percent", digits=2
    )
    ch.census("held-segment-lift", vv.loc["segment", "lift"], v_path, digits=2)

    # --- credit-score refresh among same-person customers (notebook 05, sections 2-3)
    same = con.sql(f"""select m.credit_score ms, b.credit_score bs, (m.last_updated = b.last_updated) same_upd
                       from m_customers m join b_customers b using (customer_id)
                       where {' and '.join(f'm.{f} = b.{f}' for f in IDENTITY)}""").df()  # fmt: skip
    scored = same.dropna(subset=["ms", "bs"])
    moved = scored[scored.ms != scored.bs]
    ch.count("same-person", len(same), cust)
    ch.count("scored", len(scored), cust)
    ch.census("rescored", 100 * len(moved) / len(scored), cust, unit="percent", digits=3)
    ch.census("rescore-median-abs", float((moved.bs - moved.ms).abs().median()), cust, digits=3)
    ch.census("rescore-mean", float((moved.bs - moved.ms).mean()), cust, digits=2)
    ch.census("rescored-same-updated", 100 * moved.same_upd.mean(), cust, unit="percent", digits=3)
    ch.census("unchanged-same-updated", 100 * scored[scored.ms == scored.bs].same_upd.mean(), cust, unit="percent",
              digits=3)  # fmt: skip

    # --- clones found without IDs: fingerprint + drift window, with placebo windows (notebook 04, L4)
    pairs = con.sql("""select m.transaction_id pk, strftime(m.process_date, '%Y-%m') ym,
               date_diff('day', m.process_date, b.process_date) k,
               (m.amount = b.amount and m.currency = b.currency and m.transaction_type = b.transaction_type
                and m.channel = b.channel and m.fraud_score is not distinct from b.fraud_score
                and m.merchant_name is not distinct from b.merchant_name) clone
        from m_transactions m join b_transactions b using (transaction_id)""").df()
    med = pairs.groupby("ym").k.median().rename("med").reset_index()
    con.register("med_tbl", med)
    cols = "amount, currency, transaction_type, channel, transaction_country, merchant_name, fraud_score"

    def window(shift: int) -> pd.DataFrame:
        return con.sql(f"""
            with a as (select transaction_id mid, process_date d, strftime(process_date, '%Y-%m') ym, hash({cols}) h
                       from m_transactions),
                 b as (select transaction_id bid, process_date d, hash({cols}) h from b_transactions)
            select a.mid, b.bid from a join b using (h) join med_tbl t on t.ym = a.ym
            where abs(date_diff('day', a.d, b.d) - t.med - ({shift})) <= 3""").df()  # fmt: skip

    found = window(0)
    id_clones = set(pairs.loc[pairs.clone, "pk"])
    same_id = found[found.mid == found.bid]
    placebo = [len(window(s)) for s in (120, 240, -120)]
    ch.count("window-pairs", len(found), BACKUP / "transactions.parquet")
    ch.count(
        "window-other-id", int((found.mid != found.bid).sum()), BACKUP / "transactions.parquet"
    )
    ch.census("window-recall", 100 * len(set(same_id.mid) & id_clones) / len(id_clones), BACKUP / "transactions.parquet",
              unit="percent", digits=3)  # fmt: skip
    ch.census("placebo-mean", float(np.mean(placebo)), BACKUP / "transactions.parquet", digits=3)

    # --- complaints as the negative control: columns equal in every row
    comp_cols = [
        c[0] for c in con.sql("describe m_complaints").fetchall() if c[0] != "complaint_id"
    ]
    eq = con.sql("select " + ", ".join(f"avg((m.{c} is not distinct from b.{c})::int) {c}" for c in comp_cols)
                 + " from m_complaints m join b_complaints b using (complaint_id)").df().iloc[0]  # fmt: skip
    ch.count("complaint-columns", len(comp_cols), MAIN / "complaints.parquet")
    ch.count("complaint-columns-equal", int((eq == 1).sum()), MAIN / "complaints.parquet")
    ch.census("complaint-customer-equal", 100 * eq["customer_id"], MAIN / "complaints.parquet", unit="percent",
              digits=3)  # fmt: skip

    # --- stored tables of notebooks 04 and 05
    l1 = pd.read_csv(TABLES / "alignment_l1_date_drift.csv").set_index("table")
    for t in ("transactions", "campaign_sends", "digital_events"):
        s = t.replace("_", "-")
        for col, topic in (("MAE_no_shift", "mae-raw"), ("MAE_global_constant", "mae-const"),
                           ("MAE_drift_model", "mae-drift")):  # fmt: skip
            ch.census(f"{topic}-{s}", l1.loc[t, col], TABLES / "alignment_l1_date_drift.csv", source_type="table",
                      digits=2)  # fmt: skip
    ch.census("within-day-transactions", l1.loc["transactions", "within_1d_after_drift_pct"],
              TABLES / "alignment_l1_date_drift.csv", source_type="table", unit="percent", digits=3)  # fmt: skip
    l3 = pd.read_csv(TABLES / "alignment_l3_natural_keys.csv").set_index("table")
    p3 = TABLES / "alignment_l3_natural_keys.csv"
    ch.count("products-shared-id", l3.loc["products", "shared_ids"], p3, source_type="table")
    ch.count("products-nk-pairs", l3.loc["products", "natural_key_pairs"], p3, source_type="table")
    ch.census("products-id-same-object", l3.loc["products", "id_pairs_that_are_same_object_pct"], p3,
              source_type="table", unit="percent", digits=3)  # fmt: skip
    ch.count("products-extra", int(l3.loc["products", "natural_key_pairs"] - l3.loc["products",
             "natural_key_pairs_also_same_id"]), p3, source_type="table")  # fmt: skip
    red = pd.read_csv(TABLES / "product_currency_redenomination.csv")
    pr = TABLES / "product_currency_redenomination.csv"
    get = lambda a, b, col: float(red[(red.mc == a) & (red.bc == b)][col].iloc[0])  # noqa: E731
    ch.census(
        "rate-cop",
        get("USD", "COP", "median ratio (backup ÷ main)"),
        pr,
        source_type="table",
        digits=4,
    )
    ch.census(
        "rate-ars",
        get("USD", "ARS", "median ratio (backup ÷ main)"),
        pr,
        source_type="table",
        digits=3,
    )
    ch.census("redenominated", 100 * red[red.mc != red.bc].pairs.sum() / red.pairs.sum(), pr, source_type="table",
              unit="percent", digits=3)  # fmt: skip
    ch.census(
        "log-ratio-sd-min", float(red["sd of log10 ratio"].min()), pr, source_type="table", digits=2
    )
    ch.census(
        "log-ratio-sd-max", float(red["sd of log10 ratio"].max()), pr, source_type="table", digits=2
    )
    ca = pd.read_csv(TABLES / "transaction_clone_agreement.csv").set_index("field").agreement
    pc = TABLES / "transaction_clone_agreement.csv"
    ch.census(
        "clone-same-city", 100 * ca["same city"], pc, source_type="table", unit="percent", digits=3
    )
    ch.census(
        "clone-same-branch",
        100 * ca["same branch"],
        pc,
        source_type="table",
        unit="percent",
        digits=3,
    )
    tx = pd.read_csv(TABLES / "customers_mismatch_taxonomy.csv").set_index("field")
    ch.census("edited-city-changed", tx.loc["city", "changed_pct"], TABLES / "customers_mismatch_taxonomy.csv",
              source_type="table", unit="percent", digits=3)  # fmt: skip

    render_table(w_path, "ch05-fs-weights", "Fellegi-Sunter parameters re-estimated with a deterministic random "
                 "baseline: agreement probability among matches (m) and by chance (u), and the weights in bits.",
                 digits=3)  # fmt: skip
    render_table(v_path, "ch05-validation", "Blind validation: agreement on fields the linkage never used, among "
                 "linked pairs and among random cross-copy pairs.", digits=3)  # fmt: skip
    render_table(
        sens_path,
        "ch05-sensitivity",
        "Linked customers at thresholds around the notebook's choice.",
    )
    render_table(TABLES / "alignment_l1_date_drift.csv", "ch05-drift-alignment", "Date alignment of shared keys: "
                 "mean absolute error in days with no shift, a global constant and the drift model evaluated "
                 "leave-one-month-out (notebook 04).", digits=3)  # fmt: skip
    render_table(pr, "ch05-redenomination", "Products paired by number: balance ratio by currency pair "
                 "(notebook 05).", digits=4)  # fmt: skip
    print(f"{len(ch.claims)} claims -> {ch.write()}")


if __name__ == "__main__":
    main()
