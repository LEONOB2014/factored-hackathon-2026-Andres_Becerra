-- fct_customer_month: one row per (customer_id, month_start).
select count(*) as n_rows, count(distinct (customer_id, month_start)) as n_keys
from {{ ref('fct_customer_month') }}
having count(*) <> count(distinct (customer_id, month_start))
