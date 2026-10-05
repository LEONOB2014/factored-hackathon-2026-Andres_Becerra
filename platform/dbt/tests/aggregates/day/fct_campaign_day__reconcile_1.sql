-- fct_campaign_day: sends per (send_date) equals count(*) of its atomic source.
with l as (select send_date, sum(sends) as v from {{ ref('fct_campaign_day') }} group by all),
     r as (select cast(send_ts_utc as date) as send_date, count(*) as v from {{ ref('fct_campaign_send') }} group by all)
select coalesce(l.send_date, r.send_date) as send_date, l.v as aggregate_value, r.v as atomic_value
from l full outer join r on l.send_date is not distinct from r.send_date
where coalesce(l.v, 0) <> coalesce(r.v, 0) and abs(coalesce(l.v, 0) - coalesce(r.v, 0)) > 1e-6 * greatest(1, abs(coalesce(r.v, 0)))
