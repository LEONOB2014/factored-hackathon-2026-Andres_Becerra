select
    product_id, customer_id, country_code, product_type, product_status, is_blocked, expiration_date,
    days_to_expiry, is_active_but_expired, credit_limit, current_balance, utilization,
    current_decline_streak, declines_do_not_honor_30d, declines_invalid_card_30d,
    declines_insufficient_funds_30d, declines_expired_30d, foreign_tx_90d,
    array_to_string(foreign_countries_90d, ',')        as foreign_countries_90d,
    open_cases, contacts_30d, next_best_action,
    timestamp '{{ var("as_of_date") }} 23:59:59'         as as_of_ts
from {{ ref('mart_card_support') }}
