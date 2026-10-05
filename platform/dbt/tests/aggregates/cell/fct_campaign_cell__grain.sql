-- fct_campaign_cell: one row per (send_channel, promoted_product, campaign_objective, segment, country_code, month_start).
select count(*) as n_rows, count(distinct (send_channel, promoted_product, campaign_objective, segment, country_code, month_start)) as n_keys
from {{ ref('fct_campaign_cell') }}
having count(*) <> count(distinct (send_channel, promoted_product, campaign_objective, segment, country_code, month_start))
