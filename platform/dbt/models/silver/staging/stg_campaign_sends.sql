select
    send_id,
    send_date                                      as send_ts_utc,
    process_date,
    campaign_id,
    customer_id,
    send_channel,
    template_used,
    send_status,
    was_delivered,
    was_opened,
    open_date                                      as open_ts_utc,
    was_clicked,
    click_date                                     as click_ts_utc,
    cast(click_count as integer)                   as click_count,
    had_conversion,
    conversion_date                                as conversion_ts_utc,
    conversion_value,
    open_device,
    failure_reason,
    send_cost
from {{ ref('typed_campaign_sends') }} src
where {{ not_held('src', 'campaign_sends') }}
