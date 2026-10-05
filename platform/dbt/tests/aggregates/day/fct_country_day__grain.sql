-- fct_country_day: one row per (country_code, local_date).
select count(*) as n_rows, count(distinct (country_code, local_date)) as n_keys
from {{ ref('fct_country_day') }}
having count(*) <> count(distinct (country_code, local_date))
