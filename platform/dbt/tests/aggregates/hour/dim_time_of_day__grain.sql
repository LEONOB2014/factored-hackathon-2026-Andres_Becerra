-- dim_time_of_day: one row per (hour_of_day).
select count(*) as n_rows, count(distinct (hour_of_day)) as n_keys
from {{ ref('dim_time_of_day') }}
having count(*) <> count(distinct (hour_of_day))
