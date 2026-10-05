-- fct_category_month: one row per (category, country_code, month_start).
select count(*) as n_rows, count(distinct (category, country_code, month_start)) as n_keys
from {{ ref('fct_category_month') }}
having count(*) <> count(distinct (category, country_code, month_start))
