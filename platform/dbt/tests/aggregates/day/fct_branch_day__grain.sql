-- fct_branch_day: one row per (branch_id, local_date).
select count(*) as n_rows, count(distinct (branch_id, local_date)) as n_keys
from {{ ref('fct_branch_day') }}
having count(*) <> count(distinct (branch_id, local_date))
