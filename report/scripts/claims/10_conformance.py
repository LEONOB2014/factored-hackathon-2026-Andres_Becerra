"""Chapter 10 · Conformance: lineage, exchange rates, the USD amount, point-in-time joins and change hashes.

Report-only re-analysis of pipeline/01, 04–06 and country_template/05–06:

* a static lineage of the lakehouse DAG from the dbt sources (refs in models, in the macros they call, in snapshots),
  and the edges that read a later task group;
* the structure of the exchange-rate table (centre, jitter, serial dependence, inverse and cross-rate consistency);
* the USD imputation of the conformed transaction fact, against the source's own USD amounts, at the daily rate and
  at the median rate;
* the dollar amounts of Mexican transactions labelled USD against everyone else's;
* transactions that predate their customer's registration or their product's opening (point-in-time coverage);
* the change hash of the snapshots: collision bound and injectivity of its encoding on the data;
* the sparsity of the dense customer-month grid.

    uv run python scripts/claims/10_conformance.py
"""

from __future__ import annotations

import re
from collections import defaultdict

import numpy as np
import pandas as pd
from scipy import stats

from report_lib import db
from report_lib.build import Chapter
from report_lib.paths import BUILD, REPO
from report_lib.texgen import render_table

MAIN = REPO / "data" / "parquet"
DBT = REPO / "platform" / "dbt"
COMMON = REPO / "platform" / "airflow" / "include" / "latam_dags" / "common.py"
OUT = BUILD / "sources"
THIS = REPO / "report" / "scripts" / "claims" / "10_conformance.py"
REF = re.compile(r"ref\(\s*['\"]([A-Za-z0-9_]+)['\"]\s*\)")


def layer_of(path) -> str | None:
    r = path.relative_to(DBT / "models").as_posix()
    top = r.split("/")[0]
    if top == "silver":
        return "silver"
    if r.startswith(("gold/core", "gold/marts")):
        return "gold"
    if r.startswith("gold/aggregates/"):
        return "aggregates_" + r.split("/")[2]
    if top in ("features", "graph", "knowledge"):
        return "features_graph_knowledge"
    if top in ("privacy", "serving"):
        return "privacy_serving"
    if top == "audit":
        return "audit"
    return None  # the BigQuery export models run outside the lakehouse DAG


def lineage(ch: Chapter) -> None:
    order = list(re.search(r"LAYERS = \{(.*?)\n\}", COMMON.read_text(), re.S).group(1).split("\n"))
    order = [re.match(r'\s*"(\w+)"', ln).group(1) for ln in order if re.match(r'\s*"(\w+)":', ln)]
    rank = {g: i for i, g in enumerate(order)}
    macro_refs: dict[str, set[str]] = {}
    for p in (DBT / "macros").glob("*.sql"):
        for name, body in re.findall(
            r"{%-?\s*macro\s+(\w+)\(.*?%}(.*?){%-?\s*endmacro", p.read_text(), re.S
        ):
            macro_refs[name] = set(REF.findall(body))
    nodes, edges = {}, set()
    for p in sorted((DBT / "models").rglob("*.sql")):
        g = layer_of(p)
        if g is None:
            continue
        nodes[p.stem] = g
        text = p.read_text()
        refs = set(REF.findall(text))
        for m in re.findall(r"{{\s*(\w+)\(", text):
            refs |= macro_refs.get(m, set())
        edges |= {(u, p.stem) for u in refs}
    for s, u in re.findall(
        r"- name: (snap_\w+)\n\s+relation: ref\('(\w+)'\)",
        (DBT / "snapshots" / "snapshots.yml").read_text(),
    ):
        nodes[s] = "snapshots"
        edges.add((u, s))
    for p in (DBT / "seeds").glob("*.csv"):
        nodes[p.stem] = "seeds"
    assert all(u in nodes for u, _ in edges), {u for u, _ in edges if u not in nodes}
    back = sorted((u, v) for u, v in edges if rank[nodes[u]] > rank[nodes[v]])
    succ = defaultdict(set)
    for u, v in edges:
        succ[u].add(v)

    def descendants(n: str) -> set[str]:
        seen, stack = set(), [n]
        while stack:
            for v in succ[stack.pop()]:
                if v not in seen:
                    seen.add(v)
                    stack.append(v)
        return seen

    src = DBT / "dbt_project.yml"
    ch.count("nodes", len(nodes), src)
    ch.count("edges", len(edges), src)
    ch.count("groups", len(order), COMMON)
    ch.count("back-edges", len(back), src)
    assert back == [("feat_credit_eligibility_pit", "mart_credit_eligibility")], back
    for n in ("stg_transactions", "int_transactions_enriched", "dq_corrections_active"):
        ch.count(f"desc-{n.replace('_', '-')}", len(descendants(n)), src)
    fanout = pd.DataFrame(
        [{"node": n, "task group": nodes[n], "descendants": len(descendants(n))} for n in nodes]
    )
    fanout.sort_values(["descendants", "node"], ascending=[False, True]).head(10).to_csv(
        OUT / "ch10_fanout.csv", index=False
    )
    render_table(OUT / "ch10_fanout.csv", "ch10-fanout", "The most central nodes of the lakehouse lineage: the number "
                 "of models, snapshots and tests downstream of each, from the dbt sources.")  # fmt: skip


def rates(ch: Chapter, con) -> pd.DataFrame:
    src = MAIN / "daily_exchange_rates.parquet"
    fx = con.sql(
        "select date, source_currency as s, target_currency as t, exchange_rate as r from m_daily_exchange_rates"
    ).df()
    w = fx.pivot_table(index="date", columns=["s", "t"], values="r").sort_index()
    rows = []
    for c in ("ARS", "COP", "MXN"):
        x = w[(c, "USD")].to_numpy()
        centre = float(np.median(1 / x))
        u = x / np.median(x) - 1
        lag1 = float(np.corrcoef(np.log(x[:-1]), np.log(x[1:]))[0, 1])
        inv = (w[(c, "USD")] * w[("USD", c)]).to_numpy()
        rows.append({"currency": c, "days": len(x), "units per dollar (median)": centre, "jitter low": float(u.min()),
                     "jitter high": float(u.max()), "coefficient of variation": float(np.std(x, ddof=1) / np.mean(x)),
                     "lag-1 autocorrelation": lag1, "inverse product low": float(inv.min()),
                     "inverse product high": float(inv.max())})  # fmt: skip
        tag = c.lower()
        ch.census(f"centre-{tag}", centre, src, digits=4)
        ch.census(f"lag1-{tag}", lag1, src, digits=2)
        ch.census(f"cv-{tag}", float(np.std(x, ddof=1) / np.mean(x)), src, digits=3)
        ch.census(
            f"ks-uniform-p-{tag}",
            float(stats.kstest((u + 0.02) / 0.04, "uniform").pvalue),
            src,
            digits=2,
        )
    t = pd.DataFrame(rows)
    t.to_csv(OUT / "ch10_rates.csv", index=False)
    ch.census(
        "jitter-max",
        float(max(t["jitter high"].max(), -t["jitter low"].min()) * 100),
        src,
        unit="percent",
        digits=2,
    )
    ch.census("uniform-cv", 100 * 0.02 / np.sqrt(3), src, unit="percent", digits=3)
    ch.constant("jitter-bound", 2, THIS, unit="percent")
    ch.census("inverse-max-dev", float(max(t["inverse product high"].max() - 1, 1 - t["inverse product low"].min()) * 100), src,
              unit="percent", digits=2)  # fmt: skip
    tri = (w[("ARS", "COP")] / (w[("ARS", "USD")] * w[("USD", "COP")])).to_numpy()
    ch.census(
        "triangle-max-dev",
        float(max(tri.max() - 1, 1 - tri.min()) * 100),
        src,
        unit="percent",
        digits=2,
    )
    ch.count("fx-days", int(t.days.iloc[0]), src)
    render_table(OUT / "ch10_rates.csv", "ch10-rates", "The exchange-rate table per currency against the dollar: "
                 "the median rate, the range of the daily deviation from it, its coefficient of variation and lag-one "
                 "autocorrelation, and the range of the product of the rate and its quoted inverse.", digits=4)  # fmt: skip
    return w


def usd(ch: Chapter, con) -> None:
    src = MAIN / "transactions.parquet"
    r = con.sql("""
        with fx as (select date as rate_date, source_currency as cur, exchange_rate as usd from m_daily_exchange_rates
                    where target_currency = 'USD'),
             med as (select cur, median(usd) as usd_med from fx group by 1),
             t as (select transaction_id, currency, amount, amount_usd, cast(process_date as date) as pd
                   from m_transactions where currency <> 'USD')
        select t.*, fx.usd, med.usd_med
        from t asof left join fx on fx.cur = t.currency and fx.rate_date <= t.pd
        join med on med.cur = t.currency""").df()  # fmt: skip
    n_all = con.sql("select count(*) from m_transactions").fetchone()[0]
    k = r.amount_usd.notna()
    ch.count("nonusd", len(r), src)
    ch.count("imputed", int((~k).sum()), src)
    ch.census("imputed-share", 100 * (~k).sum() / n_all, src, unit="percent", digits=3)
    g = r[k]
    daily = g.amount * g.usd / g.amount_usd - 1
    median = g.amount * g.usd_med / g.amount_usd - 1
    implied = g.amount_usd / g.amount
    rel = implied / implied.groupby(g.currency).transform("median") - 1
    ch.census("implied-range", float(rel.abs().max() * 100), src, unit="percent", digits=2)
    ch.census("implied-corr", float(np.corrcoef(implied / g.groupby("currency").usd.transform("median"), g.usd / g.usd_med)[0, 1]),
              src, digits=2)  # fmt: skip
    for tag, e in (("daily", daily), ("median", median)):
        ch.census(f"err-{tag}-bias", float(e.mean() * 100), src, unit="percent", digits=2)
        ch.census(f"err-{tag}-sd", float(e.std() * 100), src, unit="percent", digits=2)
        ch.census(
            f"err-{tag}-p95", float(e.abs().quantile(0.95) * 100), src, unit="percent", digits=2
        )
    ch.count("checked", int(k.sum()), src)
    ch.constant("p95-level", 95, THIS, unit="percent")
    ch.census("err-ratio", float(daily.std() / median.std()), src, digits=2)

    # Mexican transactions labelled USD against everyone else's dollar amounts
    q = con.sql("""select c.country,
                          coalesce(t.amount_usd, case when t.currency = 'USD' then t.amount end) as usd, t.currency
                   from m_transactions t join m_customers c using (customer_id)""").df()  # fmt: skip
    mx = q[(q.country == "México") & (q.currency == "USD")].usd.dropna()
    other = q[(q.country != "México")].usd.dropna()
    ch.census("mx-usd-median", float(mx.median()), src, digits=4)
    ch.census("other-usd-median", float(other.median()), src, digits=4)
    ch.census("mx-ks", float(stats.ks_2samp(mx, other).statistic), src, digits=2)
    ch.census(
        "mx-usd-share", 100 * len(mx) / (q.country == "México").sum(), src, unit="percent", digits=4
    )
    ch.count("mxn-transactions", int((q.currency == "MXN").sum()), src)


def pit(ch: Chapter, con) -> None:
    src = MAIN / "transactions.parquet"
    a, b, n = con.sql("""select count(*) filter (where cast(t.transaction_date as date) < c.registration_date),
                                count(*) filter (where cast(t.transaction_date as date) < p.opening_date),
                                count(*)
                         from m_transactions t join m_customers c using (customer_id)
                         join m_products p using (product_id)""").fetchone()  # fmt: skip
    ch.census("before-registration", 100 * a / n, src, unit="percent", digits=3)
    ch.census("before-opening", 100 * b / n, src, unit="percent", digits=3)


def hashes(ch: Chapter, con) -> None:
    src = DBT / "macros" / "helpers.sql"
    text = src.read_text()
    assert "md5(concat_ws('|'" in text and "'<null>'" in text
    bc = (DBT / "macros" / "business_columns.sql").read_text()
    cols = {t: re.findall(r"'(\w+)'", re.search(rf"macro cols_{t}\(\).*?return\(\[(.*?)\]\)", bc, re.S).group(1))
            for t in ("customers", "products", "branches", "service_agents")}  # fmt: skip
    keys, bad = 0, 0
    for t, cs in cols.items():
        present = {c[0] for c in con.sql(f"describe m_{t}").fetchall()}
        cs = [c for c in cs if c in present]
        keys += con.sql(f"select count(*) from m_{t}").fetchone()[0]
        cond = " or ".join(
            f"contains(cast({c} as varchar), '|') or cast({c} as varchar) = '<null>'" for c in cs
        )
        bad += con.sql(f"select count(*) from m_{t} where {cond}").fetchone()[0]
    ch.count("hash-keys", keys, MAIN / "customers.parquet")
    ch.count("hash-ambiguous", bad, MAIN / "customers.parquet")
    ch.constant("hash-bits", 128, src)
    ch.census("hash-bound", float(keys * (keys - 1) / 2 * 2.0**-128), src, digits=2)
    ch.census(
        "hash-bound-log10",
        float(np.log10(keys * (keys - 1) / 2) - 128 * np.log10(2)),
        src,
        digits=3,
    )


def grid(ch: Chapter, con) -> None:
    src = MAIN / "transactions.parquet"
    months, customers, active = con.sql("""
        with m as (select count(distinct date_trunc('month', transaction_date)) as k from m_transactions),
             a as (select count(*) as k from (select distinct customer_id, date_trunc('month', transaction_date)
                                               from m_transactions))
        select m.k, (select count(*) from m_customers), a.k from m, a""").fetchone()  # fmt: skip
    ch.count("grid-months", months, src)
    ch.census(
        "grid-empty", 100 * (1 - active / (months * customers)), src, unit="percent", digits=3
    )


def main() -> None:
    con = db.connect()
    ch = Chapter(10, "ch10")
    OUT.mkdir(parents=True, exist_ok=True)
    lineage(ch)
    rates(ch, con)
    usd(ch, con)
    pit(ch, con)
    hashes(ch, con)
    grid(ch, con)
    print(f"{len(ch.claims)} claims -> {ch.write()}")


if __name__ == "__main__":
    main()
