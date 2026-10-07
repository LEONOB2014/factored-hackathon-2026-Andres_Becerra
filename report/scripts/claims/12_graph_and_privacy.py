"""Chapter 12 · Graph, tokens and differential privacy.

Report-only analysis of pipeline/10–11 and country_template/10–11 from the lake's exports:

* the property graph: degree of identifier nodes, the token that missing values collapse into, real sharing;
* the cost of reversing a salted SHA-256 token by enumeration, measured on this machine;
* the differentially private complaint release: sensitivity, noise, the error of the released cells against the
  true counts, cells of a country with no customers, the bias that suppression introduces, the privacy budget against
  the schedule, and the bias and noise of alternative contribution bounds.

    uv run python scripts/claims/12_graph_and_privacy.py
"""

from __future__ import annotations

import hashlib
import re
import time

import duckdb
import numpy as np
import pandas as pd

from report_lib import db
from report_lib.build import Chapter
from report_lib.paths import BUILD, REPO
from report_lib.texgen import render_table

LAKE = REPO / "data" / "lake"
EDGES = LAKE / "graph" / "graph_edges.parquet"
RELEASE = next((LAKE / "privacy").glob("dp_complaints_country_month__*.parquet"))
DAG = REPO / "platform" / "airflow" / "dags" / "dp_release.py"
PRIV = REPO / "platform" / "libs" / "latam_platform" / "privacy.py"
HELPERS = REPO / "platform" / "dbt" / "macros" / "helpers.sql"
MAIN = REPO / "data" / "parquet"
OUT = BUILD / "sources"
THIS = REPO / "report" / "scripts" / "claims" / "12_graph_and_privacy.py"
CODE = {"México": "MX", "Colombia": "CO", "Argentina": "AR"}


def dlap_var(b: float) -> float:
    """Variance of the discrete Laplace distribution P(k) proportional to exp(-|k| / b)."""
    q = np.exp(-1 / b)
    return 2 * q / (1 - q) ** 2


def graph(ch: Chapter, con) -> None:
    g = duckdb.connect()
    deg = g.sql(f"""select dst_type, dst_id, count(distinct src_id) as deg from '{EDGES}'
                    where src_type = 'customer' group by all""").df()  # fmt: skip
    ip = deg[deg.dst_type == "ip"].sort_values("deg", ascending=False)
    customers = con.sql("select count(*) from m_customers").fetchone()[0]
    ch.count("customers", customers, MAIN / "customers.parquet")
    ch.count("ip-nodes", len(ip), EDGES)
    ch.count("ip-top-degree", int(ip.deg.iloc[0]), EDGES)
    ch.census("ip-top-share", 100 * ip.deg.iloc[0] / customers, EDGES, unit="percent", digits=3)
    ch.count("ip-shared-two", int((ip.deg.iloc[1:] == 2).sum()), EDGES)
    ch.count("ip-max-other", int(ip.deg.iloc[1:].max()), EDGES)
    ch.count("edges", int(g.sql(f"select count(*) from '{EDGES}'").fetchone()[0]), EDGES)
    ch.count("transfer-edges", int(g.sql(f"""select count(*) from '{EDGES}'
                                           where src_type = 'customer' and dst_type = 'customer'""").fetchone()[0]), EDGES)  # fmt: skip
    events = con.sql("""select count(*) filter (where ip_address is null), count(*) from m_digital_events
                        where customer_id is not null""").fetchone()  # fmt: skip
    ch.census(
        "events-ip-missing",
        100 * events[0] / events[1],
        MAIN / "digital_events.parquet",
        unit="percent",
        digits=3,
    )
    assert "sha256(concat(" in HELPERS.read_text()


def brute_force(ch: Chapter, con) -> None:
    n, t0 = 0, time.perf_counter()
    while time.perf_counter() - t0 < 3:
        for i in range(50_000):
            hashlib.sha256(b"salt|%d" % i).digest()
        n += 50_000
    rate = n / (time.perf_counter() - t0)
    ch.census("hash-rate", rate, THIS, digits=2)
    lengths = con.sql(
        "select length(document_number) l, count(*) n from m_customers group by 1 order by 1"
    ).df()
    ch.count("doc-lengths", len(lengths), MAIN / "customers.parquet")
    common = int(lengths.sort_values("n").l.iloc[-1])
    ch.count("doc-common-length", common, MAIN / "customers.parquet")
    ch.census(
        "doc-common-share",
        100 * lengths.n.max() / lengths.n.sum(),
        MAIN / "customers.parquet",
        unit="percent",
        digits=3,
    )
    ch.census("enumerate-common-s", 10**common / rate, THIS, digits=2)
    ch.census("enumerate-longest-min", 10 ** int(lengths.l.max()) / rate / 60, THIS, digits=2)


def privacy(ch: Chapter, con) -> None:
    dag = DAG.read_text()
    eps = float(re.search(r"epsilon: float = ([\d.]+)", dag).group(1))
    total = float(re.search(r"epsilon_total=([\d.]+)", dag).group(1))
    per_group = int(re.search(r"max_per_group=(\d+)", dag).group(1))
    groups = int(re.search(r"max_groups=(\d+)", dag).group(1))
    schedule = re.search(r'schedule="(@\w+)"', dag).group(1)
    assert schedule == "@monthly" and "suppress_below: int = 10" in PRIV.read_text()
    sens = per_group * groups
    b = sens / eps
    for tag, v in (
        ("eps", eps),
        ("eps-total", total),
        ("per-group", per_group),
        ("max-groups", groups),
    ):
        ch.constant(tag, v, DAG)
    ch.constant("suppress", 10, PRIV)
    ch.census("sensitivity", sens, DAG)
    ch.census("scale", b, DAG, digits=3)
    ch.census("noise-sd", float(np.sqrt(dlap_var(b))), DAG, digits=3)
    ch.census("releases-per-budget", total / eps, DAG, digits=2)
    ch.constant("releases-per-year", 12, DAG)

    k = con.sql("""select k.customer_id, c.country, strftime(k.creation_date, '%Y-%m') as ym, k.category
                   from m_complaints k join m_customers c using (customer_id)""").df()  # fmt: skip
    src = MAIN / "complaints.parquet"
    pg = k.groupby(["customer_id", "country", "ym", "category"]).size()
    gpc = pg.groupby(level=0).size()
    ch.count("complaints", len(k), src)
    ch.count("max-per-group-obs", int(pg.max()), src)
    ch.count("max-groups-obs", int(gpc.max()), src)
    ch.census("single-share", 100 * float((pg == 1).mean()), src, unit="percent", digits=4)
    cells = k.groupby(["country", "ym", "category"]).size()
    ch.count("cells", len(cells), src)
    ch.census("cell-median", float(cells.median()), src)
    ch.census(
        "rel-noise", 100 * np.sqrt(dlap_var(b)) / cells.median(), src, unit="percent", digits=2
    )

    rel = duckdb.connect().sql(f"select * from '{RELEASE}'").df()
    true = cells.rename("true").reset_index()
    true["country_code"] = true.country.map(CODE)
    m = rel.merge(true, left_on=["country_code", "year_month", "category"], right_on=["country_code", "ym", "category"],
                  how="left")  # fmt: skip
    m["true"] = m["true"].fillna(0)
    ok = ~m.suppressed
    err = m.dp_count[ok] - m["true"][ok]
    ch.count("released-cells", len(rel), RELEASE)
    ch.count("suppressed-cells", int(m.suppressed.sum()), RELEASE)
    ch.census("err-sd", float(err.std()), RELEASE, digits=3)
    ch.census("err-mean", float(err.mean()), RELEASE, digits=3)
    br = m[m.country_code == "BR"]
    ch.count("br-cells", len(br), RELEASE)
    ch.count("br-published", int((~br.suppressed).sum()), RELEASE)
    q = np.exp(-1 / b)
    p_tail = q**10 / (1 + q)  # P(L >= 10) for the discrete Laplace
    ch.census("br-expected", float(len(br) * p_tail), RELEASE, digits=3)

    # alternative bounds: complaints removed by bounding, and the noise each sensitivity implies
    rows = []
    for pgb, gb in ((per_group, groups), (1, 1), (1, 2), (1, 3), (2, 3)):
        kept = np.minimum(pg, pgb)
        ranked = (
            kept.groupby(level=0).cumcount() < gb
        )  # any deterministic choice of groups; the count is what matters
        removed = len(k) - int(kept[ranked].sum())
        s, bb = pgb * gb, pgb * gb / eps
        sd = float(np.sqrt(dlap_var(bb)))
        bias = removed / len(cells)
        rows.append({"per group": pgb, "groups": gb, "sensitivity": s, "complaints removed": removed,
                     "share removed": removed / len(k), "noise sd": sd,
                     "root mean squared error": float(np.sqrt(bias**2 + sd**2)),
                     "relative to median cell": float(np.sqrt(bias**2 + sd**2) / cells.median())})  # fmt: skip
    t = pd.DataFrame(rows)
    t.to_csv(OUT / "ch12_bounds.csv", index=False)
    best = t.iloc[1:].sort_values("root mean squared error").iloc[0]
    ch.count("best-per-group", int(best["per group"]), THIS)
    ch.count("best-groups", int(best["groups"]), THIS)
    ch.census("best-rmse", float(best["root mean squared error"]), THIS, digits=3)
    ch.census("best-removed", 100 * float(best["share removed"]), THIS, unit="percent", digits=2)
    ch.census("current-rmse", float(t.iloc[0]["root mean squared error"]), THIS, digits=3)
    render_table(OUT / "ch12_bounds.csv", "ch12-bounds", "Contribution bounds for the complaint release at the "
                 "release's privacy loss: complaints per customer and group, groups per customer, the sensitivity they "
                 "imply, the complaints the bounds remove, the noise of the discrete Laplace mechanism and the "
                 "resulting error per cell. The first row is the deployed setting.", digits=3)  # fmt: skip


def main() -> None:
    con = db.connect()
    ch = Chapter(12, "ch12")
    OUT.mkdir(parents=True, exist_ok=True)
    graph(ch, con)
    brute_force(ch, con)
    privacy(ch, con)
    print(f"{len(ch.claims)} claims -> {ch.write()}")


if __name__ == "__main__":
    main()
