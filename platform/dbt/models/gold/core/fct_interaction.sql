select i.* exclude (mentioned_product_ids), cast(i.interaction_ts_utc as date) as date_key,
       len(i.mentioned_product_ids) as n_mentioned_products
from {{ ref('stg_call_center_interactions') }} i
