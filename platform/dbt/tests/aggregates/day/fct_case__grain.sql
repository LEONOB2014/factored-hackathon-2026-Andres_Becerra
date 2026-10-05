-- fct_case: one row per (complaint_id).
select count(*) as n_rows, count(distinct (complaint_id)) as n_keys
from {{ ref('fct_case') }}
having count(*) <> count(distinct (complaint_id))
