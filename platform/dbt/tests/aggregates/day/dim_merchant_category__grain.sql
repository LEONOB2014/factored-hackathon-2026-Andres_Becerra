-- dim_merchant_category: one row per (category).
select count(*) as n_rows, count(distinct (category)) as n_keys
from {{ ref('dim_merchant_category') }}
having count(*) <> count(distinct (category))
