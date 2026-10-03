-- One row per product for inquiry answers; nested history serialized to JSON for Postgres jsonb.
select
    product_id, customer_id, country_code, product_type, product_family, product_status, currency,
    current_balance, balance_usd, available_credit, utilization, days_past_due, pending_count,
    pending_amount, declined_30d, reversed_30d, last_decline_reason, last_decline_action,
    last_deposit_ts, last_payment_ts, last_payment_amount,
    to_json(declines_by_code_90d)                      as declines_by_code_90d_json,
    to_json(last_20_transactions)                      as last_20_transactions_json,
    timestamp '{{ var("as_of_date") }} 23:59:59'         as as_of_ts
from {{ ref('mart_account_payment_inquiry') }}
