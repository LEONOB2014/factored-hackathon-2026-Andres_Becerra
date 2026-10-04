"""The granularity library on synthetic inputs (no dataset): runner, build checks and the statistics it uses."""

import duckdb
import numpy as np
import pandas as pd
import pytest
from statsmodels.stats.multitest import multipletests

from latam_eda import granularity as g


class FakePipeline:
    """The three methods of `latam_eda.pipeline.Pipeline` the star needs, over an in-memory DuckDB."""

    def __init__(self, con):
        self.con = con

    def key(self, name):
        return name

    def relation(self, key):
        return f"main.{key}"

    def ensure(self, key):
        return []


@pytest.fixture
def star(tmp_path):
    con = duckdb.connect()
    con.sql("""CREATE TABLE fct_tx AS SELECT * FROM (VALUES
               ('a', TIMESTAMP '2025-01-03', 10.0), ('a', TIMESTAMP '2025-01-20', 5.0),
               ('b', TIMESTAMP '2025-02-01', 7.0)) t(customer_id, ts, usd)""")
    con.sql("CREATE TABLE customers AS SELECT * FROM (VALUES ('a'), ('b')) t(customer_id)")
    con.sql("""CREATE TABLE months AS SELECT * FROM (VALUES (DATE '2025-01-01'), (DATE '2025-02-01'))
               t(month_start)""")
    (tmp_path / "grid.sql").write_text(
        "-- the customer-month grid\n"
        "-- grain: customer_id, month_start\n"
        "-- dense: customer_id from {customers} x month_start from {months}\n"
        "select c.customer_id, m.month_start from {customers} c cross join {months} m\n"
    )
    (tmp_path / "cust_month.sql").write_text(
        "-- grain: customer_id, month_start\n"
        "-- reconcile: n_tx = count(*) from {fct_tx} | month_start = date_trunc('month', ts)::date\n"
        "-- reconcile: usd = sum(usd) from {fct_tx}\n"
        "-- dense: customer_id from {customers} x month_start from {months}\n"
        "select g.customer_id, g.month_start, count(t.ts) as n_tx, coalesce(sum(t.usd), 0) as usd\n"
        "from {grid} g left join {fct_tx} t on t.customer_id = g.customer_id\n"
        " and date_trunc('month', t.ts) = g.month_start group by all\n"
    )
    s = g.Star(FakePipeline(con), sql_dir=tmp_path)
    s.build(verbose=False)
    return s


def test_runner_orders_by_refs_and_reads_contracts(star):
    assert g.order(star.models) == ["grid", "cust_month"]
    m = star.models["cust_month"]
    assert m.grain == ["customer_id", "month_start"]
    assert len(m.reconcile) == 2 and m.refs == {"grid", "fct_tx"}
    assert star.models["grid"].doc == "the customer-month grid"


def test_checks_pass_on_a_correct_star(star):
    res = star.check()
    assert res.ok.all(), res


def test_checks_catch_a_duplicate_a_lost_row_and_a_hole(star):
    con = star.pl.con
    con.sql("INSERT INTO agg.cust_month SELECT * FROM agg.cust_month LIMIT 1")  # duplicated grain
    assert not star.grain_unique("cust_month")["ok"]
    con.sql("DELETE FROM agg.cust_month WHERE customer_id = 'b'")  # a hole and a lost transaction
    assert not star.dense_complete("cust_month")["ok"]
    assert not all(r["ok"] for r in star.reconciles("cust_month"))


def test_order_rejects_a_cycle(tmp_path):
    (tmp_path / "x.sql").write_text("select * from {y}\n")
    (tmp_path / "y.sql").write_text("select * from {x}\n")
    with pytest.raises(ValueError, match="cycle"):
        g.order(g.load(tmp_path))


def test_transition_matrix_stationary_and_sojourn():
    rows = []
    for c, seq in {"a": "AAAD", "b": "ADDD", "c": "AADA"}.items():
        for i, s in enumerate(seq):
            rows.append({"c": c, "m": pd.Timestamp("2025-01-01") + pd.DateOffset(months=i), "s": s})
    df = pd.DataFrame(rows)
    df = df.drop(
        index=df[(df.c == "c") & (df.m == pd.Timestamp("2025-02-01"))].index
    )  # a gap: not a transition
    p = g.transition_matrix(df, "c", "m", "s")
    assert np.allclose(p.sum(axis=1), 1)
    assert p.loc["A", "D"] == pytest.approx(
        3 / 6
    )  # a:A→A,A→A,A→D  b:A→D  c:D→A (c's A→D skipped by the gap)
    pi = g.stationary(pd.DataFrame([[0.9, 0.1], [0.5, 0.5]], index=["A", "D"], columns=["A", "D"]))
    assert pi["A"] == pytest.approx(5 / 6)
    assert g.expected_sojourn(pd.DataFrame([[0.75]], index=["A"], columns=["A"]))[
        "A"
    ] == pytest.approx(4)


def test_erlang_c_matches_the_textbook_case():
    # 100 calls an hour, 3-minute handle time: A = 5 Erlangs; with 6 agents P(wait) = 0.5875 (standard tables)
    assert g.erlang_c(100, 180, 6) == pytest.approx(0.5875, abs=1e-3)
    assert g.erlang_c(100, 180, 5) == 1.0
    n = g.agents_needed(100, 180, target_seconds=20, service=0.8)
    assert g.service_level(100, 180, n, 20) >= 0.8 > g.service_level(100, 180, n - 1, 20)


def test_newsvendor_and_concentration():
    assert g.newsvendor_quantile(9, 1) == pytest.approx(0.9)
    assert g.hhi(pd.Series([1.0])) == pytest.approx(10_000)
    assert g.hhi(pd.Series([1, 1, 1, 1])) == pytest.approx(2_500)


def test_bh_fdr_matches_statsmodels():
    p = np.array([0.001, 0.008, 0.039, 0.041, 0.042, 0.06, 0.074, 0.205, 0.212, 0.216])
    rej, adj = g.bh_fdr(p, 0.05)
    ref_rej, ref_adj, *_ = multipletests(p, 0.05, method="fdr_bh")
    assert (rej == ref_rej).all() and np.allclose(adj, ref_adj)


def test_mase_and_diebold_mariano():
    rng = np.random.default_rng(0)
    y = 100 + 10 * np.sin(np.arange(140) * 2 * np.pi / 7) + rng.normal(0, 1, 140)
    naive = y[-35 - 7 : -7]
    assert g.mase(y[-35:], naive, y[:-35]) == pytest.approx(1.0, abs=0.35)
    good, bad = rng.normal(0, 1, 200), rng.normal(0, 3, 200)
    stat, p = g.diebold_mariano(good, bad)
    assert stat < 0 and p < 0.01
