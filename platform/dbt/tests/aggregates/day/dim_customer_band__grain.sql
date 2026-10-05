-- dim_customer_band: one row per (band_key).
select count(*) as n_rows, count(distinct (band_key)) as n_keys
from {{ ref('dim_customer_band') }}
having count(*) <> count(distinct (band_key))
