{# Point-in-time fraud features over any enriched-transaction relation. One definition serves training
   (feat_fraud_realtime_pit), stream parity (feat_fraud_stream_parity) and documents the Flink job. #}
{% macro fraud_features(tx_rel, events_rel) %}
with tx as (
    select
        transaction_id, customer_id, product_id, transaction_ts_utc, amount_usd, transaction_type, channel,
        transaction_category, merchant_name, transaction_country_code, is_cross_border, local_hour, is_weekend,
        transaction_status, latitude, longitude, product_family, is_fraud,
        ln(1 + amount_usd) as log_amount
    from {{ tx_rel }}
),
w as (
    select
        tx.*,
        -- velocity (RANGE windows over time, current row excluded)
        count(*)        over (partition by customer_id order by transaction_ts_utc
                              range between interval 1 hour preceding and current row exclude current row)  as tx_count_1h,
        count(*)        over (partition by customer_id order by transaction_ts_utc
                              range between interval 24 hour preceding and current row exclude current row) as tx_count_24h,
        coalesce(sum(amount_usd) over (partition by customer_id order by transaction_ts_utc
                              range between interval 24 hour preceding and current row exclude current row), 0) as amount_usd_24h,
        count(*)        over (partition by customer_id order by transaction_ts_utc
                              range between interval 7 day preceding and current row exclude current row)   as tx_count_7d,
        count(*) filter (where transaction_status = 'Declined')
                        over (partition by customer_id order by transaction_ts_utc
                              range between interval 24 hour preceding and current row exclude current row) as declines_24h,
        -- customer baseline from all prior history (expanding window)
        avg(log_amount)         over (partition by customer_id order by transaction_ts_utc
                                      rows between unbounded preceding and 1 preceding)                    as hist_mean_log_amount,
        stddev_samp(log_amount) over (partition by customer_id order by transaction_ts_utc
                                      rows between unbounded preceding and 1 preceding)                    as hist_std_log_amount,
        max(amount_usd)         over (partition by customer_id order by transaction_ts_utc
                                      rows between unbounded preceding and 1 preceding)                    as hist_max_amount_usd,
        count(*)                over (partition by customer_id order by transaction_ts_utc
                                      rows between unbounded preceding and 1 preceding)                    as hist_tx_count,
        avg(local_hour)         over (partition by customer_id order by transaction_ts_utc
                                      rows between unbounded preceding and 1 preceding)                    as hist_mean_hour,
        -- recency and novelty
        lag(transaction_ts_utc) over (partition by customer_id order by transaction_ts_utc)                as prev_ts,
        lag(latitude)           over (partition by customer_id order by transaction_ts_utc)                as prev_lat,
        lag(longitude)          over (partition by customer_id order by transaction_ts_utc)                as prev_lon,
        row_number() over (partition by customer_id, merchant_name order by transaction_ts_utc) = 1         as is_new_merchant,
        row_number() over (partition by customer_id, transaction_country_code order by transaction_ts_utc) = 1 as is_new_country,
        row_number() over (partition by customer_id, channel order by transaction_ts_utc) = 1               as is_new_channel
    from tx
),
login as (   -- most recent digital login at or before the transaction (ASOF = point-in-time join)
    select w.transaction_id, l.event_ts_utc as last_login_ts, l.ip_country_code as last_login_ip_country,
           l.channel as last_login_channel
    from w
    asof left join (
        select customer_id, event_ts_utc, ip_country_code, channel
        from {{ events_rel }}
        where event_type = 'Login' and customer_id is not null
    ) l on l.customer_id = w.customer_id and l.event_ts_utc <= w.transaction_ts_utc
)
select
    w.transaction_id,
    w.customer_id,
    w.product_id,
    w.transaction_ts_utc                                                       as anchor_ts,
    -- context of the event itself
    w.amount_usd,
    w.log_amount,
    w.transaction_type,
    w.channel,
    w.transaction_category,
    w.product_family,
    w.is_cross_border,
    w.local_hour,
    w.local_hour between 0 and 5                                               as is_night,
    w.is_weekend,
    -- velocity
    w.tx_count_1h,
    w.tx_count_24h,
    w.tx_count_7d,
    w.amount_usd_24h,
    w.declines_24h,
    -- deviation from the customer's own history
    w.hist_tx_count,
    (w.log_amount - w.hist_mean_log_amount) / nullif(w.hist_std_log_amount, 0) as amount_zscore_vs_history,
    w.amount_usd / nullif(w.hist_max_amount_usd, 0)                            as amount_to_hist_max,
    abs(w.local_hour - w.hist_mean_hour)                                       as hour_deviation,
    -- recency, dormancy, novelty
    date_diff('second', w.prev_ts, w.transaction_ts_utc) / 3600.0              as hours_since_prev_tx,
    coalesce(date_diff('day', w.prev_ts, w.transaction_ts_utc) >= {{ var('dormancy_days') }}, false)
                                                                               as is_dormant_reactivation,
    w.prev_ts is null                                                          as is_first_tx,
    w.is_new_merchant and w.prev_ts is not null                                as is_new_merchant,
    w.is_new_country and w.prev_ts is not null                                 as is_new_country,
    w.is_new_channel and w.prev_ts is not null                                 as is_new_channel,
    -- geo-velocity (only when both points have coordinates: 29 % of ATM/POS rows do)
    {{ haversine_km('w.prev_lat', 'w.prev_lon', 'w.latitude', 'w.longitude') }} as km_from_prev_tx,
    {{ haversine_km('w.prev_lat', 'w.prev_lon', 'w.latitude', 'w.longitude') }}
        / greatest(date_diff('second', w.prev_ts, w.transaction_ts_utc) / 3600.0, 1 / 60.0)
                                                                               as implied_speed_kmh,
    -- digital context
    date_diff('minute', l.last_login_ts, w.transaction_ts_utc)                 as minutes_since_last_login,
    l.last_login_channel,
    l.last_login_ip_country,
    -- label and out-of-time split
    w.is_fraud                                                                 as label_is_fraud,
    -- out-of-time split; rows inside the embargo before each boundary are excluded from training so that
    -- no 7-day feature window straddles train/valid or valid/test
    case when w.transaction_ts_utc < timestamp '{{ var("fraud_train_end") }}' - interval {{ var("embargo_days") }} day then 'train'
         when w.transaction_ts_utc < timestamp '{{ var("fraud_train_end") }}' then 'embargo'
         when w.transaction_ts_utc < timestamp '{{ var("fraud_valid_end") }}' - interval {{ var("embargo_days") }} day then 'valid'
         when w.transaction_ts_utc < timestamp '{{ var("fraud_valid_end") }}' then 'embargo'
         when w.transaction_ts_utc < timestamp '{{ var("stream_cutoff") }}' then 'test'
         else 'stream_holdout' end                                             as split
from w
left join login l using (transaction_id)
{% endmacro %}
