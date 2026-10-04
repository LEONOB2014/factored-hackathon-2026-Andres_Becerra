-- Digital session fact (grain: session). IP addresses are tokenized: an IP is personal data under LGPD.
select
    session_id,
    arg_min(customer_id, (event_ts_utc, event_id))          as customer_id,
    min(event_ts_utc)                                        as session_start_utc,
    max(event_ts_utc)                                        as session_end_utc,
    cast(min(event_ts_utc) as date)                          as date_key,
    count(*)                                                 as n_events,
    count(*) filter (where event_type = 'Login')             as n_logins,
    count(*) filter (where event_type = 'Error')             as n_errors,
    count(*) filter (where event_type = 'Purchase')          as n_purchases,
    arg_min(channel, (event_ts_utc, event_id))              as channel,
    arg_min(platform, (event_ts_utc, event_id))             as platform,
    {{ pii_hash('arg_min(ip_address, (event_ts_utc, event_id))') }} as ip_token,
    arg_min(ip_country_code, (event_ts_utc, event_id))      as ip_country_code
from {{ ref('stg_digital_events') }}
group by session_id
