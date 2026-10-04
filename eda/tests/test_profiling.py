"""latam_eda.profiling: exact DuckDB statistics on a tiny in-memory table (no dataset)."""

import duckdb
import matplotlib as mpl
import pandas as pd
import pytest

from latam_eda import profiling as p
from latam_eda import theme


@pytest.fixture
def con():
    con = duckdb.connect()
    con.sql(
        """create table t as select * from (values
            ('T1', 'C1', 10.0, 'MX', true,  timestamp '2024-01-01 09:00', 'ana@x.com'),
            ('T2', 'C1', 20.0, 'MX', false, timestamp '2024-01-01 10:00', 'bo@y.org'),
            ('T3', 'C2', null, 'CO', false, timestamp '2024-01-02 09:00', null),
            ('T4', 'C3', 0.0,  'N/A', null, timestamp '2024-01-08 23:00', 'cy@z.net'),
            ('T4', 'C3', 1000.0, '', false, null, 'dee@x.com')
        ) v(transaction_id, customer_id, amount, country, is_fraud, transaction_date, email)"""
    )
    return con


def test_kind_assigns_analytical_roles(con):
    kinds = p.columns(con, "t").set_index("column")["kind"].to_dict()
    assert kinds == {
        "transaction_id": "identifier",
        "customer_id": "identifier",
        "amount": "numeric",
        "country": "categorical",
        "is_fraud": "boolean",
        "transaction_date": "temporal",
        "email": "pii",
    }


def test_overview_separates_nulls_from_disguised_missing(con):
    ov = p.overview(con, "t").set_index("column")
    assert ov.attrs["rows"] == 5
    assert ov.loc["amount", "nulls"] == 1
    assert ov.loc["country", "nulls"] == 0
    assert ov.loc["country", "placeholders"] == 2  # 'N/A' and ''
    assert ov.loc["country", "missing_pct"] == pytest.approx(40.0)
    assert ov.loc["customer_id", "distinct"] == 3


def test_time_of_day_is_categorical_not_temporal():
    assert p.kind("opening_time", "TIME") == "categorical"
    assert p.kind("event_date", "TIMESTAMP") == "temporal"
    assert p.kind("process_date", "DATE") == "temporal"


def test_overview_handles_an_all_null_text_column():
    con = duckdb.connect()
    con.sql("create table e as select 1 as id, null::varchar as note")
    ov = p.overview(con, "e").set_index("column")
    assert ov.loc["note", "nulls"] == 1 and ov.loc["note", "placeholders"] == 0


def test_pk_check_counts_duplicates(con):
    assert p.pk_check(con, "t", "transaction_id") == {
        "pk": "transaction_id",
        "rows": 5,
        "null_keys": 0,
        "duplicate_keys": 1,
    }


def test_numeric_summary_matches_pandas(con):
    s = p.numeric_summary(con, "t").loc["amount"]
    ref = pd.Series([10.0, 20.0, 0.0, 1000.0])
    assert s["count"] == 4
    assert s["mean"] == pytest.approx(ref.mean())
    assert s["std"] == pytest.approx(ref.std())
    assert s["p50"] == pytest.approx(ref.median())
    assert s["zero_share"] == pytest.approx(0.25)
    assert s["iqr_outlier_share"] == pytest.approx(0.25)  # 1000 is the only outlier


def test_value_counts_folds_the_tail(con):
    vc = p.value_counts(con, "t", "customer_id", top=2)
    assert vc["n"].sum() == 5
    assert vc["value"].iloc[-1] == "(other 1)"
    assert vc["cum_pct"].iloc[-1] == pytest.approx(100.0)
    assert vc.attrs["cardinality"] == 3


def test_pattern_profile_hides_values(con):
    pats = p.pattern_profile(con, "t", "email")
    assert set(pats["pattern"]) == {"A@A.A", "(null)"}
    assert "ana" not in pats.to_string()


def test_binned_hist_covers_every_value(con):
    h = p.binned_hist(con, "t", "amount", bins=4)
    assert h["n"].sum() == 4
    assert h["left"].iloc[0] == 0.0 and h["right"].iloc[-1] == pytest.approx(1000.0)


def test_binned_hist_log_drops_non_positive(con):
    h = p.binned_hist(con, "t", "amount", bins=3, log=True)
    assert h["n"].sum() == 3
    assert h.attrs["excluded"] == 1
    assert h["left"].iloc[0] == pytest.approx(10.0)


def test_crosstab_normalisations(con):
    ct = p.crosstab(con, "t", "customer_id", "country")
    assert ct.values.sum() == 5
    rows = p.crosstab(con, "t", "customer_id", "country", normalize="row")
    assert rows.sum(axis=1).round(6).eq(100).all()
    assert p.crosstab(con, "t", "customer_id", "country", normalize="all").values.sum() == (
        pytest.approx(100)
    )


def test_cramers_v_bounds():
    a = pd.Series(list("aabbccaabbcc") * 5)
    assert p.cramers_v(a, a) == pytest.approx(1.0)
    noise = pd.Series(list("xyxyxyxyxyxy") * 5)
    assert 0.0 <= p.cramers_v(a, noise) < 0.2
    m = p.cramers_v_matrix(pd.DataFrame({"a": a, "b": noise}), ["a", "b"])
    assert (m.values == m.values.T).all()


def test_sample_is_reproducible(con):
    a = p.sample(con, "t", n=3, key="transaction_id")
    b = p.sample(con, "t", n=3, key="transaction_id")
    assert len(a) == 3 and a.equals(b)
    assert len(p.sample(con, "t", n=10)) == 5  # small tables come back whole


def test_time_profile_and_weekday_hour(con):
    days = p.time_profile(con, "t", "transaction_date", "week")
    assert days["value"].sum() == 4
    grid = p.weekday_hour(con, "t", "transaction_date")
    assert grid.shape == (7, 24)
    assert grid.loc["Mon", 9] == 1 and grid.loc["Mon"].sum() == 3  # 2024-01-01 is a Monday
    with pytest.raises(ValueError):
        p.time_profile(con, "t", "transaction_date", "hour")


def test_safe_drops_pii_and_text(con):
    df = con.sql("select *, 'hello' as description from t").df()
    assert not {"email", "description"} & set(p.safe(df).columns)


def test_register_mpl_uses_the_palette():
    with mpl.rc_context():
        theme.register_mpl()
        assert mpl.rcParams["axes.facecolor"] == theme.SURFACE
        cycle = [c["color"] for c in mpl.rcParams["axes.prop_cycle"]]
        assert cycle == theme.CATEGORICAL
    assert theme.cmap_div().N == 256
    assert theme.SEQ_SCALE[0][0] == 0 and theme.SEQ_SCALE[-1][0] == pytest.approx(1)
