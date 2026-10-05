-- Periodic snapshot, one row per market and hour of the business clock, dense over the data window: the grain of
-- intraday operations (staffing per hour, intraday control charts, the streaming twin of the day KPIs). hour_start is
-- the UTC hour; delivery_day is the day it belongs to (the hour minus the process's window start: −6 h for
-- transactions, digital events and sends, −8 h for contacts and complaints, see country.PROCESS_DAY_OFFSET), and
-- hour_of_day is its position inside the transaction delivery day (0 = 06:00 UTC).
-- grain: country_code, hour_start
-- reconcile: n_tx = count(*) from {int_transactions_enriched}
-- reconcile: contacts = count(*) from {fct_interaction}
-- reconcile: complaints_opened = count(*) from {fct_complaint}
-- reconcile: sends = count(*) from {fct_campaign_send}
-- dense: country_code from {int_customer_profile} x hour_start from {dim_hour}
with off as (select customer_id, country_code from {int_customer_profile}),
tx as (
    select o.country_code, date_trunc('hour', t.transaction_ts_utc) as hour_start, count(*) as n_tx,
           count(*) filter (where t.transaction_status = 'Declined') as n_declined,
           sum(t.amount_usd) filter (where t.is_cash and t.direction = -1 and t.transaction_status = 'Approved') as cash_out_usd
    from {int_transactions_enriched} t join off o using (customer_id) group by all),
cc as (
    select o.country_code, date_trunc('hour', i.interaction_ts_utc) as hour_start, count(*) as contacts,
           count(*) filter (where i.interaction_type in ('Inbound Call', 'Chat')) as inbound_contacts,
           sum(i.duration_seconds) as handle_seconds, sum(i.wait_time_seconds) as wait_seconds
    from {fct_interaction} i join off o using (customer_id) group by all),
dg as (
    select o.country_code, date_trunc('hour', s.session_start_utc) as hour_start, count(*) as sessions,
           sum(s.n_errors) as digital_errors
    from {fct_digital_session} s join off o using (customer_id) group by all),
cp as (
    select o.country_code, date_trunc('hour', c.created_ts_utc) as hour_start, count(*) as complaints_opened
    from {fct_complaint} c join off o using (customer_id) group by all),
cs as (
    select o.country_code, date_trunc('hour', s.send_ts_utc) as hour_start, count(*) as sends
    from {fct_campaign_send} s join off o using (customer_id) group by all),
grid as (select m.country_code, h.hour_start, h.delivery_day, h.hour_of_day, h.delivery_weekday
         from (select distinct country_code from off) m cross join {dim_hour} h)
select g.country_code, g.hour_start,
       g.delivery_day, g.hour_of_day, g.delivery_weekday,
       coalesce(tx.n_tx, 0) as n_tx, coalesce(tx.n_declined, 0) as n_declined, coalesce(tx.cash_out_usd, 0) as cash_out_usd,
       coalesce(cc.contacts, 0) as contacts, coalesce(cc.inbound_contacts, 0) as inbound_contacts,
       coalesce(cc.handle_seconds, 0) as handle_seconds, coalesce(cc.wait_seconds, 0) as wait_seconds,
       coalesce(dg.sessions, 0) as sessions, coalesce(dg.digital_errors, 0) as digital_errors,
       coalesce(cp.complaints_opened, 0) as complaints_opened, coalesce(cs.sends, 0) as sends
from grid g
left join tx using (country_code, hour_start)
left join cc using (country_code, hour_start)
left join dg using (country_code, hour_start)
left join cp using (country_code, hour_start)
left join cs using (country_code, hour_start)
