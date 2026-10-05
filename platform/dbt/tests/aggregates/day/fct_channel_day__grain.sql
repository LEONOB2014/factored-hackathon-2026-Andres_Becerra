-- fct_channel_day: one row per (country_code, channel, local_date).
select count(*) as n_rows, count(distinct (country_code, channel, local_date)) as n_keys
from {{ ref('fct_channel_day') }}
having count(*) <> count(distinct (country_code, channel, local_date))
