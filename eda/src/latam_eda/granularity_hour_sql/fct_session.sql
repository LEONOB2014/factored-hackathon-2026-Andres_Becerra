-- Accumulating fact, one row per digital session (a sub-hour grain: a median session lasts minutes), on the delivery
-- clock (−6 h; the gold fct_digital_session dates a session by its UTC day). Sequence features describe the order of
-- events inside the session: where the first error falls, whether a purchase follows it, and how many event-type
-- changes the session makes.
-- grain: session_id
-- reconcile: n_events = count(*) from {stg_digital_events}
-- reconcile: n_errors = count(*) filter (where event_type = 'Error') from {stg_digital_events}
with e as (
    select session_id, customer_id, event_type, event_ts_utc, duration_seconds,
           row_number() over (partition by session_id order by event_ts_utc, event_id) as k,
           lag(event_type) over (partition by session_id order by event_ts_utc, event_id) as prev_type
    from {stg_digital_events})
select session_id,
       arg_min(customer_id, k) as customer_id,
       min(event_ts_utc) as session_start_utc,
       cast(min(event_ts_utc) - interval 6 hour as date) as delivery_day,
       hour(min(event_ts_utc) - interval 6 hour) as hour_of_day,
       date_diff('second', min(event_ts_utc), max(event_ts_utc)) as session_seconds,
       count(*) as n_events,
       count(*) filter (where event_type = 'Error') as n_errors,
       count(*) filter (where event_type = 'Purchase') as n_purchases,
       count(*) filter (where event_type = 'FormSubmit') as n_forms,
       count(*) filter (where event_type = 'PageView') as n_pageviews,
       count(*) filter (where event_type = 'Click') as n_clicks,
       count(*) filter (where prev_type is not null and prev_type <> event_type) as n_switches,
       min(k) filter (where event_type = 'Error') as first_error_position,
       min(k) filter (where event_type = 'Purchase') as first_purchase_position,
       arg_min(event_type, k) = 'Login' as starts_with_login,
       arg_max(event_type, k) = 'Logout' as ends_with_logout,
       count(*) filter (where event_type = 'Error') > 0 as has_error,
       count(*) filter (where event_type = 'Purchase') > 0 as has_purchase,
       count(*) filter (where event_type = 'FormSubmit') > 0 as has_form
from e group by session_id
