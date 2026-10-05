-- dim_agent_shift: one row per (work_shift, hour_of_day).
select count(*) as n_rows, count(distinct (work_shift, hour_of_day)) as n_keys
from {{ ref('dim_agent_shift') }}
having count(*) <> count(distinct (work_shift, hour_of_day))
