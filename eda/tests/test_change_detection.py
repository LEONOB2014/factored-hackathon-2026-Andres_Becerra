"""latam_eda.change_detection on synthetic series with known changes (positive and negative controls)."""

import numpy as np
import pandas as pd
import pytest

from latam_eda import change_detection as cd

DAYS = pd.date_range("2024-01-01", periods=200, freq="D")


def presence(on_days):
    return pd.Series([d in on_days for d in range(len(DAYS))], index=DAYS)


@pytest.mark.parametrize(
    ("on", "kind"),
    [
        (set(range(200)), "stable"),
        (set(range(120, 200)), "born"),
        (set(range(0, 80)), "died"),
        ({30, 31, 90}, "transient"),
        (set(range(60, 140)), "episode"),
        (set(range(0, 200, 3)), "intermittent"),
        (set(range(150, 200, 3)), "born"),  # sparse, but absent for 150 days before: a late birth
        (set(range(2, 200, 3)), "intermittent"),  # a 2-day lead is normal for a 1-in-3 value
        (set(), "absent"),
    ],
)
def test_presence_classification(on, kind):
    assert cd.classify_presence(presence(on), k=7)["kind"] == kind


def test_born_reports_the_first_day():
    r = cd.classify_presence(presence(set(range(120, 200))))
    assert r["first_seen"] == DAYS[120]


def test_pelt_with_calibrated_penalty_finds_a_step_and_nothing_in_noise():
    rng = np.random.default_rng(1)
    noise = rng.normal(0, 1, 200)
    step = noise + np.r_[np.zeros(120), np.full(80, 3.0)]
    pen = cd.calibrated_penalty(noise, alpha=0.05)
    assert cd.pelt(noise, pen) == []
    cps = cd.pelt(step, cd.calibrated_penalty(step, alpha=0.05))
    assert len(cps) == 1 and abs(cps[0] - 120) <= 3


def test_binseg_finds_steps_and_nothing_in_noise():
    rng = np.random.default_rng(5)
    noise = rng.normal(0, 1, 300)
    assert cd.binseg(noise, alpha=0.01) == []
    two = noise + np.r_[np.zeros(100), np.full(100, 2.0), np.zeros(100)]
    cps = cd.binseg(two, alpha=0.01)
    assert len(cps) == 2 and abs(cps[0] - 100) <= 4 and abs(cps[1] - 200) <= 4


def test_binseg_false_alarm_rate_is_controlled():
    rng = np.random.default_rng(6)
    alarms = sum(bool(cd.binseg(rng.normal(0, 1, 150), alpha=0.05, seed=i)) for i in range(60))
    assert alarms / 60 <= 0.12  # nominal 5%, generous bound for 60 trials


def test_cusum_alarms_after_a_shift_not_before():
    rng = np.random.default_rng(2)
    x = pd.Series(rng.normal(0, 1, 200) + np.r_[np.zeros(150), np.full(50, 1.5)], index=DAYS)
    alarms = cd.cusum(x, warmup=60)
    assert alarms and all(a >= DAYS[150] for a in alarms)
    assert (alarms[0] - DAYS[150]).days <= 10


def test_benjamini_hochberg():
    p = np.array([0.001, 0.008, 0.039, 0.041, 0.042, 0.06, 0.074, 0.205, 0.212, 0.216])
    assert cd.benjamini_hochberg(p, 0.05).tolist() == [True, True] + [False] * 8


def test_rate_shift_tests_flag_only_the_shifted_days():
    rng = np.random.default_rng(3)
    n = pd.Series(1000, index=DAYS)
    p = np.r_[np.full(180, 0.05), np.full(20, 0.15)]
    k = pd.Series(rng.binomial(1000, p), index=DAYS)
    res = cd.rate_shift_tests(k, n, warmup=60)
    assert res["flag"].iloc[180:].all()
    assert res["flag"].iloc[:180].mean() < 0.05


def test_scale_step_is_labelled_as_a_redenomination():
    rng = np.random.default_rng(4)
    loc = np.r_[np.full(120, 6.2), np.full(80, 6.2 - np.log10(4000))] + rng.normal(0, 0.02, 200)
    steps = cd.scale_steps(pd.Series(loc, index=DAYS))
    assert len(steps) == 1
    assert steps["label"].iloc[0] == "COP/USD ~4000"
    assert abs(steps["date"].iloc[0] - DAYS[120]).days <= 3


def test_jsd_and_jaccard_bounds():
    assert cd.jensen_shannon(np.array([1, 0]), np.array([1, 0])) == pytest.approx(0)
    assert cd.jensen_shannon(np.array([1, 0]), np.array([0, 1])) == pytest.approx(np.log(2))
    assert cd.jaccard({"a", "b"}, {"b", "c"}) == pytest.approx(1 / 3)


def test_robust_z_and_weekday_adjust():
    x = pd.Series([1.0] * 20 + [10.0], index=pd.date_range("2024-01-01", periods=21))
    assert cd.robust_z(x).iloc[-1] == np.inf
    w = pd.Series(np.tile([5, 1, 1, 1, 1, 1, 1], 4), index=pd.date_range("2024-01-01", periods=28))
    assert cd.weekday_adjust(w).abs().max() == 0


def test_detect_table_end_to_end_on_crafted_partitions(tmp_path):
    """40 daily files; from day 20 the vocabulary changes and a decimal comma appears."""
    import json
    from dataclasses import asdict

    import duckdb

    from latam_eda import raw_forensics as rf

    files = []
    for i, day in enumerate(pd.date_range("2024-01-01", periods=40)):
        kind = "Compra" if i >= 20 else "Purchase"
        amount = "7,5" if i >= 20 else "7.5"
        rows = "".join(f'T{i}_{j},{kind},"{amount}"\r\n' for j in range(30))
        p = tmp_path / f"year={day:%Y}/month={day:%m}/day={day:%d}/t.csv"
        p.parent.mkdir(parents=True)
        p.write_bytes(b"\xef\xbb\xbf" + ("id,kind,amount\r\n" + rows).encode())
        files.append(p)
    scans = pd.DataFrame([asdict(rf.scan_file(f)) for f in files])
    scans["header"] = scans["header"].map(json.dumps)
    con = duckdb.connect()
    lex, voc = rf.lexical_profile(con, files), rf.vocabulary(con, files, ["kind"])
    for df in (scans, lex, voc):
        df["partition_date"] = pd.to_datetime(df["partition_date"])
    found = cd.detect_table(scans, lex, voc)
    day20 = pd.Timestamp("2024-01-21")

    def one(level, column, signal, kind):
        f = found[(found.level == level) & (found.column == column) & (found.kind == kind)]
        f = f[f.signal == signal]
        assert len(f) == 1, (level, column, signal, kind, found)
        return f.iloc[0]

    assert one("L3", "kind", "value=Compra", "born")["change_date"] == day20
    assert one("L3", "kind", "value=Purchase", "died")["change_date"] == day20
    assert one("L2", "amount", "class:dec_comma", "born")["change_date"] == day20
    assert one("L2", "amount", "class:dec_dot", "died")["change_date"] == day20
    # nothing is reported before the change: the first 20 days are clean
    assert (found["change_date"].dropna() >= day20).all()


def test_a_burst_is_dated_by_its_earliest_change(tmp_path):
    """60 values die and 60 new ones are born on day 20: one burst finding, dated day 20."""
    days = pd.date_range("2024-01-01", periods=40)
    rows = []
    for i, day in enumerate(days):
        values = [f"new{j}" for j in range(60)] if i >= 20 else [f"old{j}" for j in range(60)]
        rows += [
            {"file": f"f{i}", "column": "code", "value": v, "n": 1, "partition_date": day}
            for v in values
        ]
    voc = pd.DataFrame(rows)
    files = pd.DataFrame(
        {
            "partition_date": days,
            "bom": True,
            "crlf": 1,
            "lf": 0,
            "utf8_errors": 0,
            "nul_bytes": 0,
            "ragged": 0,
            "grammar_error": None,
            "header": '["code"]',
        }
    )
    lex = pd.DataFrame(columns=["file", "column", "partition_date", "n", "log10_median"])
    found = cd.detect_table(files, lex, voc, max_values=50)
    burst = found[found.signal == "vocabulary_burst"]
    assert len(burst) == 1
    assert burst["change_date"].iloc[0] == days[20]


def test_scale_steps_on_an_immaterial_step_returns_an_empty_frame_with_columns():
    loc = np.r_[np.full(100, 3.0), np.full(100, 3.003)]  # x1.007: significant, immaterial
    steps = cd.scale_steps(pd.Series(loc, index=DAYS))
    assert steps.empty and list(steps.columns) == ["date", "step_log10", "factor", "label"]
