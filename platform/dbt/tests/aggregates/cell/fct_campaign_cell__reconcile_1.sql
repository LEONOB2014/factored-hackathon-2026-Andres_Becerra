-- fct_campaign_cell: sends per (month_start) equals count(*) of its atomic source.
with l as (select month_start, sum(sends) as v from {{ ref('fct_campaign_cell') }} group by all),
     r as (select cast(date_trunc('month', process_date) as date) as month_start, count(*) as v from {{ ref('fct_campaign_send') }} group by all)
select coalesce(l.month_start, r.month_start) as month_start, l.v as aggregate_value, r.v as atomic_value
from l full outer join r on l.month_start is not distinct from r.month_start
where coalesce(l.v, 0) <> coalesce(r.v, 0) and abs(coalesce(l.v, 0) - coalesce(r.v, 0)) > 1e-6 * greatest(1, abs(coalesce(r.v, 0)))
