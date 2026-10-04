-- Accumulating snapshot, one row per customer: the whole relationship summarised as of the last full month. It is
-- the grain of lifetime value, recency-frequency-monetary (RFM) scoring and customer-level survival. Recency is
-- measured against the last full month (the data stops on the 17th of May 2026), so a customer seen only in the
-- partial month is not mistaken for a recent one.
-- grain: customer_id
-- reconcile: lifetime_tx = count(*) from {int_transactions_enriched}
-- reconcile: lifetime_contacts = count(*) from {fct_interaction}
with m as (select max(month_start) filter (where not is_partial) as last_full from {dim_month}),
a as (
    select f.customer_id,
           min(f.month_start) filter (where f.n_tx > 0)                                    as first_active_month,
           max(f.month_start) filter (where f.n_tx > 0 and f.month_start <= m.last_full)    as last_active_month,
           count(*) filter (where f.n_tx > 0 and f.month_start <= m.last_full)              as active_months,
           sum(f.n_tx)                                                                      as lifetime_tx,
           sum(f.outflow_usd)                                                               as lifetime_outflow_usd,
           sum(f.inflow_usd)                                                                as lifetime_inflow_usd,
           sum(f.contacts)                                                                  as lifetime_contacts,
           sum(f.complaints_opened)                                                         as lifetime_complaints,
           sum(f.conversions)                                                               as lifetime_conversions,
           sum(f.sessions)                                                                  as lifetime_sessions,
           max(f.products_held)                                                             as max_products_held,
           any_value(m.last_full)                                                           as as_of_month
    from {fct_customer_month} f cross join m
    group by f.customer_id)
select
    a.*,
    c.country_code, c.segment, c.registration_date, c.tenure_days, c.age_years, c.credit_score, c.monthly_income_usd,
    date_diff('month', a.last_active_month, a.as_of_month)                                 as recency_months,
    a.lifetime_tx / nullif(a.active_months, 0)                                              as tx_per_active_month,
    a.lifetime_outflow_usd / nullif(a.active_months, 0)                                     as outflow_per_active_month,
    a.lifetime_inflow_usd - a.lifetime_outflow_usd                                          as lifetime_net_flow_usd
from a join {int_customer_profile} c using (customer_id)
