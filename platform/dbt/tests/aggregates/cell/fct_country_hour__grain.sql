-- fct_country_hour: one row per (country_code, hour_start).
select count(*) as n_rows, count(distinct (country_code, hour_start)) as n_keys
from {{ ref('fct_country_hour') }}
having count(*) <> count(distinct (country_code, hour_start))
