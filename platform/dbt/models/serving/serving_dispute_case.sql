select
    complaint_id, customer_id, country_code, case_type, category, subcategory, reception_channel,
    came_via_regulator, priority, status, is_closed, claimed_amount, claimed_currency, created_ts_utc,
    hours_to_assignment, hours_to_first_response, hours_open_or_to_resolution, sla_breached,
    prior_disputes_365d, linked_transaction_id, link_confidence,
    to_json(evidence_transaction)                      as evidence_transaction_json,
    timestamp '{{ var("as_of_date") }} 23:59:59'         as as_of_ts
from {{ ref('mart_transaction_disputes') }}
