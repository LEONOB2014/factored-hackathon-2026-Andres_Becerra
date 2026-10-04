"""The country series library on synthetic inputs (no dataset): calendar, lake cut, learnability helpers."""

from datetime import date

import duckdb
import numpy as np
import pandas as pd
import pytest

from latam_eda import country


def test_mexico_bank_holidays_extend_the_labour_law():
    cal = country.calendar("MX", "2025-01-01", "2025-12-31").set_index("local_date")
    for d in (date(2025, 4, 17), date(2025, 4, 18), date(2025, 11, 2), date(2025, 12, 12)):
        assert cal.loc[d, "is_holiday"], d  # banking holidays absent from the labour law
    assert cal.loc[date(2025, 9, 16), "is_holiday"]  # Independence Day (statutory)
    assert not cal.loc[date(2025, 9, 17), "is_holiday"]


def test_fortnightly_paydays_move_back_to_the_previous_business_day():
    cal = country.calendar("MX", "2025-03-01", "2025-03-31").set_index("local_date")
    assert cal.loc[date(2025, 3, 14), "is_payday"]  # the 15th is a Saturday
    assert not cal.loc[date(2025, 3, 15), "is_payday"]
    assert cal.loc[date(2025, 3, 31), "is_payday"]
    assert cal.loc[date(2025, 3, 17), "days_since_payday"] == 3


def test_argentina_pays_monthly_on_the_first_business_day():
    cal = country.calendar("AR", "2025-06-01", "2025-06-30")
    pays = cal[cal.is_payday].local_date.tolist()
    assert len(pays) == 1 and pays[0].day <= 4
    assert cal.set_index("local_date").loc[pays[0], "is_business_day"]


def test_bonus_months_follow_each_country():
    assert set(
        country.calendar("CO", "2025-01-01", "2025-12-31").query("is_bonus_month").month
    ) == {6, 12}
    assert set(
        country.calendar("MX", "2025-01-01", "2025-12-31").query("is_bonus_month").month
    ) == {12}


@pytest.fixture
def tiny_lake(tmp_path):
    lake = tmp_path / "lake"
    con = duckdb.connect()

    def write(zone, table, df, part="2025-01-01"):
        d = lake / zone / table / f"_partition_date={part}"
        d.mkdir(parents=True)
        df = df.assign(_partition_date=pd.Timestamp(part).date(), _record_no=range(len(df)))
        con.register("df", df)
        con.sql(f"COPY df TO '{d / 'part-0.parquet'}' (FORMAT parquet)")
        con.unregister("df")

    write(
        "bronze_raw",
        "customers",
        pd.DataFrame({"customer_id": ["a", "b", "c"], "country": ["México", "Colombia", "México"]}),
    )
    write(
        "bronze_raw",
        "transactions",
        pd.DataFrame({"customer_id": ["a", "b", "c", "b"], "amount": ["1", "2", "3", "4"]}),
    )
    write(
        "bronze_raw",
        "digital_events",
        pd.DataFrame(
            {
                "customer_id": ["a", "", "", "b"],
                "ip_country": ["México", "Mexico", "Colombia", "Colombia"],
            }
        ),
    )
    write("bronze_raw", "branches", pd.DataFrame({"branch_id": ["x"], "country": ["Colombia"]}))
    write(
        "holdout_raw",
        "transactions",
        pd.DataFrame({"customer_id": ["a", "b"], "amount": ["5", "6"]}),
    )
    for d in ("corrections/applied", "manifests/bronze_raw_proof"):
        (lake / d).mkdir(parents=True)
    return lake


def test_country_lake_cut_by_customer_and_anonymous_ip(tiny_lake, tmp_path):
    out = tmp_path / "mx"
    rows = country.build_country_lake("MX", tiny_lake, out).set_index(["zone", "table"]).rows_kept
    assert rows[("bronze_raw", "customers")] == 2
    assert rows[("bronze_raw", "transactions")] == 2
    assert (
        rows[("bronze_raw", "digital_events")] == 2
    )  # customer a, plus the anonymous 'Mexico' event
    assert rows[("holdout_raw", "transactions")] == 1
    assert (out / "bronze_raw" / "branches").is_symlink()  # reference data is shared
    assert (out / "corrections").is_symlink() and (out / "manifests").is_symlink()
    kept = duckdb.sql(
        f"select * from read_parquet('{out}/bronze_raw/transactions/*/*.parquet')"
    ).df()
    assert set(kept.customer_id) == {"a", "c"} and "_record_no" in kept  # lineage columns survive
    again = country.build_country_lake("MX", tiny_lake, out)  # second call reads the stored summary
    assert len(again) == len(rows)


def test_hanley_mcneil_matches_the_closed_form():
    assert country.hanley_mcneil(0.5, 100, 100) == pytest.approx(0.0409, abs=1e-3)
    assert country.hanley_mcneil(0.5, 26, 24000) > 4 * country.hanley_mcneil(0.5, 676, 715000)


def _frame(signal: bool, n: int = 20000, seed: int = 0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    x = rng.normal(size=n)
    logit = (2.5 * x if signal else 0) - 3
    return pd.DataFrame(
        {
            "t": pd.date_range("2024-01-01", periods=n, freq="h"),
            "x": x,
            "cat": rng.choice(["a", "b"], n),
            "y": rng.random(n) < 1 / (1 + np.exp(-logit)),
        }
    )


def test_evaluate_target_finds_signal_and_its_absence():
    good = country.evaluate_target(_frame(True), "y", "t", ["x", "cat"], n_boot=20)
    assert good["auc"] > 0.8 and country.verdict(good).startswith("learnable")
    none = country.evaluate_target(_frame(False), "y", "t", ["x", "cat"], n_boot=20)
    assert (
        none["auc_lo"] < 0.5 < none["auc_hi"] and country.verdict(none) == "no evidence of signal"
    )


def test_verdict_needs_enough_positives():
    df = _frame(True, n=2000)
    df["y"] = False
    df.loc[:5, "y"] = True
    r = country.evaluate_target(df, "y", "t", ["x"], n_boot=5)
    assert country.verdict(r) == "not evaluable (too few positives)"


def test_generated_country_series_match_the_template():
    import build_country_notebooks as gen

    for src in sorted(gen.TEMPLATE.glob("[0-9][0-9]_*.py")):
        for code in gen.NAMES:
            dst = gen.ROOT / "notebooks" / f"country_{code.lower()}" / src.name
            assert dst.exists(), (
                f"{dst.name} missing for {code}: run scripts/build_country_notebooks.py"
            )
            assert dst.read_text() == gen.render(src.read_text(), code), (
                f"{dst} differs from the template"
            )
