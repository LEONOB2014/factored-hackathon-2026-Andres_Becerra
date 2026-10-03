{% macro stg_digital_events_select(src) %}
select
    e.event_id,
    e.event_date                                   as event_ts_utc,
    e.process_date,
    e.customer_id,                                 -- 24 % null (anonymous sessions, rule R20)
    e.session_id,
    e.event_type,
    e.event_category,
    e.channel,
    e.platform,
    e.browser,
    e.app_version,
    e.page_url,
    e.action,
    e.product_id,
    e.event_value,
    cast(e.duration_seconds as integer)            as duration_seconds,
    e.ip_address,
    cc.iso2                                        as ip_country_code,
    e.ip_city,
    e.is_mobile,
    e.utm_source,
    e.utm_medium,
    e.utm_campaign
from {{ src }} e
left join {{ ref('country_codes') }} cc on cc.raw_name = e.ip_country
{% endmacro %}
