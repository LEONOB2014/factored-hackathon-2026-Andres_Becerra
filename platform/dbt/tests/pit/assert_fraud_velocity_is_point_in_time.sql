-- Point-in-time leakage test for feat_fraud_realtime_pit. For a deterministic sample of customers it
-- recomputes the 24 h velocity and the history baseline by brute force using only events at or before
-- the anchor time (excluding the row itself) and returns every row where the window function disagrees.
-- Any returned row means a feature saw the future (or missed the past).
with sample_customers as (
    select customer_id
    from {{ ref('int_customer_profile') }}
    where hash(customer_id) % 500 = 0
),
f as (
    select f.*
    from {{ ref('feat_fraud_realtime_pit') }} f
    join sample_customers using (customer_id)
),
brute as (
    select
        f.transaction_id,
        count(t.transaction_id) filter (where t.transaction_ts_utc >= f.anchor_ts - interval 24 hour) as tx_count_24h,
        count(t.transaction_id)                                                                    as hist_upper_bound
    from f
    left join {{ ref('int_transactions_enriched') }} t
      on t.customer_id = f.customer_id
     and t.transaction_ts_utc <= f.anchor_ts
     and t.transaction_id <> f.transaction_id
    group by 1
)
select f.transaction_id, f.tx_count_24h, b.tx_count_24h as expected_tx_count_24h,
       f.hist_tx_count, b.hist_upper_bound
from f join brute b using (transaction_id)
where f.tx_count_24h <> b.tx_count_24h
   or f.hist_tx_count > b.hist_upper_bound          -- history may never include later events
