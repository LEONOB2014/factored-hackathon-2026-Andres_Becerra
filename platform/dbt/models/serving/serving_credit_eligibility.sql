select
    customer_id, snapshot_date, credit_score_current, eligible_credit_card, eligible_personal_loan,
    array_to_string(decline_reasons, ',')              as decline_reasons, score_reason,
    timestamp '{{ var("as_of_date") }} 23:59:59'         as as_of_ts
from {{ ref('mart_credit_eligibility') }}
