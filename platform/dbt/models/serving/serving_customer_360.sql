-- Published to Postgres bank_serving.serving.customer_360 for low-latency agent/app lookups by customer.
-- Tokens only; re-identification happens in the presentation layer behind authorization.
select
    customer_id, document_token, country_code, segment, customer_status, tenure_days, credit_score,
    monthly_income_usd, accepts_marketing, n_products, n_active_products,
    array_to_string(product_types, ', ')               as product_types,
    deposits_usd, debt_usd, max_days_past_due, tx_count_90d, inflow_usd_90d, outflow_usd_90d,
    decline_rate_90d, last_tx_ts, logins_90d, contacts_90d, last_contact_reason, open_cases,
    complaints_365d, sla_breaches_365d, last_nps_score, last_csat_score,
    timestamp '{{ var("as_of_date") }} 23:59:59'          as as_of_ts
from {{ ref('mart_customer_360') }}
