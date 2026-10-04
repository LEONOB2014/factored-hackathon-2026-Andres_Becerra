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


def test_evaluate_target_drops_features_with_no_value():
    df = _frame(True).assign(gone=np.nan)
    r = country.evaluate_target(df, "y", "t", ["x", "gone"], n_boot=5)
    assert r["dropped_empty_features"] == "gone" and r["auc"] > 0.8


def test_verdict_needs_enough_positives():
    df = _frame(True, n=2000)
    df["y"] = False
    df.loc[:5, "y"] = True
    r = country.evaluate_target(df, "y", "t", ["x"], n_boot=5)
    assert country.verdict(r) == "not evaluable (too few positives)"


def test_generated_series_match_the_template():
    import build_country_notebooks as gen

    for src in sorted(gen.TEMPLATE.glob("[0-9][0-9]_*.py")):
        for dataset, code in gen.SERIES:
            dst = gen.folder(dataset, code) / src.name
            assert dst.exists(), (
                f"{dst.name} missing for {dataset}/{code}: run scripts/build_country_notebooks.py"
            )
            assert dst.read_text() == gen.render(src.read_text(), code, dataset), (
                f"{dst} differs from the template"
            )


def test_render_keeps_only_the_blocks_of_its_scope_and_dataset():
    import build_country_notebooks as gen

    text = (
        "# a __COUNTRY_NAME__\n# <ALL>\n# whole\n# </ALL>\n# <COUNTRY>\n# one\n# </COUNTRY>\n"
        "# <BACKUP>\n# swapped\n# </BACKUP>\nPREFIX = '__PREFIX__'\n"
    )
    assert gen.render(text, "MX") == "# a Mexico\n# one\nPREFIX = 'country'\n"
    assert gen.render(text, "ALL", "backup") == (
        "# a All countries\n# whole\n# swapped\nPREFIX = 'backup'\n"
    )
    with pytest.raises(AssertionError):
        gen.render("# <ALL>\n# never closed\n", "ALL")


def test_full_months_drops_partial_first_and_last_months():
    days = pd.DataFrame({"local_date": pd.date_range("2024-06-17", "2024-09-25", freq="D")})
    kept = country.full_months(days).local_date
    assert kept.min() == pd.Timestamp("2024-07-01") and kept.max() == pd.Timestamp("2024-08-31")
    whole = pd.DataFrame({"local_date": pd.date_range("2024-07-01", "2024-08-31", freq="D")})
    assert len(country.full_months(whole)) == len(whole)


def test_scopes_cover_the_whole_bank():
    assert country.scope_codes("ALL") == ["MX", "CO", "AR"]
    assert country.scope_codes("CO") == ["CO"]
    assert country.SCOPES["ALL"].title == "The whole bank"
    assert set(country.SCOPES["ALL"].raw_names) >= {"México", "Mexico", "Colombia", "Argentina"}


@pytest.fixture
def main_with_backup(tmp_path):
    """A main lake with a quarantined backup that stops early and lacks one table."""
    lake = tmp_path / "lake"
    con = duckdb.connect()

    def write(zone, table, df, part):
        d = lake / zone / table / f"_partition_date={part}"
        d.mkdir(parents=True)
        df = df.assign(_partition_date=pd.Timestamp(part).date())
        con.register("df", df)
        con.sql(f"COPY df TO '{d / 'part-0.parquet'}' (FORMAT parquet)")
        con.unregister("df")

    tx = pd.DataFrame({"transaction_id": ["t1"], "customer_id": ["a"]})
    write("bronze_raw", "customers", pd.DataFrame({"customer_id": ["a"]}), "2026-06-17")
    write("bronze_raw", "transactions", tx, "2026-05-17")
    write("bronze_raw", "call_transcripts", pd.DataFrame({"transcript_id": ["x"]}), "2026-05-17")
    write("holdout_raw", "transactions", tx, "2026-05-18")
    write("holdout_raw", "call_transcripts", pd.DataFrame({"transcript_id": ["y"]}), "2026-05-18")
    q = country.BACKUP_DIR
    write(q, "customers", pd.DataFrame({"customer_id": ["a", "b"]}), "2026-06-17")
    write(q, "transactions", tx.assign(transaction_id="b1"), "2024-09-25")
    write(q, "complaints", pd.DataFrame({"complaint_id": ["c1"]}), "2026-05-17")
    write(q, "complaints", pd.DataFrame({"complaint_id": ["c2"]}), "2026-06-01")
    write("holdout_raw", "complaints", pd.DataFrame({"complaint_id": ["c3"]}), "2026-05-18")
    proof = lake / "manifests" / "bronze_raw_proof"
    proof.mkdir(parents=True)
    (proof / "transactions.json").write_text('{"files": {"main": {}}}')
    (proof / "backup_20260831__transactions.json").write_text('{"files": {"backup": {}}}')
    (lake / "corrections" / "applied").mkdir(parents=True)
    con.sql(
        f"COPY (SELECT 1 AS x) TO '{lake / 'corrections/applied/_genesis.parquet'}' (FORMAT parquet)"
    )
    return lake


def test_backup_lake_is_laid_out_as_main(main_with_backup, tmp_path):
    out = tmp_path / "backup"
    rows = country.build_backup_lake(main_with_backup, out).set_index(["zone", "table"])
    n = rows.rows_backup
    assert n[("bronze_raw", "customers")] == 2 and n[("bronze_raw", "transactions")] == 1
    assert (
        n[("bronze_raw", "complaints")] == 1 and n[("holdout_raw", "complaints")] == 1
    )  # split at the cutoff
    assert (
        n[("bronze_raw", "call_transcripts")] == 0
    )  # missing in the backup: empty, with main's schema
    assert n[("holdout_raw", "transactions")] == 0  # the backup stops before the cutoff
    assert rows.loc[("bronze_raw", "call_transcripts"), "rule"].startswith("missing")
    cols = duckdb.sql(
        f"select * from read_parquet('{out}/bronze_raw/call_transcripts/*/*.parquet')"
    ).columns
    assert "transcript_id" in cols
    part = out / "bronze_raw" / "transactions" / "_partition_date=2024-09-25" / "part-0.parquet"
    assert part.stat().st_nlink >= 2  # a hard link: byte-identical, no space
    reverse = out / country.BACKUP_DIR / "transactions"
    assert reverse.is_symlink() and reverse.resolve() == (
        main_with_backup / "bronze_raw" / "transactions"
    )
    assert "backup" in (out / "manifests" / "bronze_raw_proof" / "transactions.json").read_text()
    assert (out / "corrections" / "applied" / "_genesis.parquet").exists()
    again = country.build_backup_lake(main_with_backup, out)  # second call reads the stored summary
    assert len(again) == len(rows)
