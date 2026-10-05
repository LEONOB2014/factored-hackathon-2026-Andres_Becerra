-- fct_session: one row per (session_id).
select count(*) as n_rows, count(distinct (session_id)) as n_keys
from {{ ref('fct_session') }}
having count(*) <> count(distinct (session_id))
