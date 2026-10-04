-- Contribution-bounded input for DP spend statistics: each customer's monthly spend is clamped to
-- [0, var('dp_spend_clamp_usd', 20000)] so one customer can move the sum by at most the clamp.
select
    c.country_code,
    c.segment,
    strftime(t.transaction_ts_utc, '%Y-%m')                 as year_month,
    t.customer_id,
    least(greatest({{ exact_sum('t.amount_usd', "t.direction = -1 and t.transaction_status = 'Approved'") }}, 0),
          {{ var('dp_spend_clamp_usd', 20000) }})          as clamped_spend_usd
from {{ ref('int_transactions_enriched') }} t
join {{ ref('int_customer_profile') }} c using (customer_id)
group by all
