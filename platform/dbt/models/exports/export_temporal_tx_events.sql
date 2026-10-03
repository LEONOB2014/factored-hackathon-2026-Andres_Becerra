-- Continuous-time dynamic graph (TGN / JODIE / DyRep format): one interaction per transaction between a
-- customer (src) and a merchant (dst), ordered by time, with edge features and the fraud label.
-- Integer ids are dense and disjoint (merchants are offset after customers) as TGN loaders require.
{{ config(materialized='external', location='../../data/exports/temporal_tx_events.parquet') }}
with c as (select customer_id, dense_rank() over (order by customer_id) - 1 as idx from {{ ref('int_customer_profile') }}),
     m as (select merchant_name, dense_rank() over (order by merchant_name) - 1 as idx
           from (select distinct merchant_name from {{ ref('int_transactions_enriched') }} where merchant_name is not null)),
     n_c as (select count(*) as n from c)
select
    c.idx                                              as src,
    (select n from n_c) + m.idx                        as dst,
    epoch(f.anchor_ts)                                 as ts,
    f.transaction_id,
    f.log_amount,
    f.is_cross_border::int                             as is_cross_border,
    f.is_night::int                                    as is_night,
    f.tx_count_24h,
    coalesce(f.amount_zscore_vs_history, 0)            as amount_zscore_vs_history,
    f.channel,
    f.transaction_type,
    f.label_is_fraud::int                              as label,
    f.split
from {{ ref('feat_fraud_realtime_pit') }} f
join {{ ref('int_transactions_enriched') }} t using (transaction_id)
join c on c.customer_id = f.customer_id
join m on m.merchant_name = t.merchant_name
order by ts
