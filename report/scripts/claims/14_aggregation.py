"""Chapter 14 · Aggregation: grains, zeros, dispersion, the ecological fallacy, exposure and the target ledger.

Reads the granularity series' stored results (build checks of the day and hour stars, hour-grain sparsity, the
ecological-fallacy correlations, the exposure table, the pooled target ledger) and recomputes from the pinned copy the
zero share and dispersion of the main count at each grain, the occupancy of hour cells against a Poisson process, the
geometric exposure law, and the Benjamini-Hochberg q-values of the target ledger.

    uv run python scripts/claims/14_aggregation.py
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import statsmodels.formula.api as smf

from report_lib import db
from report_lib.build import Chapter
from report_lib.estimators import bh
from report_lib.paths import BUILD, REPO, TABLES
from report_lib.texgen import render_table

MAIN = REPO / "data" / "parquet"
OUT = BUILD / "sources"
FIRST, LAST = "2023-07-01", "2026-05-31"  # the complete months of the delivery window


def checks(ch: Chapter) -> None:
    for name, tag in (("granularity_build_checks", "day"), ("granularity_hour_checks", "hour")):
        p = TABLES / f"{name}.csv"
        c = pd.read_csv(p)
        ch.count(f"checks-{tag}", len(c), p, source_type="table")
        ch.count(f"checks-{tag}-ok", int(c.ok.sum()), p, source_type="table")
        ch.count(f"models-{tag}", int(c.model.nunique()), p, source_type="table")


def grains(ch: Chapter, con) -> None:
    src = MAIN / "transactions.parquet"
    months = pd.date_range(FIRST, LAST, freq="MS")
    n_cust = con.sql("select count(*) from m_customers").fetchone()[0]
    n_prod = con.sql("select count(*) from m_products").fetchone()[0]
    rows = []

    def add(grain, measure, units, counts: pd.Series):
        x = np.zeros(units)
        x[: len(counts)] = counts.to_numpy(float)
        rows.append({"grain": grain, "measure": measure, "rows": units, "zero share": float((x == 0).mean()),
                     "mean": float(x.mean()), "variance / mean": float(x.var(ddof=1) / x.mean())})  # fmt: skip

    w = f"process_date between '{FIRST}' and '{LAST}'"
    for table, measure in (("transactions", "transactions"), ("call_center_interactions", "contacts"),
                           ("complaints", "complaints")):  # fmt: skip
        k = con.sql(f"""select customer_id, date_trunc('month', process_date) m, count(*) n from m_{table}
                        where {w} and customer_id is not null group by all""").df().n  # fmt: skip
        add("customer x month", measure, n_cust * len(months), k)
    k = con.sql(f"""select product_id, date_trunc('month', process_date) m, count(*) n from m_transactions
                    where {w} group by all""").df().n  # fmt: skip
    add("product x month", "transactions", n_prod * len(months), k)
    days = pd.date_range(FIRST, LAST, freq="D")
    k = con.sql(f"""select c.country, t.process_date, count(*) n from m_transactions t join m_customers c using (customer_id)
                    where t.{w} group by all""").df().n  # fmt: skip
    add("market x day", "transactions", 3 * len(days), k)
    agents = con.sql("select count(*) from m_service_agents").fetchone()[0]
    k = con.sql(f"""select agent_id, process_date, count(*) n from m_call_center_interactions
                    where {w} and agent_id is not null group by all""").df().n  # fmt: skip
    add("agent x day", "contacts", agents * len(days), k)
    t = pd.DataFrame(rows)
    t.to_csv(OUT / "ch14_grains.csv", index=False)
    g = t.set_index(["grain", "measure"])
    ch.census(
        "cm-tx-zero",
        100 * g.loc[("customer x month", "transactions"), "zero share"],
        src,
        unit="percent",
        digits=3,
    )
    ch.census(
        "cm-complaint-zero",
        100 * g.loc[("customer x month", "complaints"), "zero share"],
        src,
        unit="percent",
        digits=3,
    )
    ch.census(
        "pm-tx-zero",
        100 * g.loc[("product x month", "transactions"), "zero share"],
        src,
        unit="percent",
        digits=3,
    )
    ch.census(
        "md-tx-zero",
        100 * g.loc[("market x day", "transactions"), "zero share"],
        src,
        unit="percent",
        digits=2,
    )
    ch.census("md-tx-vm", g.loc[("market x day", "transactions"), "variance / mean"], src, digits=3)
    ch.census("ad-vm", g.loc[("agent x day", "contacts"), "variance / mean"], src, digits=3)
    for m, tag in (("contacts", "contact"), ("complaints", "complaint"), ("transactions", "tx")):
        r = g.loc[("customer x month", m)]
        ch.census(f"cm-{tag}-mean", float(r["mean"]), src, digits=3)
        ch.census(
            f"cm-{tag}-pois-zero", 100 * float(np.exp(-r["mean"])), src, unit="percent", digits=3
        )
        ch.census(f"cm-{tag}-vm", float(r["variance / mean"]), src, digits=4)
    ch.census(
        "cm-contact-zero",
        100 * g.loc[("customer x month", "contacts"), "zero share"],
        src,
        unit="percent",
        digits=3,
    )
    ch.count("months", len(months), src)
    render_table(OUT / "ch14_grains.csv", "ch14-grains", "The main count at each grain over the complete months of the "
                 "window: rows of the dense grid, the share of rows with no activity, the mean and the ratio of "
                 "variance to mean (one for a Poisson count).", digits=3)  # fmt: skip


def sparsity(ch: Chapter) -> None:
    p = TABLES / "granularity_hour_sparsity.csv"
    s = pd.read_csv(p)
    s["Poisson occupied"] = 100 - s["Poisson empty %"]
    s["observed minus Poisson"] = s["occupied %"] - s["Poisson occupied"]
    s[["grain", "cells", "events per cell", "occupied %", "Poisson occupied", "observed minus Poisson", "viable"]].to_csv(
        OUT / "ch14_sparsity.csv", index=False)  # fmt: skip
    ch.census("occ-gap-max", float(s["observed minus Poisson"].abs().max()), p, source_type="table", unit="percentage points",
              digits=2)  # fmt: skip
    b = s.set_index("grain")
    worst = s.loc[s["observed minus Poisson"].abs().idxmax()]
    assert worst.grain == "market × channel × hour", worst.grain
    ch.census("occ-gap-other", float(s.drop(index=worst.name)["observed minus Poisson"].abs().max()), p,
              source_type="table", unit="percentage points", digits=2)  # fmt: skip
    ch.census("customer-hour-occ", float(b.loc["customer × hour (transactions)", "occupied %"]), p, source_type="table",
              unit="percent", digits=2)  # fmt: skip
    ch.count("viable-hour", int(s.viable.eq("yes").sum()), p, source_type="table")
    ch.count("hour-grains", len(s), p, source_type="table")
    render_table(OUT / "ch14_sparsity.csv", "ch14-sparsity", "Entity-by-hour grains: cells, events per cell, the share "
                 "of cells with at least one event, the share a Poisson process with the same rate would occupy, and the "
                 "verdict of the hour series (granularity, hour notebook 01).", digits=3)  # fmt: skip


def ecological(ch: Chapter) -> None:
    p = TABLES / "granularity_ecological.csv"
    e = pd.read_csv(p).set_index("grain").iloc[:, 0]
    for key, tag in (("customer × month", "cm"), ("customer (lifetime)", "life"), ("market × day (raw)", "md-raw"),
                     ("market × day (calendar removed)", "md-adj"),
                     ("customer (lifetime, controlling for active months)", "life-adj")):  # fmt: skip
        ch.census(f"eco-{tag}", float(e[key]), p, source_type="table", digits=2)


def exposure(ch: Chapter) -> None:
    p = TABLES / "granularity_exposure.csv"
    x = pd.read_csv(p)
    fit = smf.wls("np.log(dormant) ~ products_held", data=x, weights=x.months).fit()
    r = float(np.exp(fit.params["products_held"]))
    c = float(np.exp(fit.params["Intercept"]))
    ch.census("exp-r", r, p, source_type="table", digits=3)
    ch.census("exp-c", c, p, source_type="table", digits=3)
    ch.census("exp-r2", float(fit.rsquared), p, source_type="table", digits=4)
    indep = x["independent (1 - p)^k"]
    q = float(1 - indep.iloc[0])  # 1 - (1 - p)^1 = p, the per-product monthly use rate
    ch.census("exp-p", q, p, source_type="table", digits=3)
    ch.census(
        "exp-gap",
        float((x.dormant - c * r**x.products_held).abs().max()),
        p,
        source_type="table",
        digits=2,
    )
    ch.census("exp-dormant-1", float(x.dormant.iloc[0]), p, source_type="table", digits=3)
    ch.census("exp-dormant-8", float(x.dormant.iloc[-1]), p, source_type="table", digits=3)


def ledger(ch: Chapter) -> None:
    p = TABLES / "granularity_signal.csv"
    s = pd.read_csv(p)
    ok = s.p_value.notna()
    q = bh.adjust(s.loc[ok, "p_value"].to_numpy())
    agree = np.allclose(q, s.loc[ok, "p_adjusted"].to_numpy(), atol=1e-12)
    ch.count("ledger-targets", len(s), p, source_type="table")
    ch.count("ledger-tested", int(ok.sum()), p, source_type="table")
    ch.count("ledger-q-reproduced", int(agree), p, source_type="table")
    sig = s.loc[ok].assign(q=q)[q <= 0.05]
    ch.count("ledger-discoveries", len(sig), p, source_type="table")
    ch.constant("fdr-level", 5, p, source_type="table", unit="percent")
    ch.count(
        "ledger-grains",
        int(s.grain.str.replace(r" \(.*\)", "", regex=True).nunique()),
        p,
        source_type="table",
    )
    by = (s.assign(grain=s.grain.str.replace(r" \(.*\)", "", regex=True), sig=s.index.isin(sig.index))
          .groupby("grain").agg(targets=("target", "size"), discoveries=("sig", "sum")).reset_index())  # fmt: skip
    by.to_csv(OUT / "ch14_ledger_grains.csv", index=False)
    sig[["grain", "target", "metric", "value", "baseline", "q"]].sort_values("q").to_csv(OUT / "ch14_discoveries.csv",
                                                                                        index=False)  # fmt: skip
    render_table(OUT / "ch14_ledger_grains.csv", "ch14-ledger", "The pooled target ledger of the granularity series by "
                 "grain: targets evaluated and targets whose evidence survives Benjamini-Hochberg control of the false "
                 "discovery rate at five per cent across the whole ledger.")  # fmt: skip
    render_table(OUT / "ch14_discoveries.csv", "ch14-discoveries", "The discoveries of the pooled ledger: the metric "
                 "against its baseline (an AUC against one half, a mean absolute scaled error against the seasonal-naive "
                 "forecast's), with the Benjamini-Hochberg q-value.", digits=3)  # fmt: skip


def main() -> None:
    con = db.connect()
    ch = Chapter(14, "ch14")
    OUT.mkdir(parents=True, exist_ok=True)
    checks(ch)
    grains(ch, con)
    sparsity(ch)
    ecological(ch)
    exposure(ch)
    ledger(ch)
    print(f"{len(ch.claims)} claims -> {ch.write()}")


if __name__ == "__main__":
    main()
