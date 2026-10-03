select s.*, cast(s.send_ts_utc as date) as date_key
from {{ ref('stg_campaign_sends') }} s
