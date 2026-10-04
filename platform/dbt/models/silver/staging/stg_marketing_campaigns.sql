select
    campaign_id, campaign_name, campaign_type, campaign_objective, promoted_product, target_segment,
    target_country, start_date, end_date, budget, campaign_status, expected_conversion_rate
from {{ ref('typed_marketing_campaigns') }} src
where {{ not_held('src', 'marketing_campaigns') }}
