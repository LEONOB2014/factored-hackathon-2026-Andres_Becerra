-- fct_campaign_day: one row per (campaign_id, send_date).
select count(*) as n_rows, count(distinct (campaign_id, send_date)) as n_keys
from {{ ref('fct_campaign_day') }}
having count(*) <> count(distinct (campaign_id, send_date))
