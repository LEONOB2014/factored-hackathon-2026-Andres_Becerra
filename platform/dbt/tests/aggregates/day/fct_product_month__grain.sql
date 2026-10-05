-- fct_product_month: one row per (product_id, month_start).
select count(*) as n_rows, count(distinct (product_id, month_start)) as n_keys
from {{ ref('fct_product_month') }}
having count(*) <> count(distinct (product_id, month_start))
