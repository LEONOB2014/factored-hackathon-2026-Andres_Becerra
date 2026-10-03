-- Point-in-time credit features: one row per customer and month-end for the last 12 months.
-- Columns ending in _pit are computed only from events before the snapshot date. Columns ending in
-- _current come from current-state dimensions (no history exists yet) and are NOT safe for training a
-- model on past months: they become safe once the SCD2 snapshots have accumulated history.
with monthly as (
    select
        m.*,
        sum(inflow_usd)  over w3 / 3.0                           as avg_inflow_usd_3m,
        sum(outflow_usd) over w3 / 3.0                           as avg_outflow_usd_3m,
        sum(payments_usd) over w3 / 3.0                          as avg_payments_usd_3m,
        stddev_samp(inflow_usd) over w6                          as inflow_volatility_6m,
        count(*) filter (where inflow_usd > 0) over w6           as months_with_inflow_6m,
        sum(insufficient_funds_declines) over w3                 as nsf_declines_3m,
        max(max_outflow_usd) over w6                             as max_outflow_usd_6m,
        sum(n_tx) over w3                                        as tx_count_3m
    from {{ ref('int_customer_month_tx') }} m
    window w3 as (partition by customer_id order by month_start rows between 2 preceding and current row),
           w6 as (partition by customer_id order by month_start rows between 5 preceding and current row)
),
snap as (
    select
        customer_id,
        cast(month_start + interval 1 month - interval 1 day as date)   as snapshot_date,
        avg_inflow_usd_3m, avg_outflow_usd_3m, avg_payments_usd_3m, inflow_volatility_6m,
        months_with_inflow_6m, nsf_declines_3m, max_outflow_usd_6m, tx_count_3m
    from monthly
    where month_start >= date_trunc('month', {{ as_of() }}) - interval 12 month
      and month_start <  date_trunc('month', {{ as_of() }})
),
holdings as (   -- product holdings as of each snapshot date, from opening dates (PIT-safe)
    select s.customer_id, s.snapshot_date,
           count(p.product_id)                                       as n_products_pit,
           bool_or(p.product_family = 'credit_card')                 as has_credit_card_pit,
           bool_or(p.product_family = 'loan')                        as has_loan_pit,
           max(date_diff('day', p.opening_date, s.snapshot_date))    as oldest_product_age_days_pit
    from snap s
    left join {{ ref('int_products_enriched') }} p
      on p.customer_id = s.customer_id and p.opening_date <= s.snapshot_date
    group by all
)
select
    s.customer_id,
    s.snapshot_date,
    -- PIT-safe behaviour
    s.avg_inflow_usd_3m                              as avg_inflow_usd_3m_pit,
    s.avg_outflow_usd_3m                             as avg_outflow_usd_3m_pit,
    s.avg_payments_usd_3m                            as avg_payments_usd_3m_pit,
    s.inflow_volatility_6m / nullif(s.avg_inflow_usd_3m, 0) as inflow_cv_6m_pit,
    s.months_with_inflow_6m                          as months_with_inflow_6m_pit,
    s.nsf_declines_3m                                as nsf_declines_3m_pit,
    s.max_outflow_usd_6m                             as max_outflow_usd_6m_pit,
    s.tx_count_3m                                    as tx_count_3m_pit,
    h.n_products_pit,
    coalesce(h.has_credit_card_pit, false)           as has_credit_card_pit,
    coalesce(h.has_loan_pit, false)                  as has_loan_pit,
    h.oldest_product_age_days_pit,
    date_diff('day', cast(c.registration_date as date), s.snapshot_date) as tenure_days_pit,
    -- current-state attributes (not PIT-safe until SCD2 history exists)
    c.credit_score                                   as credit_score_current,
    c.monthly_income_usd                             as monthly_income_usd_current,
    c.segment                                        as segment_current,
    c.customer_status                                as customer_status_current,
    -- integrity context: tenure is unreliable for half the products (rule R02)
    c.dq_r05_minor_at_registration
from snap s
join {{ ref('int_customer_profile') }} c using (customer_id)
left join holdings h using (customer_id, snapshot_date)
