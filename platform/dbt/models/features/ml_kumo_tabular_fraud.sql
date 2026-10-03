-- Context/query set for an in-context tabular foundation model (nvidia/Kumo-Tabular, TabPFN/TabICL-style):
-- all fraud rows plus a fixed-seed 1 % sample of non-fraud rows from the point-in-time feature table.
-- In-context models take a bounded context, so the sample is stratified by split; class weights are
-- restored at evaluation time with the sampling rate (`sample_weight`).
{{ config(materialized='external', location=env_var('LATAM_LAKE_DIR', '../../data/lake') ~ '/features/ml_kumo_tabular_fraud.parquet') }}
select
    transaction_id, split, label_is_fraud,
    case when label_is_fraud then 1.0 else 100.0 end as sample_weight,
    log_amount, transaction_type, channel, transaction_category, product_family, is_cross_border, local_hour,
    is_night, is_weekend, tx_count_1h, tx_count_24h, tx_count_7d, amount_usd_24h, declines_24h, hist_tx_count,
    amount_zscore_vs_history, amount_to_hist_max, hour_deviation, hours_since_prev_tx, is_dormant_reactivation,
    is_first_tx, is_new_merchant, is_new_country, is_new_channel, km_from_prev_tx, implied_speed_kmh,
    minutes_since_last_login
from {{ ref('feat_fraud_realtime_pit') }}
where label_is_fraud or hash(transaction_id || 'kumo-seed-42') % 100 = 0
