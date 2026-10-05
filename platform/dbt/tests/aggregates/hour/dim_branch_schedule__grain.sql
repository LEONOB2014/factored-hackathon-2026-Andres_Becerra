-- dim_branch_schedule: one row per (branch_id, iso_weekday, hour_of_day).
select count(*) as n_rows, count(distinct (branch_id, iso_weekday, hour_of_day)) as n_keys
from {{ ref('dim_branch_schedule') }}
having count(*) <> count(distinct (branch_id, iso_weekday, hour_of_day))
