-- Transaction fact (grain: transaction) with conformed keys. Customer and product attributes as they were
-- at transaction time are reached through customer_sk / product_sk (SCD2, point-in-time join).
select
    t.*,
    cast(t.transaction_ts_utc as date)                   as date_key,
    dc.customer_sk,
    dp.product_sk,
    md5(t.merchant_name)                                 as merchant_id
from {{ ref('int_transactions_enriched') }} t
left join {{ ref('dim_customer') }} dc
  on dc.customer_id = t.customer_id and t.transaction_ts_utc >= dc.valid_from and t.transaction_ts_utc < dc.valid_to
left join {{ ref('dim_product') }} dp
  on dp.product_id = t.product_id and t.transaction_ts_utc >= dp.valid_from and t.transaction_ts_utc < dp.valid_to
