-- fct_send_response: one row per (send_id).
select count(*) as n_rows, count(distinct (send_id)) as n_keys
from {{ ref('fct_send_response') }}
having count(*) <> count(distinct (send_id))
