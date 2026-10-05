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


def test_clock_scan_recovers_a_planted_offset():
    rng = np.random.default_rng(1)
    # days drawn on a UTC-6 clock with a weekend dip, times uniform within the day; raw timestamps are stored at UTC
    days = pd.date_range("2024-01-01", "2024-06-30", freq="D")
    weight = np.where(days.weekday >= 5, 0.6, 1.0)
    n = rng.poisson(400 * weight)
    local = np.concatenate(
        [
            d + pd.to_timedelta(rng.uniform(0, 86400, k), unit="s")
            for d, k in zip(days, n, strict=True)
        ]
    )
    raw = pd.Series(pd.to_datetime(local) + pd.Timedelta(hours=6))
    scan = g.clock_scan(raw)
    best = scan.loc[scan.chi2.idxmin()]
    assert best.shift_hours == -6
    assert best.chi2_over_dof < 2 < scan.set_index("shift_hours").loc[0, "chi2_over_dof"]
    hourly = raw.dt.floor("h").value_counts().sort_index()
    fast = g.clock_scan(pd.Series(hourly.index), counts=hourly.to_numpy())
    assert fast.loc[fast.chi2.idxmin(), "shift_hours"] == -6
    assert np.allclose(fast.chi2, scan.chi2)


def test_beta_binomial_fit_recovers_the_prior():
    rng = np.random.default_rng(2)
    p = rng.beta(2.0, 300.0, 3000)
    n = rng.integers(200, 2000, 3000)
    s = rng.binomial(n, p)
    a, b = g.beta_binomial_fit(s, n)
    assert a / (a + b) == pytest.approx(2 / 302, rel=0.05)
    assert a + b == pytest.approx(302, rel=0.25)


def test_policy_value_replays_held_out_outcomes():
    cells = pd.DataFrame(
        {"rate_ho": [0.02, 0.0], "value_per_conv_ho": [100.0, 0.0], "cost_per_send_ho": [0.5, 0.5]},
        index=["good", "dead"],
    )
    even = g.policy_value(cells, pd.Series({"good": 1, "dead": 1}), 1000)
    best = g.policy_value(cells, pd.Series({"good": 1, "dead": 0}), 1000)
    assert even["conversions"] == pytest.approx(10) and even["net"] == pytest.approx(500)
    assert best["conversions"] == pytest.approx(20) and best["net"] == pytest.approx(1500)


def test_daypart_and_uniform_hours():
    assert g.daypart(0) == "night" and g.daypart(6) == "morning" and g.daypart(23) == "evening"
    assert list(g.daypart(np.array([5, 12, 18]))) == ["night", "afternoon", "evening"]
    rng = np.random.default_rng(1)
    flat = rng.multinomial(24_000, [1 / 24] * 24)
    assert g.uniform_hours_test(flat)["p_value"] > 0.01
    peak = flat.copy()
    peak[9] += 600
    t = g.uniform_hours_test(peak)
    assert t["p_value"] < 1e-6 and t["dof"] == 23 and t["cohen_w"] > 0.05


def test_occupancy_is_capped():
    assert np.allclose(g.occupancy([1800, 4000, 0]), [0.5, 1.0, 0.0])


def test_business_hours_skip_weekends_and_holidays():
    fri = pd.Series(pd.to_datetime(["2026-01-09 17:00"]))  # a Friday
    mon = pd.Series(pd.to_datetime(["2026-01-12 10:00"]))
    assert g.business_hours_between(fri, mon)[0] == pytest.approx(2.0)  # Fri 17-18, Mon 9-10
    tue = pd.Series(pd.to_datetime(["2026-01-13 10:00"]))
    assert g.business_hours_between(fri, tue, holidays={"2026-01-12"})[0] == pytest.approx(2.0)
    assert np.isnan(g.business_hours_between(fri, pd.Series([pd.NaT]))[0])
    same = pd.Series(pd.to_datetime(["2026-01-09 08:00"]))
    assert g.business_hours_between(same, fri)[0] == pytest.approx(
        8.0
    )  # 9 to 17 of the same Friday


def test_load_rejects_a_model_defined_twice(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    a.mkdir()
    b.mkdir()
    (a / "m.sql").write_text("-- grain: k\nselect 1 as k")
    (b / "m.sql").write_text("-- grain: k\nselect 2 as k")
    (b / "n.sql").write_text("-- grain: k\nselect 3 as k")
    assert set(g.load([a, tmp_path / "missing"])) == {"m"}
    with pytest.raises(ValueError, match="defined twice"):
        g.load([a, b])


def _auc_case(n, effect, seed):
    from sklearn.metrics import roc_auc_score

    rng = np.random.default_rng(seed)
    x = rng.normal(size=n)
    y = (rng.random(n) < 1 / (1 + np.exp(-(-1 + effect * x)))).astype(int)
    d, boot = g.paired_boot(
        roc_auc_score, y, x, np.zeros(n) + rng.normal(0, 1e-9, n), B=200, seed=seed
    )
    return d, boot


def test_readiness_gate_on_planted_cases():
    d, boot = _auc_case(20_000, 1.5, 1)  # a real, large effect
    assert g.readiness_verdict(boot, d, material=0.02)["verdict"] == "green"
    d, boot = _auc_case(20_000, 0.0, 2)  # noise
    r = g.readiness_verdict(boot, d, material=0.02)
    assert (r["verdict"], r["root_cause"]) == ("red", "generator independence")
    d, boot = _auc_case(80, 0.05, 3)  # a tiny effect on a small sample
    r = g.readiness_verdict(boot, d, material=0.02, cause_if_red="missing field")
    assert (r["verdict"], r["root_cause"]) == ("red", "insufficient volume")
    d, boot = _auc_case(200_000, 0.06, 4)  # significant but small
    assert g.readiness_verdict(boot, d, material=0.05)["verdict"] == "amber"
    with pytest.raises(ValueError):
        g.readiness_verdict(boot, d, material=0.05, cause_if_red="bad luck")


def test_hour_star_schedule_and_shift_dimensions():
    con = duckdb.connect()
    con.sql("""CREATE TABLE stg_branches AS SELECT * FROM (VALUES ('B1', '09:30:00', '18:00:00'))
               t(branch_id, opening_time, closing_time)""")
    s = g.Star(FakePipeline(con), sql_dir=g.SQL_DIR_HOUR)
    s.build(["dim_branch_schedule", "dim_agent_shift"], verbose=False)
    sched = s.q("select * from {dim_branch_schedule} order by iso_weekday, hour_of_day").set_index(
        ["iso_weekday", "hour_of_day"]
    )
    assert len(sched) == 7 * 24
    assert sched.loc[(1, 9), "open_fraction"] == pytest.approx(0.5)  # opens at 09:30
    assert sched.loc[(1, 12), "open_fraction"] == pytest.approx(1.0)
    assert sched.loc[(1, 18), "open_fraction"] == pytest.approx(0.0)  # closes at 18:00
    assert (
        sched.loc[(6, 12), "open_fraction"] == 0
        and sched.loc[(6, 12), "open_fraction_any_day"] == 1
    )
    shift = s.q("select work_shift, sum(in_shift::int) as hours from {dim_agent_shift} group by 1")
    assert dict(zip(shift.work_shift, shift.hours, strict=True)) == {
        "Morning": 8,
        "Afternoon": 8,
        "Night": 8,
        "Rotating": 24,
    }
    assert s.check(["dim_branch_schedule", "dim_agent_shift"]).ok.all()
