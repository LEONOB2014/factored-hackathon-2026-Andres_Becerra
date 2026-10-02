"""Shared feature engineering and semi-synthetic anomaly injection for notebooks 08–10."""

import numpy as np
import pandas as pd

from .data import DERIVED

FEATURES = [
    "log_usd",
    "hour",
    "dow",
    "is_weekend",
    "channel_code",
    "type_code",
    "currency_code",
    "status_code",
    "country_mismatch",
    "has_merchant",
    "log_gap_prev",
    "n_last_24h",
    "ratio_to_cust_median",
    "cust_n_trx",
]
INJECTED = [
    "amount_spike",
    "foreign_burst",
    "velocity_burst",
    "low_and_slow",
    "dormant_reactivation",
]


def build_tx_features(
    con, prefix: str, n: int = 400_000, seed: int = 0, enrich_fraud: bool = False
) -> pd.DataFrame:
    """Per-transaction behavioural features computed over the *whole* folder, then sampled.

    enrich_fraud=True keeps *every* is_fraud row plus a sample of n non-fraud rows (for supervised fraud models).
    """
    final = (
        f"select * from (select * from f where not coalesce(is_fraud, false) using sample {n} rows (reservoir, {seed})) union all select * from f where is_fraud"
        if enrich_fraud
        else f"select * from f using sample {n} rows (reservoir, {seed})"
    )
    q = f"""
    with base as (
      select t.transaction_id, t.customer_id, t.transaction_date ts, t.transaction_type, t.channel, t.currency, t.transaction_status,
             t.transaction_country, t.merchant_name, t.is_fraud, t.fraud_score,
             case when t.currency = 'USD' then t.amount else t.amount_usd end usd,
             c.country cust_country
      from {prefix}_transactions t join {prefix}_customers c using(customer_id)),
    f as (
      select *,
        ln(usd) log_usd,
        hour(ts - interval 6 hour) as "hour", dayofweek(ts - interval 6 hour) as dow,
        (dayofweek(ts - interval 6 hour) in (0, 6))::int is_weekend,
        (transaction_country not in (cust_country, case cust_country when 'México' then 'Mexico' end))::int country_mismatch,
        (merchant_name is not null)::int has_merchant,
        ln(1 + coalesce(date_diff('second', lag(ts) over w, ts), 31536000)) log_gap_prev,
        count(*) over (partition by customer_id order by ts range between interval 24 hours preceding and current row) - 1 n_last_24h,
        usd / nullif(median(usd) over (partition by customer_id), 0) ratio_to_cust_median,
        count(*) over (partition by customer_id) cust_n_trx
      from base where usd > 0
      window w as (partition by customer_id order by ts))
    {final}"""
    df = con.sql(q).df()
    for src, dst in (
        ("channel", "channel_code"),
        ("transaction_type", "type_code"),
        ("currency", "currency_code"),
        ("transaction_status", "status_code"),
    ):
        df[dst] = df[src].astype("category").cat.codes
    df["ratio_to_cust_median"] = df.ratio_to_cust_median.clip(0, 50)
    return df


def inject_anomalies(df: pd.DataFrame, rate: float = 0.01, seed: int = 0) -> pd.DataFrame:
    """Return a copy with ~`rate` of rows turned into labelled anomalies (5 types, equal share)."""
    rng = np.random.default_rng(seed)
    out = df.copy()
    out["anomaly_type"] = ""
    k = int(len(out) * rate)
    idx = rng.choice(len(out), size=k, replace=False)
    groups = np.array_split(idx, len(INJECTED))
    q = out.log_usd.quantile([0.88, 0.95, 0.99]).values
    for typ, ids in zip(INJECTED, groups):
        ii = out.index[ids]
        m = len(ii)
        if (
            typ == "amount_spike"
        ):  # point anomaly: value above anything the data contains (cap ≈ 9,999 USD)
            out.loc[ii, "log_usd"] = np.log(rng.uniform(12_000, 100_000, m))
            out.loc[ii, "ratio_to_cust_median"] = 50.0
        elif (
            typ == "foreign_burst"
        ):  # collective: several foreign-country transactions within hours
            out.loc[ii, "country_mismatch"] = 1
            out.loc[ii, "n_last_24h"] = rng.integers(3, 8, m)
            out.loc[ii, "log_gap_prev"] = rng.uniform(6, 10, m)
        elif typ == "velocity_burst":  # collective: card-testing style burst
            out.loc[ii, "n_last_24h"] = rng.integers(8, 25, m)
            out.loc[ii, "log_gap_prev"] = rng.uniform(0.5, 3, m)
        elif typ == "low_and_slow":  # contextual: four mild, individually ordinary shifts at once
            out.loc[ii, "log_usd"] = rng.uniform(q[0], q[1], m)
            out.loc[ii, "hour"] = rng.integers(1, 5, m)
            out.loc[ii, "n_last_24h"] = rng.integers(1, 3, m)
            out.loc[ii, "log_gap_prev"] = rng.uniform(10, 11.3, m)
            out.loc[ii, "country_mismatch"] = 1
        elif typ == "dormant_reactivation":  # contextual: long silence followed by a large movement
            out.loc[ii, "log_gap_prev"] = rng.uniform(16.0, 17.0, m)
            out.loc[ii, "log_usd"] = rng.uniform(q[1], q[2], m)
        out.loc[ii, "anomaly_type"] = typ
    out["is_injected"] = (out.anomaly_type != "").astype(int)
    return out


def load_or_build(con, prefix: str, n: int = 400_000, seed: int = 0) -> pd.DataFrame:
    path = DERIVED / f"tx_features_{prefix}_{n}.parquet"
    if path.exists():
        return pd.read_parquet(path)
    df = build_tx_features(con, prefix, n, seed)
    df.to_parquet(path)
    return df


def load_or_build_enriched(con, prefix: str, n: int = 300_000, seed: int = 1) -> pd.DataFrame:
    path = DERIVED / f"tx_features_{prefix}_{n}_fraudall.parquet"
    if path.exists():
        return pd.read_parquet(path)
    df = build_tx_features(con, prefix, n, seed, enrich_fraud=True)
    df.to_parquet(path)
    return df
