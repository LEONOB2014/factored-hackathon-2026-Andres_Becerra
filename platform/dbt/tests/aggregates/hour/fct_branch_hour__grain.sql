-- fct_branch_hour: one row per (branch_id, hour_start).
select count(*) as n_rows, count(distinct (branch_id, hour_start)) as n_keys
from {{ ref('fct_branch_hour') }}
having count(*) <> count(distinct (branch_id, hour_start))
