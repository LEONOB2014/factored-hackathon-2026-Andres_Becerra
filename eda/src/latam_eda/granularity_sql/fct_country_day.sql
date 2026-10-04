-- Periodic snapshot, one row per bank market and local day, dense: the operational day of each country across every
-- process. Each event is placed on its delivery day (`process_date`, the day the source's weekly rhythm was drawn on;
-- country.PROCESS_DAY_OFFSET); digital sessions, which carry none, on their start minus 6 hours (seed_clock), which
-- equals the delivery day of 99.8 % of digital events. Joins dim_country_day for that day's calendar. Anonymous digital
-- sessions have no customer and are placed by IP country (reported separately: anonymous_sessions).
-- grain: country_code, local_date
-- reconcile: n_tx = count(*) from {int_transactions_enriched}
-- reconcile: contacts = count(*) from {fct_interaction}
-- reconcile: complaints_opened = count(*) from {fct_complaint}
-- reconcile: sends = count(*) from {fct_campaign_send}
-- dense: country_code from {dim_data_day} x local_date from {dim_data_day}
with off as (select c.customer_id, c.country_code, k.utc_offset_hours from {int_customer_profile} c cross join {seed_clock} k),
days as (select country_code, local_date from {dim_data_day}),
tx as (
    select o.country_code, t.process_date as local_date,
           count(*) as n_tx, sum(t.amount_usd) filter (where t.direction = -1 and t.transaction_status = 'Approved') as outflow_usd,
           sum(t.amount_usd) filter (where t.direction = 1 and t.transaction_status = 'Approved') as inflow_usd,
           count(*) filter (where t.transaction_status = 'Declined') as n_declined,
           count(*) filter (where t.is_fraud) as n_flagged_fraud,
           sum(t.amount_usd) filter (where t.is_cash and t.direction = -1 and t.transaction_status = 'Approved') as cash_out_usd
    from {int_transactions_enriched} t join off o using (customer_id) group by all),
dg as (
    select o.country_code, cast(s.session_start_utc + to_hours(o.utc_offset_hours) as date) as local_date,
           count(*) as sessions, sum(s.n_errors) as digital_errors, count(*) filter (where s.n_errors > 0) as sessions_with_error
    from {fct_digital_session} s join off o using (customer_id) group by all),
an as (
    select ip_country_code as country_code, cast(session_start_utc + to_hours(k.utc_offset_hours) as date) as local_date,
           count(*) as anonymous_sessions
    from {fct_digital_session} cross join {seed_clock} k where customer_id is null group by all),
cc as (
    select o.country_code, i.process_date as local_date,
           count(*) as contacts, count(*) filter (where i.was_escalated) as escalations,
           count(*) filter (where not i.was_resolved) as unresolved_contacts,
           sum(i.duration_seconds) as handle_seconds, sum(i.wait_time_seconds) as wait_seconds
    from {fct_interaction} i join off o using (customer_id) group by all),
cp as (
    select o.country_code, c.process_date as local_date,
           count(*) as complaints_opened, count(*) filter (where c.sla_breached) as complaints_sla_breached
    from {fct_complaint} c join off o using (customer_id) group by all),
cs as (
    select o.country_code, s.process_date as local_date,
           count(*) as sends, count(*) filter (where s.had_conversion) as conversions
    from {fct_campaign_send} s join off o using (customer_id) group by all)
select
    d.country_code, d.local_date,
    coalesce(tx.n_tx, 0) as n_tx, coalesce(tx.outflow_usd, 0) as outflow_usd, coalesce(tx.inflow_usd, 0) as inflow_usd,
    coalesce(tx.n_declined, 0) as n_declined, coalesce(tx.n_flagged_fraud, 0) as n_flagged_fraud,
    coalesce(tx.cash_out_usd, 0) as cash_out_usd,
    coalesce(dg.sessions, 0) as sessions, coalesce(dg.digital_errors, 0) as digital_errors,
    coalesce(dg.sessions_with_error, 0) as sessions_with_error, coalesce(an.anonymous_sessions, 0) as anonymous_sessions,
    coalesce(cc.contacts, 0) as contacts, coalesce(cc.escalations, 0) as escalations,
    coalesce(cc.unresolved_contacts, 0) as unresolved_contacts, coalesce(cc.handle_seconds, 0) as handle_seconds,
    coalesce(cc.wait_seconds, 0) as wait_seconds,
    coalesce(cp.complaints_opened, 0) as complaints_opened, coalesce(cp.complaints_sla_breached, 0) as complaints_sla_breached,
    coalesce(cs.sends, 0) as sends, coalesce(cs.conversions, 0) as conversions
from days d
left join tx using (country_code, local_date)
left join dg using (country_code, local_date)
left join an using (country_code, local_date)
left join cc using (country_code, local_date)
left join cp using (country_code, local_date)
left join cs using (country_code, local_date)
