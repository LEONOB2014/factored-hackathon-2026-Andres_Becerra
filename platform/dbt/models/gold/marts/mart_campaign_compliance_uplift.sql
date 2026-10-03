-- Marketing: one row per campaign send with consent compliance, contact pressure and uplift-ready
-- treatment/outcome columns. `accepts_marketing` is the CURRENT flag: without consent history (SCD2) we
-- cannot prove consent at send time, which is itself a compliance gap (report ch. 02 and 04).
select
    s.send_id,
    s.campaign_id,
    s.customer_id,
    s.send_ts_utc,
    s.send_channel,
    k.campaign_objective,
    k.promoted_product,
    k.target_segment,
    c.segment,
    c.country_code,
    c.accepts_marketing                                        as accepts_marketing_current,
    not c.accepts_marketing                                    as sent_without_current_consent,
    -- contact pressure: sends to the same customer in the previous 7 / 30 days
    count(*) over (partition by s.customer_id order by s.send_ts_utc
                   range between interval 7 day preceding and current row exclude current row)  as prior_sends_7d,
    count(*) over (partition by s.customer_id order by s.send_ts_utc
                   range between interval 30 day preceding and current row exclude current row) as prior_sends_30d,
    s.send_status,
    s.was_delivered                                            as treatment_delivered,
    s.was_opened,
    s.was_clicked,
    s.had_conversion                                           as outcome_converted,
    date_diff('hour', s.send_ts_utc, s.conversion_ts_utc)      as hours_to_conversion,
    s.conversion_value,
    s.send_cost,
    -- product already held before the send (conversion would be impossible / mis-attributed)
    exists (select 1 from {{ ref('stg_products') }} p
            where p.customer_id = s.customer_id and p.product_type = k.promoted_product
              and p.opening_date <= cast(s.send_ts_utc as date)) as already_held_promoted_product
from {{ ref('stg_campaign_sends') }} s
join {{ ref('stg_marketing_campaigns') }} k using (campaign_id)
join {{ ref('int_customer_profile') }} c using (customer_id)
