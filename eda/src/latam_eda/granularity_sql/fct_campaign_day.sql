-- Periodic snapshot, one row per campaign and send day (UTC): the grain at which marketing paces a campaign and
-- reads its funnel (sent, delivered, opened, clicked, converted) and its economics (cost against conversion value).
-- days_since_start places each day on the campaign's own timeline.
-- grain: campaign_id, send_date
-- reconcile: sends = count(*) from {fct_campaign_send} | send_date = cast(send_ts_utc as date)
-- reconcile: conversions = count(*) filter (where had_conversion) from {fct_campaign_send}
select s.campaign_id, cast(s.send_ts_utc as date) as send_date,
       date_diff('day', any_value(c.start_date), cast(s.send_ts_utc as date)) as days_since_start,
       any_value(c.campaign_type) as campaign_type, any_value(c.campaign_objective) as campaign_objective,
       any_value(c.promoted_product) as promoted_product, any_value(c.target_country) as target_country,
       count(*) as sends, count(*) filter (where s.was_delivered) as delivered,
       count(*) filter (where s.was_opened) as opened, count(*) filter (where s.was_clicked) as clicked,
       count(*) filter (where s.had_conversion) as conversions,
       sum(coalesce(s.conversion_value, 0)) as conversion_value, sum(coalesce(s.send_cost, 0)) as send_cost,
       count(distinct s.customer_id) as customers_reached
from {fct_campaign_send} s left join {dim_campaign} c using (campaign_id)
group by s.campaign_id, cast(s.send_ts_utc as date)
