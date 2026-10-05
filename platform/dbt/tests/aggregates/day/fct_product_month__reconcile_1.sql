-- fct_product_month: n_tx per (month_start) equals count(product_id) of its atomic source.
with l as (select month_start, sum(n_tx) as v from {{ ref('fct_product_month') }} group by all),
     r as (select cast(date_trunc('month', transaction_ts_utc) as date) as month_start, count(product_id) as v from {{ ref('int_transactions_enriched') }} group by all)
select coalesce(l.month_start, r.month_start) as month_start, l.v as aggregate_value, r.v as atomic_value
from l full outer join r on l.month_start is not distinct from r.month_start
where coalesce(l.v, 0) <> coalesce(r.v, 0) and abs(coalesce(l.v, 0) - coalesce(r.v, 0)) > 1e-6 * greatest(1, abs(coalesce(r.v, 0)))
