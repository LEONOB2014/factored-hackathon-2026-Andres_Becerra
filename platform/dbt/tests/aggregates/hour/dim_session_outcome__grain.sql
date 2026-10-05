-- dim_session_outcome: one row per (has_error, has_purchase, has_form).
select count(*) as n_rows, count(distinct (has_error, has_purchase, has_form)) as n_keys
from {{ ref('dim_session_outcome') }}
having count(*) <> count(distinct (has_error, has_purchase, has_form))
