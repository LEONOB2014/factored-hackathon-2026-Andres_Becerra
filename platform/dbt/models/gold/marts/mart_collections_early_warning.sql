-- Collections early warning: one row per credit product (loans, credit cards) with delinquency state,
-- repayment trend, cash-flow stress and contact signals. Delinquency is current-state only (no DPD
-- history in the source); roll-rate models need the SCD2 snapshot of days_past_due to accumulate.
with pay as (
    select
        product_id,
        sum(amount_usd) filter (where transaction_type = 'Payment' and transaction_status = 'Approved'
                                  and transaction_ts_utc >= {{ as_of() }} - interval 30 day)              as payments_usd_30d,
        sum(amount_usd) filter (where transaction_type = 'Payment' and transaction_status = 'Approved'
                                  and transaction_ts_utc >= {{ as_of() }} - interval 90 day
                                  and transaction_ts_utc <  {{ as_of() }} - interval 30 day) / 2.0        as payments_usd_prev_monthly_avg,
        max(transaction_ts_utc) filter (where transaction_type = 'Payment' and transaction_status = 'Approved') as last_payment_ts
    from {{ ref('fct_transaction') }}
    where product_family in ('loan', 'credit_card')
    group by 1
),
cust as (
    select customer_id,
           sum(inflow_usd)  filter (where month_start >= date_trunc('month', {{ as_of() }}) - interval 3 month) / 3.0 as avg_inflow_usd_3m,
           sum(insufficient_funds_declines) filter (where month_start >= date_trunc('month', {{ as_of() }}) - interval 3 month)
                                                                                                     as nsf_declines_3m
    from {{ ref('int_customer_month_tx') }}
    group by 1
)
select
    p.product_id,
    p.customer_id,
    c.country_code,
    c.segment,
    p.product_type,
    p.product_status,
    p.balance_usd,
    p.credit_limit_usd,
    p.utilization,
    p.interest_rate,
    p.days_past_due,
    p.dpd_bucket,
    y.last_payment_ts,
    date_diff('day', cast(y.last_payment_ts as date), {{ as_of() }})     as days_since_last_payment,
    coalesce(y.payments_usd_30d, 0)                                       as payments_usd_30d,
    y.payments_usd_prev_monthly_avg,
    coalesce(y.payments_usd_30d, 0) / nullif(y.payments_usd_prev_monthly_avg, 0) as payment_trend_ratio,
    k.avg_inflow_usd_3m,
    k.nsf_declines_3m,
    h.contacts_90d,
    h.negative_sentiment_share_365d,
    h.logins_90d,
    h.open_cases,
    -- transparent early-warning score (0-100); a learned model replaces it once DPD history exists.
    -- Every term is null-safe: LEAST() ignores NULLs, so one null term would otherwise yield 100.
    least(100,
          25 * coalesce(p.days_past_due between 1 and 30, false)::int
        + 40 * coalesce(p.days_past_due > 30, false)::int
        + 15 * coalesce(p.utilization >= 0.9, false)::int
        + 10 * coalesce(k.nsf_declines_3m >= 2, false)::int
        + 10 * coalesce(coalesce(y.payments_usd_30d, 0) / nullif(y.payments_usd_prev_monthly_avg, 0) < 0.5, false)::int
        + 10 * coalesce(date_diff('day', cast(y.last_payment_ts as date), {{ as_of() }}) > 45, true)::int
    )                                                                     as early_warning_score
from {{ ref('int_products_enriched') }} p
join {{ ref('int_customer_profile') }} c using (customer_id)
left join pay y using (product_id)
left join cust k using (customer_id)
left join {{ ref('mart_customer_360') }} h using (customer_id)
where p.product_family in ('loan', 'credit_card')
