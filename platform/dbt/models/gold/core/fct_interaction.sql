-- Contact-centre interaction fact. The customer's detected accent is a proxy for region/ethnicity and stays
-- in silver (fairness analysis only); the agent's accent and the match flag are operational QA attributes.
select
    i.* exclude (mentioned_product_ids, customer_detected_accent),
    cast(i.interaction_ts_utc as date)                    as date_key,
    i.customer_detected_accent = i.agent_used_accent      as accent_matched,
    len(i.mentioned_product_ids)                          as n_mentioned_products
from {{ ref('stg_call_center_interactions') }} i
