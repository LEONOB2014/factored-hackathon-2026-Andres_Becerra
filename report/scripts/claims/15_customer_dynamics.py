"""Chapter 15 · Customer dynamics: the monthly Markov chain, lapse survival, value and hours.

Recomputes from the pinned copy, on the complete months of the window:

* the customer-month activity chain (dormant: no transaction; light: one or two; active: three or more), its
  stationary distribution and sojourn times, and a likelihood-ratio test of the first-order Markov property against
  a second-order chain, with its effect size;
* the AUC of next-month dormancy (customers active this month) from exposure alone (products held) and from this
  month's transactions alone, with DeLong intervals, against the series' model;
* the concentration of lifetime spend (Gini, top-decile share).

Reads the stored survival summary, the cross-process lifts and the hour-profile tests of the series.

    uv run python scripts/claims/15_customer_dynamics.py
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from scipy import stats

from report_lib import db
from report_lib.build import Chapter
from report_lib.estimators import intervals
from report_lib.estimators.auc import delong
from report_lib.paths import BUILD, REPO, TABLES
from report_lib.texgen import render_table

MAIN = REPO / "data" / "parquet"
OUT = BUILD / "sources"
FIRST, LAST = "2023-07-01", "2026-05-31"
STATES = ["dormant", "light", "active"]


def grid(con) -> pd.DataFrame:
    """Dense customer x month grid of transaction counts and products held at the start of the month."""
    months = pd.date_range(FIRST, LAST, freq="MS")
    con.register("months_df", pd.DataFrame({"m": months}))
    return con.sql(f"""
        with tx as (select customer_id, date_trunc('month', process_date) as m, count(*) as n
                    from m_transactions where process_date between '{FIRST}' and '{LAST}' group by all),
             g as (select c.customer_id, cast(mo.m as date) as m from m_customers c cross join months_df mo),
             p as (select g.customer_id, g.m, count(pr.product_id) as held
                   from g left join m_products pr on pr.customer_id = g.customer_id and pr.opening_date < g.m
                   group by all)
        select g.customer_id, g.m, coalesce(tx.n, 0) as n, p.held
        from g left join tx on tx.customer_id = g.customer_id and tx.m = g.m
        join p on p.customer_id = g.customer_id and p.m = g.m
        order by g.customer_id, g.m""").df()  # fmt: skip


def effect(i, j, k) -> float:
    """Mean over (previous, current) pairs, weighted by their frequency, of the largest change in a next-state
    probability when the previous state is known: zero for a first-order chain."""
    M = np.zeros((3, 3, 3))
    np.add.at(M, (i, j, k), 1)
    w = M.sum(2)
    with np.errstate(invalid="ignore", divide="ignore"):
        p2 = M / w[:, :, None]
        Njk = M.sum(0)
        p1 = Njk / Njk.sum(1, keepdims=True)
    d = np.nan_to_num(np.abs(p2 - p1[None, :, :]).max(2))
    return float((d * w).sum() / w.sum()) if w.sum() else float("nan")


def markov(ch: Chapter, g: pd.DataFrame) -> None:
    src = MAIN / "transactions.parquet"
    s = np.select([g.n == 0, g.n <= 2], [0, 1], 2)
    cust = g.customer_id.to_numpy()
    same1 = cust[1:] == cust[:-1]
    a, b = s[:-1][same1], s[1:][same1]
    N = np.zeros((3, 3))
    np.add.at(N, (a, b), 1)
    P = N / N.sum(1, keepdims=True)
    w, v = np.linalg.eig(P.T)
    pi = np.real(v[:, np.argmin(np.abs(w - 1))])
    pi = pi / pi.sum()
    observed = np.bincount(s, minlength=3) / len(s)
    rows = []
    for i, st in enumerate(STATES):
        rows.append({"state": st, **{f"to {t}": P[i, j] for j, t in enumerate(STATES)}, "stationary": pi[i],
                     "observed": observed[i], "sojourn (months)": 1 / (1 - P[i, i])})  # fmt: skip
        ch.census(f"pi-{st}", float(pi[i]), src, digits=3)
        ch.census(f"obs-{st}", float(observed[i]), src, digits=3)
        ch.census(f"sojourn-{st}", float(1 / (1 - P[i, i])), src, digits=3)
    ch.census("p-dd", float(P[0, 0]), src, digits=3)
    ch.census("p-da", float(1 - P[0, 0]), src, digits=3)
    ch.census("p-aa", float(P[2, 2]), src, digits=3)
    pd.DataFrame(rows).to_csv(OUT / "ch15_markov.csv", index=False)
    ch.count("transitions", int(N.sum()), src)
    ch.constant(
        "light-max",
        2,
        REPO / "eda" / "notebooks" / "granularity" / "02_customer_month.py",
        source_type="notebook",
    )

    # second order: does the state before last change the next state, given the last?
    same2 = (cust[2:] == cust[1:-1]) & (cust[1:-1] == cust[:-2])
    i, j, k = s[:-2][same2], s[1:-1][same2], s[2:][same2]
    M = np.zeros((3, 3, 3))
    np.add.at(M, (i, j, k), 1)
    Njk = M.sum(0)
    Nij = M.sum(2)
    exp = Nij[:, :, None] * (Njk / Njk.sum(1, keepdims=True))[None, :, :]
    mask = M > 0
    g2 = float(2 * (M[mask] * np.log(M[mask] / exp[mask])).sum())
    df = 3 * 2 * 2
    ch.census("g2", g2, src, digits=4)
    ch.count("g2-df", df, src)
    ch.census("g2-p", float(stats.chi2.sf(g2, df)), src, digits=2)
    ch.census("g2-effect", effect(i, j, k), src, digits=2)
    # the same effect within groups of customers with a similar overall activity rate (a diagnostic: the rate is
    # computed over the whole window, so it is not a predictor)
    rate = g.groupby("customer_id").n.transform("mean").to_numpy()[1:-1][same2]
    dec = pd.qcut(rate, 10, labels=False, duplicates="drop")
    within = [effect(i[dec == d], j[dec == d], k[dec == d]) for d in np.unique(dec)]
    within = [w for w in within if np.isfinite(w)]
    ch.census("g2-effect-within-max", float(max(within)), src, digits=2)
    ch.census("g2-effect-within-median", float(np.median(within)), src, digits=2)
    ch.count("rate-groups", len(within), src)
    ch.count("triples", int(M.sum()), src)
    render_table(OUT / "ch15_markov.csv", "ch15-markov", "Customer activity as a monthly Markov chain: transition "
                 "probabilities from each state, the stationary distribution, the observed share of customer-months "
                 "in each state, and the expected stay in a state.", digits=3)  # fmt: skip


def dormancy(ch: Chapter, g: pd.DataFrame) -> None:
    src = MAIN / "transactions.parquet"
    g = g.assign(next_n=g.groupby("customer_id").n.shift(-1)).dropna(subset=["next_n"])
    act = g[g.n > 0]
    y = (act.next_n == 0).to_numpy()
    rng = np.random.default_rng(15)
    pick = rng.choice(len(act), size=min(300_000, len(act)), replace=False)
    yy = y[pick]
    for tag, x in (("held", -act.held.to_numpy(float)), ("ntx", -act.n.to_numpy(float))):
        iv = delong(yy, x[pick])
        ch.metric(f"auc-{tag}", iv, len(pick), src, digits=3)
    ch.census("dormant-base", float(y.mean()), src, digits=3)
    st = pd.read_csv(TABLES / "granularity_targets_customer_month.csv")
    row = st[st.target.str.startswith("dormant")].iloc[0]
    sp = TABLES / "granularity_targets_customer_month.csv"
    ch.census("model-auc", float(row.value), sp, source_type="table", digits=3)
    ch.census("model-best-single", float(row.best_single_value), sp, source_type="table", digits=3)


def value(ch: Chapter, con) -> None:
    src = MAIN / "transactions.parquet"
    v = con.sql("""select c.customer_id,
                          coalesce(sum(coalesce(t.amount_usd, case when t.currency = 'USD' then t.amount end))
                                   filter (where t.transaction_type not in ('Deposit', 'Adjustment')
                                           and t.transaction_status = 'Approved'), 0) as spend
                   from m_customers c left join m_transactions t using (customer_id) group by 1""").df().spend  # fmt: skip
    x = np.sort(v.to_numpy(float))
    n = len(x)
    gini = float((2 * np.arange(1, n + 1) - n - 1) @ x / (n * x.sum()))
    top = float(x[int(0.9 * n) :].sum() / x.sum())
    ch.census("gini", gini, src, digits=3)
    ch.census("top-decile", 100 * top, src, unit="percent", digits=3)
    ch.census("zero-spend", 100 * float((x == 0).mean()), src, unit="percent", digits=3)


def stored(ch: Chapter) -> None:
    p = TABLES / "granularity_survival_customer.csv"
    s = pd.read_csv(p)
    c = s[s.group == "country_code"]
    ch.census("lr-country-p", float(c.logrank_p.iloc[0]), p, source_type="table", digits=2)
    ch.census(
        "rmst-gap",
        float(c["RMST 24 months"].max() - c["RMST 24 months"].min()),
        p,
        source_type="table",
        digits=2,
    )
    ch.census("s12-min", float(s["S(12)"].min()), p, source_type="table", digits=3)
    ch.census("s12-max", float(s["S(12)"].max()), p, source_type="table", digits=3)
    ch.census("median-lapse", float(c["median months to lapse"].median()), p, source_type="table")
    ch.census(
        "lapsed-pct", float(c["lapsed %"].mean()), p, source_type="table", unit="percent", digits=3
    )
    nb03 = REPO / "eda" / "notebooks" / "granularity" / "03_customer_lifetime.py"
    ch.constant("lapse-months", 3, nb03, source_type="notebook")
    ch.constant("rmst-horizon", 24, p, source_type="table")
    ch.census(
        "lr-segment-p",
        float(s[s.group == "segment"].logrank_p.iloc[0]),
        p,
        source_type="table",
        digits=2,
    )
    s.to_csv(OUT / "ch15_survival.csv", index=False)
    render_table(OUT / "ch15_survival.csv", "ch15-survival", "Time to a customer's first 90-day lapse, by group: "
                 "customers, the share that lapsed, the Kaplan-Meier median and survival at twelve months, the mean "
                 "engaged months within two years (RMST), and the log-rank p-value of the grouping (granularity "
                 "notebook 03).", digits=3)  # fmt: skip
    t = pd.read_csv(TABLES / "granularity_targets_customer.csv").iloc[0]
    tp = TABLES / "granularity_targets_customer.csv"
    ch.census("concordance", float(t.value), tp, source_type="table", digits=3)
    ch.census("concordance-lo", float(t.ci_low), tp, source_type="table", digits=3)
    ch.census("concordance-hi", float(t.ci_high), tp, source_type="table", digits=3)

    h = pd.read_csv(TABLES / "granularity_hour_customer_profile.csv")
    hp = TABLES / "granularity_hour_customer_profile.csv"
    r = h.iloc[0]
    k = round(r.statistic * r.n)
    ch.proportion(
        "preferred-hour",
        k,
        int(r.n),
        intervals.wilson(k, int(r.n)),
        hp,
        source_type="table",
        digits=3,
    )
    ch.constant("preferred-alpha", 1, hp, source_type="table", unit="percent")
    ch.census("daypart-ks-p", float(h.iloc[1].p_value), hp, source_type="table", digits=2)

    lifts = pd.read_csv(TABLES / "granularity_lifts.csv")
    lifts[["signal", "months with A", "P(B | A) %", "P(B | not A) %", "relative risk", "rr_low", "rr_high"]].to_csv(
        OUT / "ch15_lifts.csv", index=False)  # fmt: skip
    ch.count("lifts", len(lifts), TABLES / "granularity_lifts.csv", source_type="table")
    ch.census("lift-max-dev", float((lifts["relative risk"] - 1).abs().max()), TABLES / "granularity_lifts.csv",
              source_type="table", digits=2)  # fmt: skip
    render_table(OUT / "ch15_lifts.csv", "ch15-lifts", "Cross-process early warnings at the customer-month grain: "
                 "months in which the antecedent occurred, the probability of the consequent with and without it, and "
                 "the relative risk with its 95\\,\\% interval (granularity notebook 02).", digits=3)  # fmt: skip


def main() -> None:
    con = db.connect()
    ch = Chapter(15, "ch15")
    OUT.mkdir(parents=True, exist_ok=True)
    g = grid(con)
    markov(ch, g)
    dormancy(ch, g)
    value(ch, con)
    stored(ch)
    print(f"{len(ch.claims)} claims -> {ch.write()}")


if __name__ == "__main__":
    main()
