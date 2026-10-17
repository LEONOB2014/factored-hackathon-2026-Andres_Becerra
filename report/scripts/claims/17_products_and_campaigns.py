"""Chapter 17 · Products and campaigns.

From the granularity series' stored tables:

* campaigns: dispersion of conversion between campaigns overall and within each channel (Pearson chi-square / df);
* decision cells: empirical-Bayes shrinkage of cell conversion rates (beta-binomial prior fitted on the fit period),
  scored on the held-out period by log loss per send against the global, channel and raw cell rates, with a paired
  bootstrap over cells for the differences;
* allocation policies, the category mix, sequences, sessions and sends (stored).

    uv run python scripts/claims/17_products_and_campaigns.py
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from report_lib import db
from report_lib.build import Chapter
from report_lib.eda import granularity as g
from report_lib.estimators import bh
from report_lib.estimators.intervals import Interval
from report_lib.paths import BUILD, REPO, TABLES
from report_lib.texgen import render_table

OUT = BUILD / "sources"
MAIN = REPO / "data" / "parquet"
EPS = 1e-5
B = 2000


def dispersion(k: np.ndarray, n: np.ndarray) -> float:
    p = k.sum() / n.sum()
    return float((((k - n * p) ** 2) / (n * p * (1 - p))).sum() / (len(k) - 1))


def campaigns(ch: Chapter) -> None:
    p = TABLES / "granularity_campaigns.csv"
    c = pd.read_csv(p)
    tracked = c[c.opened > 0]
    ch.count("campaigns", len(c), p, source_type="table")
    ch.count("campaigns-untracked", int((c.opened == 0).sum()), p, source_type="table")
    ch.count(
        "untracked-conversions",
        int(c.loc[c.opened == 0, "conversions"].sum()),
        p,
        source_type="table",
    )
    k, n = tracked.conversions.to_numpy(float), tracked.delivered.to_numpy(float)
    ch.census("phi-all", dispersion(k, n), p, source_type="table", digits=3)
    within = []
    for t, d in tracked.groupby("campaign_type"):
        if len(d) > 2:
            within.append(
                (t, dispersion(d.conversions.to_numpy(float), d.delivered.to_numpy(float)), len(d))
            )
    w = pd.DataFrame(within, columns=["channel", "phi", "campaigns"])
    ch.census("phi-within-max", float(w.phi.max()), p, source_type="table", digits=3)
    ch.census("phi-within-min", float(w.phi.min()), p, source_type="table", digits=3)
    ch.count("channels-tracked", len(w), p, source_type="table")
    rate = tracked.groupby("campaign_type").apply(
        lambda d: d.conversions.sum() / d.delivered.sum(), include_groups=False
    )
    ch.census("rate-max", 100 * float(rate.max()), p, source_type="table", unit="percent", digits=3)
    ch.census("rate-min", 100 * float(rate.min()), p, source_type="table", unit="percent", digits=3)
    m = pd.read_csv(TABLES / "granularity_targets_marketing.csv").set_index("target")
    mp = TABLES / "granularity_targets_marketing.csv"
    ch.census(
        "launch-rho",
        float(m.loc["campaign conversion from launch attributes", "value"]),
        mp,
        source_type="table",
        digits=3,
    )
    ch.census("fatigue-slope", float(m.loc["contact fatigue (prior sends lower conversion)", "value"]), mp,
              source_type="table", digits=2)  # fmt: skip
    ch.census("fatigue-p", float(m.loc["contact fatigue (prior sends lower conversion)", "p_value"]), mp, source_type="table",
              digits=2)  # fmt: skip


def cells(ch: Chapter) -> None:
    p = TABLES / "granularity_time_cells.csv"
    c = pd.read_csv(p)
    c = c[c.tracked & (c.sends_ho > 0) & (c.sends_fit > 0)].reset_index(
        drop=True
    )  # cells seen in both periods
    alpha, beta_ = g.beta_binomial_fit(c.conversions_fit.to_numpy(), c.sends_fit.to_numpy())
    kappa = alpha + beta_
    glob = c.conversions_fit.sum() / c.sends_fit.sum()
    chan = c.groupby("send_channel").apply(
        lambda d: d.conversions_fit.sum() / d.sends_fit.sum(), include_groups=False
    )
    cr = c.send_channel.map(chan)
    s, n = c.conversions_fit, c.sends_fit
    pred = pd.DataFrame({"global rate": glob, "channel rate": cr, "raw cell rate": s / n,
                         "EB, global prior": (s + alpha) / (n + kappa),
                         "EB, channel prior": (s + kappa * cr) / (n + kappa)}).clip(EPS, 1 - EPS)  # fmt: skip
    yc, yn = c.conversions_ho.to_numpy(float), c.sends_ho.to_numpy(float)

    def ll_cells(pr: np.ndarray) -> np.ndarray:
        return -(yc * np.log(pr) + (yn - yc) * np.log(1 - pr))

    L = {k: ll_cells(v.to_numpy()) for k, v in pred.items()}
    rng = np.random.default_rng(17)
    idx = rng.integers(0, len(c), (B, len(c)))
    rows = []
    base = L["global rate"]
    for k, v in L.items():
        skill = 1 - v.sum() / base.sum()
        draws = 1 - v[idx].sum(1) / base[idx].sum(1)
        lo, hi = np.quantile(draws, [0.025, 0.975])
        rows.append({"predictor": k, "log loss per send": v.sum() / yn.sum(), "skill vs global": skill,
                     "lower": lo, "upper": hi})  # fmt: skip
    t = pd.DataFrame(rows)
    t.to_csv(OUT / "ch17_cells.csv", index=False)
    tags = {
        "channel rate": "channel",
        "raw cell rate": "raw",
        "EB, global prior": "eb",
        "EB, channel prior": "ebc",
    }
    for k, tag in tags.items():
        r = t.set_index("predictor").loc[k]
        ch.difference(f"skill-{tag}", Interval(float(r["skill vs global"]), float(r.lower), float(r.upper), "cluster-bootstrap"),
                      p, "cell", source_type="table", digits=2)  # fmt: skip
    d = L["EB, channel prior"] - L["channel rate"]
    draws = d[idx].sum(1) / yn[idx].sum(1)
    lo, hi = np.quantile(draws, [0.025, 0.975])
    ch.difference("ebc-minus-channel", Interval(float(d.sum() / yn.sum()), float(lo), float(hi), "cluster-bootstrap"), p,
                  "cell", source_type="table", digits=2)  # fmt: skip
    ch.count("cells", len(c), p, source_type="table")
    ch.census("kappa", float(kappa), p, source_type="table", digits=3)
    ch.census("median-sends", float(np.median(n)), p, source_type="table")
    ch.census(
        "prior-mean", 100 * float(alpha / kappa), p, source_type="table", unit="percent", digits=3
    )
    render_table(OUT / "ch17_cells.csv", "ch17-cells", "Predicting each decision cell's held-out conversion rate from "
                 "its fit-period data: log loss per held-out send and the skill against the global rate, with a 95\\,\\% "
                 "interval from resampling cells. EB: empirical-Bayes posterior mean under a beta prior fitted to the "
                 "cells, centred on the global or on the channel rate.", digits=4)  # fmt: skip


def allocation(ch: Chapter) -> None:
    p = TABLES / "granularity_time_allocation.csv"
    a = pd.read_csv(p).set_index("policy")
    act = a.loc["actual mix"]
    ch.census("alloc-actual-roi", float(act.roi), p, source_type="table", digits=3)
    ch.census(
        "alloc-placebo", float(act.placebo_mean_conversions), p, source_type="table", digits=4
    )
    ch.census("alloc-actual-conv", float(act.conversions), p, source_type="table", digits=4)
    for k, tag in (("greedy on channel rate", "channel"), ("greedy on EB cell rate", "eb"), ("greedy on raw cell rate", "raw"),
                   ("proportional tilt to EB rate", "tilt")):  # fmt: skip
        r = a.loc[k]
        ch.census(
            f"alloc-{tag}-conv",
            float(r["conversions vs actual %"]),
            p,
            source_type="table",
            unit="percent",
            digits=3,
        )
        ch.census(
            f"alloc-{tag}-cost",
            float(r["cost vs actual %"]),
            p,
            source_type="table",
            unit="percent",
            digits=3,
        )
        ch.census(f"alloc-{tag}-roi", float(r.roi), p, source_type="table", digits=3)
    a.reset_index()[["policy", "conversions", "cost", "roi", "conversions vs actual %", "cost vs actual %", "sends to SMS %"]].to_csv(
        OUT / "ch17_allocation.csv", index=False)  # fmt: skip
    render_table(OUT / "ch17_allocation.csv", "ch17-allocation", "Replaying send allocation policies on the held-out "
                 "months with each cell's realised rates: conversions, cost, return on cost, changes against the actual "
                 "mix and the share of sends given to SMS (granularity, time notebook 05). A replay on observed cells, "
                 "not a causal estimate.", digits=3)  # fmt: skip


def stored(ch: Chapter, con) -> None:
    cat = pd.read_csv(TABLES / "granularity_categories.csv")
    cp = TABLES / "granularity_categories.csv"
    k = con.sql("select count(distinct transaction_category) from m_transactions").fetchone()[0]
    ch.count("categories", k, MAIN / "transactions.parquet")
    ch.census("hhi-uniform", 10000 / k, MAIN / "transactions.parquet", digits=4)
    ch.constant("hhi-max", 10000, cp, source_type="table")
    ch.constant("psi-months", 6, cp, source_type="table")
    ch.census("hhi-mean", float(cat["mean HHI"].mean()), cp, source_type="table", digits=4)
    ch.census(
        "cat-psi-max",
        float(cat["PSI first vs last 6 months"].max()),
        cp,
        source_type="table",
        digits=2,
    )
    ch.census("cat-p-min", float(cat.p_value.min()), cp, source_type="table", digits=2)

    sq = pd.read_csv(TABLES / "granularity_time_sequences.csv")
    sp = TABLES / "granularity_time_sequences.csv"
    q = bh.adjust(sq.p_value.to_numpy())
    ch.count("seq-tests", len(sq), sp, source_type="table")
    ch.count("seq-raw-sig", int((sq.p_value < 0.05).sum()), sp, source_type="table")
    ch.count("seq-bh-sig", int((q <= 0.05).sum()), sp, source_type="table")
    ch.census("seq-ratio-min", float(sq["after / before"].min()), sp, source_type="table", digits=2)
    ch.census("seq-ratio-max", float(sq["after / before"].max()), sp, source_type="table", digits=2)

    sf = pd.read_csv(TABLES / "granularity_hour_session_funnel.csv")
    fp = TABLES / "granularity_hour_session_funnel.csv"
    ch.census("funnel-v", float(sf.iloc[0].effect), fp, source_type="table", digits=2)
    ch.census("error-or", float(sf.iloc[1].statistic), fp, source_type="table", digits=3)
    ch.census("error-p", float(sf.iloc[1].p_value), fp, source_type="table", digits=2)
    sd = pd.read_csv(TABLES / "granularity_hour_send_delay.csv")
    dp = TABLES / "granularity_hour_send_delay.csv"
    ch.census("delay-ks-p", float(sd.iloc[0].p_value), dp, source_type="table", digits=2)
    ch.census("sendhour-p", float(sd.iloc[2].p_value), dp, source_type="table", digits=2)

    tp = pd.read_csv(TABLES / "granularity_targets_product.csv")
    pp = TABLES / "granularity_targets_product.csv"
    ch.constant("prod-horizon", 3, pp, source_type="table")
    ch.census("prod-dormant-auc", float(tp.iloc[0].value), pp, source_type="table", digits=3)
    ch.census("prod-dpd-auc", float(tp.iloc[1].value), pp, source_type="table", digits=3)
    ch.census("prod-dpd-auc-lo", float(tp.iloc[1].ci_low), pp, source_type="table", digits=3)
    ch.census("prod-dpd-auc-hi", float(tp.iloc[1].ci_high), pp, source_type="table", digits=3)


def main() -> None:
    ch = Chapter(17, "ch17")
    OUT.mkdir(parents=True, exist_ok=True)
    campaigns(ch)
    cells(ch)
    allocation(ch)
    stored(ch, db.connect())
    print(f"{len(ch.claims)} claims -> {ch.write()}")


if __name__ == "__main__":
    main()
