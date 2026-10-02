"""latam_eda.anomaly: transaction features and the injected-anomaly benchmark (notebooks 08–10)."""

import math

import duckdb
import numpy as np
import pandas as pd
import pytest

from latam_eda import anomaly

TX_COLUMNS = (
    "transaction_id, customer_id, transaction_date, transaction_type, channel, currency, "
    "transaction_status, transaction_country, merchant_name, is_fraud, fraud_score, amount, amount_usd"
)


@pytest.fixture
def tx_con():
    """In-memory `m_transactions` / `m_customers` covering every feature's edge case."""
    con = duckdb.connect()
    con.sql("""create table m_customers as select * from (values
        ('C1', 'México'), ('C2', 'Colombia'), ('C3', 'Argentina')) t(customer_id, country)""")
    con.sql(f"""create table m_transactions as select * from (values
        -- C1, Mexican: Saturday 15:00 UTC = 09:00 local, domestic spelled without accent
        ('T1', 'C1', timestamp '2024-01-06 15:00', 'purchase', 'app', 'USD', 'approved',
         'Mexico', 'Oxxo', false, 10, 10.0, 10.0),
        -- C1 again 5 h later, abroad
        ('T2', 'C1', timestamp '2024-01-06 20:00', 'purchase', 'web', 'USD', 'approved',
         'USA', null, false, 20, 1000.0, 1000.0),
        -- C2, Colombian, abroad on a Monday; local currency so amount_usd is used
        ('T3', 'C2', timestamp '2024-01-08 12:00', 'transfer', 'app', 'COP', 'approved',
         'Brazil', null, true, 90, 400000.0, 100.0),
        -- C2 domestic
        ('T4', 'C2', timestamp '2024-01-09 12:00', 'purchase', 'pos', 'COP', 'declined',
         'Colombia', 'Exito', false, 5, 40000.0, 10.0),
        -- C3: zero-value row is dropped; then three rows whose median is 1 USD
        ('T5', 'C3', timestamp '2024-01-10 12:00', 'fee', 'app', 'USD', 'approved',
         'Argentina', null, false, 0, 0.0, 0.0),
        ('T6', 'C3', timestamp '2024-01-11 12:00', 'purchase', 'app', 'USD', 'approved',
         'Argentina', 'Kiosco', false, 1, 1.0, 1.0),
        ('T7', 'C3', timestamp '2024-01-12 12:00', 'purchase', 'app', 'USD', 'approved',
         'Argentina', 'Kiosco', false, 1, 1.0, 1.0),
        ('T8', 'C3', timestamp '2024-01-13 12:00', 'purchase', 'app', 'USD', 'approved',
         'Argentina', 'Kiosco', false, 1, 1000.0, 1000.0)
        ) t({TX_COLUMNS})""")
    return con


@pytest.fixture
def features(tx_con):
    return anomaly.build_tx_features(tx_con, "m", n=1_000).set_index("transaction_id")


def test_features_include_every_model_input(features):
    assert set(anomaly.FEATURES) <= set(features.columns)


def test_non_positive_amounts_are_dropped(features):
    assert "T5" not in features.index
    assert len(features) == 7


def test_local_currency_rows_use_amount_usd(features):
    assert features.loc["T3", "usd"] == 100.0
    assert features.loc["T3", "log_usd"] == pytest.approx(math.log(100))


def test_time_features_use_utc_minus_6(features):
    assert features.loc["T1", "hour"] == 9
    assert features.loc["T1", "dow"] == 6  # Saturday (DuckDB: Sunday = 0)
    assert features.loc["T1", "is_weekend"] == 1
    assert features.loc["T3", "is_weekend"] == 0


def test_country_mismatch_for_every_customer_country(features):
    assert features.loc["T1", "country_mismatch"] == 0  # 'Mexico' is domestic for 'México'
    assert features.loc["T2", "country_mismatch"] == 1
    assert features.loc["T3", "country_mismatch"] == 1  # used to be NULL for non-Mexican customers
    assert features.loc["T4", "country_mismatch"] == 0
    assert features.country_mismatch.notna().all()


def test_merchant_flag(features):
    assert features.loc["T1", "has_merchant"] == 1
    assert features.loc["T2", "has_merchant"] == 0


def test_gap_and_velocity_per_customer(features):
    assert features.loc["T1", "log_gap_prev"] == pytest.approx(
        math.log1p(31_536_000)
    )  # first: 1 year
    assert features.loc["T2", "log_gap_prev"] == pytest.approx(math.log1p(5 * 3600))
    assert features.loc["T1", "n_last_24h"] == 0
    assert features.loc["T2", "n_last_24h"] == 1
    assert features.loc["T4", "n_last_24h"] == 1  # T3 is exactly 24 h earlier
    assert features.loc["T7", "n_last_24h"] == 1


def test_customer_level_aggregates(features):
    assert features.loc["T1", "cust_n_trx"] == 2
    assert features.loc["T8", "cust_n_trx"] == 3
    assert features.loc["T8", "ratio_to_cust_median"] == 50  # 1000 / median 1, clipped
    assert features.loc["T6", "ratio_to_cust_median"] == 1


def test_categoricals_are_integer_codes(features):
    for col in ("channel_code", "type_code", "currency_code", "status_code"):
        assert pd.api.types.is_integer_dtype(features[col])
        assert features[col].min() >= 0


def test_sample_is_reproducible_for_a_seed(tx_con):
    # a seeded reservoir sample used to differ between runs (multi-threaded window query)
    runs = {
        tuple(anomaly.build_tx_features(tx_con, "m", n=3, seed=1).transaction_id) for _ in range(30)
    }
    assert len(runs) == 1
    assert len(next(iter(runs))) == 3
    other = {
        tuple(anomaly.build_tx_features(tx_con, "m", n=3, seed=s).transaction_id)
        for s in range(2, 12)
    }
    assert len(other) > 1  # the seed does change the sample


def test_enrich_fraud_keeps_every_fraud_row_plus_n_others(tx_con):
    # the non-fraud sample used to be drawn before the fraud filter, so it could come back short
    for seed in range(30):
        df = anomaly.build_tx_features(tx_con, "m", n=1, seed=seed, enrich_fraud=True)
        assert sorted(df.is_fraud) == [False, True], seed
        assert "T3" in set(df.transaction_id)


def test_load_or_build_caches_to_derived(tx_con, tmp_path, monkeypatch):
    monkeypatch.setattr(anomaly, "DERIVED", tmp_path)
    built = anomaly.load_or_build(tx_con, "m", n=1_000)
    cache = tmp_path / "tx_features_m_1000.parquet"
    assert cache.exists()
    tx_con.sql("drop table m_transactions")  # a rebuild would now fail
    cached = anomaly.load_or_build(tx_con, "m", n=1_000)
    pd.testing.assert_frame_equal(built, cached)


def test_load_or_build_enriched_caches_separately(tx_con, tmp_path, monkeypatch):
    monkeypatch.setattr(anomaly, "DERIVED", tmp_path)
    anomaly.load_or_build_enriched(tx_con, "m", n=1)
    assert (tmp_path / "tx_features_m_1_fraudall.parquet").exists()


@pytest.fixture
def base():
    rng = np.random.default_rng(42)
    n = 10_000
    return pd.DataFrame(
        {
            "log_usd": rng.normal(4, 1, n),
            "hour": rng.integers(0, 24, n),
            "country_mismatch": rng.integers(0, 2, n),
            "n_last_24h": rng.integers(0, 3, n),
            "log_gap_prev": rng.uniform(5, 15, n),
            "ratio_to_cust_median": rng.uniform(0, 3, n),
        }
    )


def test_injection_rate_and_equal_shares(base):
    out = anomaly.inject_anomalies(base, rate=0.01, seed=0)
    assert out.is_injected.sum() == 100
    counts = out.loc[out.is_injected == 1, "anomaly_type"].value_counts()
    assert set(counts.index) == set(anomaly.INJECTED)
    assert (counts == 20).all()
    assert (out.loc[out.is_injected == 0, "anomaly_type"] == "").all()


def test_injection_is_deterministic_and_leaves_input_alone(base):
    before = base.copy()
    a = anomaly.inject_anomalies(base, seed=3)
    b = anomaly.inject_anomalies(base, seed=3)
    c = anomaly.inject_anomalies(base, seed=4)
    pd.testing.assert_frame_equal(base, before)
    pd.testing.assert_frame_equal(a, b)
    assert not a.anomaly_type.equals(c.anomaly_type)


def test_untouched_rows_keep_their_values(base):
    out = anomaly.inject_anomalies(base, seed=0)
    normal = out.is_injected == 0
    pd.testing.assert_frame_equal(out.loc[normal, base.columns], base.loc[normal])


def test_each_anomaly_type_has_its_signature(base):
    out = anomaly.inject_anomalies(base, rate=0.05, seed=0)

    def rows(t):
        return out[out.anomaly_type == t]

    spike = rows("amount_spike")
    assert (spike.log_usd > math.log(12_000)).all()
    assert (spike.ratio_to_cust_median == 50).all()

    foreign = rows("foreign_burst")
    assert (foreign.country_mismatch == 1).all()
    assert foreign.n_last_24h.between(3, 7).all()

    burst = rows("velocity_burst")
    assert burst.n_last_24h.between(8, 24).all()
    assert (burst.log_gap_prev < 3).all()

    slow = rows("low_and_slow")
    q88, q95 = base.log_usd.quantile([0.88, 0.95])
    assert slow.log_usd.between(q88, q95).all()
    assert slow.hour.between(1, 4).all()
    assert (slow.country_mismatch == 1).all()

    dormant = rows("dormant_reactivation")
    assert dormant.log_gap_prev.between(16, 17).all()
