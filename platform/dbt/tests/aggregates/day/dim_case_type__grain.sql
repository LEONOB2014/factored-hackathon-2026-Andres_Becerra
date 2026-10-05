-- dim_case_type: one row per (case_type_key).
select count(*) as n_rows, count(distinct (case_type_key)) as n_keys
from {{ ref('dim_case_type') }}
having count(*) <> count(distinct (case_type_key))
