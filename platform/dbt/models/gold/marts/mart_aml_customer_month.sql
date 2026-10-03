-- AML / transaction monitoring: one row per customer-month with typology indicators and peer-group
-- deviations (segment x country). Limitation: transfers carry no counterparty, so network typologies
-- (fan-in/fan-out, mule chains) cannot be computed from this source; see report ch. 07.
with base as (
    select
        m.*,
        c.segment,
        c.country_code,
        c.monthly_income_usd,
        least(m.inflow_usd, m.outflow_usd) / nullif(greatest(m.inflow_usd, m.outflow_usd), 0) as pass_through_ratio,
        m.cross_border_usd / nullif(m.inflow_usd + m.outflow_usd, 0)                       as cross_border_share,
        (m.cash_in_usd + m.cash_out_usd) / nullif(m.inflow_usd + m.outflow_usd, 0)          as cash_share,
        m.inflow_usd / nullif(c.monthly_income_usd, 0)                                      as inflow_to_declared_income
    from {{ ref('int_customer_month_tx') }} m
    join {{ ref('int_customer_profile') }} c using (customer_id)
    where m.n_tx > 0
),
peer as (   -- robust peer statistics (median / MAD) per segment, country and month
    select segment, country_code, month_start,
           quantile_cont(inflow_usd, 0.5)  as med_in,
           mad(inflow_usd)                 as mad_in,
           quantile_cont(outflow_usd, 0.5) as med_out,
           mad(outflow_usd)                as mad_out
    from base
    group by all
)
select
    b.customer_id,
    b.month_start,
    b.segment,
    b.country_code,
    b.n_tx,
    b.inflow_usd,
    b.outflow_usd,
    b.cash_in_usd,
    b.cash_out_usd,
    b.cross_border_usd,
    b.n_foreign_countries,
    b.pass_through_ratio,
    b.cross_border_share,
    b.cash_share,
    b.inflow_to_declared_income,
    b.near_threshold_tx,
    b.round_amount_tx,
    (b.inflow_usd  - p.med_in)  / nullif(1.4826 * p.mad_in, 0)  as inflow_robust_z_vs_peers,
    (b.outflow_usd - p.med_out) / nullif(1.4826 * p.mad_out, 0) as outflow_robust_z_vs_peers,
    list_filter(list_value(
        case when b.pass_through_ratio >= 0.9 and b.inflow_usd >= 10000          then 'RAPID_IN_OUT' end,
        case when b.inflow_to_declared_income >= 5                              then 'INFLOW_INCONSISTENT_WITH_INCOME' end,
        case when b.near_threshold_tx >= 2                                      then 'NEAR_THRESHOLD_STRUCTURING' end,
        case when b.n_foreign_countries >= 3                                    then 'MULTI_JURISDICTION' end,
        case when b.cash_share >= 0.8 and b.inflow_usd + b.outflow_usd >= 10000 then 'CASH_INTENSIVE' end,
        case when (b.inflow_usd - p.med_in) / nullif(1.4826 * p.mad_in, 0) >= 6 then 'PEER_OUTLIER_INFLOW' end
    ), x -> x is not null)                                      as typology_hits
from base b
join peer p using (segment, country_code, month_start)
