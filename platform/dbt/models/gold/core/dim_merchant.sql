-- Merchant dimension derived from transactions (the source has no merchant master: 24 merchants).
select
    md5(merchant_name)                                   as merchant_id,
    merchant_name,
    mode(transaction_category)                           as main_category,
    min(transaction_ts_utc)                              as first_seen_ts,
    max(transaction_ts_utc)                              as last_seen_ts,
    count(*)                                             as n_transactions
from {{ ref('int_transactions_enriched') }}
where merchant_name is not null
group by merchant_name
