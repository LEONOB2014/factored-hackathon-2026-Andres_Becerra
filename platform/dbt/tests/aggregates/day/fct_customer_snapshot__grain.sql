-- fct_customer_snapshot: one row per (customer_id).
select count(*) as n_rows, count(distinct (customer_id)) as n_keys
from {{ ref('fct_customer_snapshot') }}
having count(*) <> count(distinct (customer_id))
