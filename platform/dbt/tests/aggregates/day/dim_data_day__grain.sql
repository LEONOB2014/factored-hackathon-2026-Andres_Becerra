-- dim_data_day: one row per (country_code, local_date).
select count(*) as n_rows, count(distinct (country_code, local_date)) as n_keys
from {{ ref('dim_data_day') }}
having count(*) <> count(distinct (country_code, local_date))
