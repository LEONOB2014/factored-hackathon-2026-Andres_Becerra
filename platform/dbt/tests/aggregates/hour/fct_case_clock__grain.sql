-- fct_case_clock: one row per (complaint_id).
select count(*) as n_rows, count(distinct (complaint_id)) as n_keys
from {{ ref('fct_case_clock') }}
having count(*) <> count(distinct (complaint_id))
