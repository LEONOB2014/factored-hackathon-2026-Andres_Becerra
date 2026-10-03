-- Last 20 transactions per product (rank 1 = most recent), normalized for serving and inquiry answers.
select
    product_id,
    row_number() over (partition by product_id order by transaction_ts_utc desc) as recency_rank,
    transaction_id,
    transaction_ts_local,
    transaction_type,
    amount,
    currency,
    transaction_status,
    response_meaning                                   as decline_or_status_reason,
    merchant_name,
    channel,
    transaction_country_code
from {{ ref('fct_transaction') }}
qualify recency_rank <= 20
