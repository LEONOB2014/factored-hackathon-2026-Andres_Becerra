-- Digital session fact (grain: session). IP addresses are tokenized: an IP is personal data under LGPD.
select
    session_id,
    any_value(customer_id)                                   as customer_id,
    min(event_ts_utc)                                        as session_start_utc,
    max(event_ts_utc)                                        as session_end_utc,
    cast(min(event_ts_utc) as date)                          as date_key,
    count(*)                                                 as n_events,
    count(*) filter (where event_type = 'Login')             as n_logins,
    count(*) filter (where event_type = 'Error')             as n_errors,
    count(*) filter (where event_type = 'Purchase')          as n_purchases,
    any_value(channel)                                       as channel,
    any_value(platform)                                      as platform,
    {{ pii_hash('any_value(ip_address)') }}                  as ip_token,
    any_value(ip_country_code)                               as ip_country_code
from {{ ref('stg_digital_events') }}
group by session_id
