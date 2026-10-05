-- fct_channel_hour: one row per (country_code, channel, hour_start).
select count(*) as n_rows, count(distinct (country_code, channel, hour_start)) as n_keys
from {{ ref('fct_channel_hour') }}
having count(*) <> count(distinct (country_code, channel, hour_start))
