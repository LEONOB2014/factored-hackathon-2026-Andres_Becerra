-- fct_customer_daypart: one row per (customer_id, daypart).
select count(*) as n_rows, count(distinct (customer_id, daypart)) as n_keys
from {{ ref('fct_customer_daypart') }}
having count(*) <> count(distinct (customer_id, daypart))
