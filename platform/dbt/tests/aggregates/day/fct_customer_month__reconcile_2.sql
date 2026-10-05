-- fct_customer_month: outflow_usd per (month_start) equals sum(outflow_usd) of its atomic source.
with l as (select month_start, sum(outflow_usd) as v from {{ ref('fct_customer_month') }} group by all),
     r as (select month_start as month_start, sum(outflow_usd) as v from {{ ref('int_customer_month_tx') }} group by all)
select coalesce(l.month_start, r.month_start) as month_start, l.v as aggregate_value, r.v as atomic_value
from l full outer join r on l.month_start is not distinct from r.month_start
where coalesce(l.v, 0) <> coalesce(r.v, 0) and abs(coalesce(l.v, 0) - coalesce(r.v, 0)) > 1e-6 * greatest(1, abs(coalesce(r.v, 0)))
