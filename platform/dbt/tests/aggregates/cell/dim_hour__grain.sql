-- dim_hour: one row per (hour_start).
select count(*) as n_rows, count(distinct (hour_start)) as n_keys
from {{ ref('dim_hour') }}
having count(*) <> count(distinct (hour_start))
