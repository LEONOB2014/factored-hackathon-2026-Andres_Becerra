-- Periodic snapshot, one row per campaign decision cell and month: the grain at which marketing allocates budget.
-- A cell is (send channel, promoted product, campaign objective, customer segment, market): what is sent, why, to whom
-- and where. Additive measures only: the cell's conversion rate, value per conversion and cost per send are derived as
-- ratios of these sums. The delivery month is the send's process_date month (the business day). open_tracked counts the
-- delivered sends whose channel records opens (Voice and WhatsApp record none, so their conversions cannot be attributed).
-- grain: send_channel, promoted_product, campaign_objective, segment, country_code, month_start
-- reconcile: sends = count(*) from {fct_campaign_send} | month_start = cast(date_trunc('month', process_date) as date)
-- reconcile: conversions = count(*) filter (where had_conversion) from {fct_campaign_send}
-- reconcile: opened = count(*) filter (where was_opened) from {fct_campaign_send}
-- reconcile: send_cost = sum(coalesce(send_cost, 0)) from {fct_campaign_send}
select s.send_channel, coalesce(k.promoted_product, '(unknown)') as promoted_product,
       coalesce(k.campaign_objective, '(unknown)') as campaign_objective, c.segment, c.country_code,
       cast(date_trunc('month', s.process_date) as date) as month_start,
       count(*) as sends,
       count(*) filter (where s.was_delivered) as delivered,
       count(*) filter (where s.was_delivered and s.was_opened is not null) as open_tracked,
       count(*) filter (where s.was_opened) as opened,
       count(*) filter (where s.was_clicked) as clicked,
       count(*) filter (where s.had_conversion) as conversions,
       sum(coalesce(s.conversion_value, 0)) as conversion_value,
       sum(coalesce(s.send_cost, 0)) as send_cost,
       count(distinct s.campaign_id) as campaigns
from {fct_campaign_send} s
left join {dim_campaign} k using (campaign_id)
join {int_customer_profile} c using (customer_id)
group by all
