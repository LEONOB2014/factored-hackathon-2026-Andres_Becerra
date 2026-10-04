select
    interaction_id,
    interaction_date                               as interaction_ts_utc,
    process_date,
    customer_id,
    agent_id,
    -- The backup re-labelled this field in Spanish; normalize both vocabularies to one.
    case interaction_type
        when 'Llamada Entrante' then 'Inbound Call'
        when 'Llamada Saliente' then 'Outbound Call'
        else interaction_type
    end                                            as interaction_type,
    channel,
    contact_reason,
    reason_category,
    cast(duration_seconds as integer)              as duration_seconds,
    cast(wait_time_seconds as integer)             as wait_time_seconds,
    was_resolved,
    requires_followup,
    detected_sentiment,
    sentiment_score,
    customer_detected_accent,
    agent_used_accent,
    was_escalated,
    -- comma-separated product ids -> list (undeclared FK, see docs/erd.md)
    case when mentioned_products is not null then string_split(mentioned_products, ',') end
                                                   as mentioned_product_ids,
    has_transcript,
    has_recording
from {{ ref('typed_call_center_interactions') }} src
where {{ not_held('src', 'call_center_interactions') }}
