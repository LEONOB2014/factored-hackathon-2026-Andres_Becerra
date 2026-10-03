-- Dense customer x month grid of transaction aggregates (months without activity are zero rows, which
-- rolling windows need). Shared by the credit, AML and collections marts.
with months as (
    select cast(m as date) as month_start
    from range(date_trunc('month', (select min(transaction_ts_utc) from {{ ref('int_transactions_enriched') }})),
               date_trunc('month', {{ as_of() }}) + interval 1 month, interval 1 month) r(m)
),
grid as (
    select c.customer_id, m.month_start
    from {{ ref('int_customer_profile') }} c cross join months m
),
agg as (
    select
        customer_id,
        cast(date_trunc('month', transaction_ts_utc) as date)                                      as month_start,
        count(*)                                                                                   as n_tx,
        sum(amount_usd) filter (where direction = 1 and transaction_status = 'Approved')           as inflow_usd,
        sum(amount_usd) filter (where direction = -1 and transaction_status = 'Approved')          as outflow_usd,
        sum(amount_usd) filter (where transaction_type = 'Payment' and transaction_status = 'Approved') as payments_usd,
        sum(amount_usd) filter (where is_cash and direction = 1 and transaction_status = 'Approved')  as cash_in_usd,
        sum(amount_usd) filter (where is_cash and direction = -1 and transaction_status = 'Approved') as cash_out_usd,
        sum(amount_usd) filter (where is_cross_border and transaction_status = 'Approved')         as cross_border_usd,
        count(distinct transaction_country_code) filter (where is_cross_border)                    as n_foreign_countries,
        count(*) filter (where response_code = '51')                                               as insufficient_funds_declines,
        count(*) filter (where amount_usd >= 9000 and amount_usd < 10000)                          as near_threshold_tx,
        count(*) filter (where amount = round(amount, -2) and amount >= 1000)                      as round_amount_tx,
        max(amount_usd) filter (where direction = -1)                                              as max_outflow_usd
    from {{ ref('int_transactions_enriched') }}
    group by all
)
select
    g.customer_id,
    g.month_start,
    coalesce(a.n_tx, 0)                         as n_tx,
    coalesce(a.inflow_usd, 0)                   as inflow_usd,
    coalesce(a.outflow_usd, 0)                  as outflow_usd,
    coalesce(a.payments_usd, 0)                 as payments_usd,
    coalesce(a.cash_in_usd, 0)                  as cash_in_usd,
    coalesce(a.cash_out_usd, 0)                 as cash_out_usd,
    coalesce(a.cross_border_usd, 0)             as cross_border_usd,
    coalesce(a.n_foreign_countries, 0)          as n_foreign_countries,
    coalesce(a.insufficient_funds_declines, 0)  as insufficient_funds_declines,
    coalesce(a.near_threshold_tx, 0)            as near_threshold_tx,
    coalesce(a.round_amount_tx, 0)              as round_amount_tx,
    a.max_outflow_usd
from grid g
left join agg a using (customer_id, month_start)
