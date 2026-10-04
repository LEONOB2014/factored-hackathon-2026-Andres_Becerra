-- Warm-start state for the streaming scorer: per customer, the history the online features need when
-- the stream begins at var('stream_cutoff'). Loaded into bank_serving.online_features before replay so the
-- first streamed transaction sees the same history as the batch features (parity by construction).
with tx as (
    select * from {{ ref('int_transactions_enriched') }}
),
last_tx as (
    select customer_id, arg_max(latitude, (transaction_ts_utc, transaction_id)) as last_lat,
           arg_max(longitude, (transaction_ts_utc, transaction_id)) as last_lon, max(transaction_ts_utc) as last_tx_ts
    from tx group by 1
)
select
    t.customer_id,
    count(*)                                            as hist_tx_count,
    {{ exact_avg('ln(1 + t.amount_usd)') }}            as hist_mean_log_amount,
    {{ exact_stddev('ln(1 + t.amount_usd)') }}         as hist_std_log_amount,
    {{ exact_sum('ln(1 + t.amount_usd)') }}            as hist_sum_log_amount,
    {{ exact_sum('power(ln(1 + t.amount_usd), 2)') }} as hist_sumsq_log_amount,
    max(t.amount_usd)                                   as hist_max_amount_usd,
    sum(t.local_hour)                                   as hist_sum_hour,
    to_json(list(distinct t.merchant_name order by t.merchant_name) filter (where t.merchant_name is not null)) as seen_merchants_json,
    to_json(list(distinct t.transaction_country_code order by t.transaction_country_code)) as seen_countries_json,
    to_json(list(distinct t.channel order by t.channel)) as seen_channels_json,
    l.last_tx_ts,
    l.last_lat,
    l.last_lon,
    timestamp '{{ var("stream_cutoff") }}'               as state_as_of_ts
from tx t join last_tx l using (customer_id)
group by t.customer_id, l.last_tx_ts, l.last_lat, l.last_lon
