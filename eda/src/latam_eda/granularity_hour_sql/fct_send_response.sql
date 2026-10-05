-- Accumulating fact, one row per campaign send, with the response milestones (open, click, conversion) as elapsed
-- hours from the send, and the hour and weekday of the send and of the open on the delivery clock (−6 h): the grain
-- of send-time optimisation (does the hour of the send change whether, or how fast, a customer responds).
-- grain: send_id
-- reconcile: n_sends = count(*) from {fct_campaign_send}
-- reconcile: opened = count(*) filter (where was_opened) from {fct_campaign_send}
select s.send_id, s.customer_id, s.campaign_id, s.send_channel,
       hour(s.send_ts_utc - interval 6 hour) as send_hour_of_day,
       isodow(s.send_ts_utc - interval 6 hour) as send_weekday,
       hour(s.open_ts_utc - interval 6 hour) as open_hour_of_day,
       s.was_delivered, s.was_opened is not null as open_tracked,
       coalesce(s.was_opened, false)::int as opened,
       coalesce(s.was_clicked, false)::int as clicked,
       coalesce(s.had_conversion, false)::int as converted,
       date_diff('minute', s.send_ts_utc, s.open_ts_utc) / 60.0 as hours_to_open,
       date_diff('minute', s.send_ts_utc, s.click_ts_utc) / 60.0 as hours_to_click,
       date_diff('minute', s.send_ts_utc, s.conversion_ts_utc) / 60.0 as hours_to_convert,
       1 as n_sends
from {fct_campaign_send} s
