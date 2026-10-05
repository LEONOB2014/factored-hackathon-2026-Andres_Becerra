-- dim_month: one row per (month_start).
select count(*) as n_rows, count(distinct (month_start)) as n_keys
from {{ ref('dim_month') }}
having count(*) <> count(distinct (month_start))
