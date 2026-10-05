-- Periodic snapshot, one row per customer and daypart (not customer × hour, which is 99.9 % empty): how a customer's
-- activity spreads over the business day, the input of a time-of-day profile (a behaviour mini-dimension). Each
-- process on its own clock: transactions and sessions −6 h, contacts −8 h.
-- grain: customer_id, daypart
-- reconcile: n_tx = count(*) from {int_transactions_enriched}
-- reconcile: n_contacts = count(*) from {fct_interaction}
-- dense: customer_id from {int_customer_profile} x daypart from {dim_time_of_day}
with tx as (select customer_id, d.daypart, count(*) as n_tx
            from {int_transactions_enriched} t join {dim_time_of_day} d on d.hour_of_day = hour(t.transaction_ts_utc - interval 6 hour)
            group by all),
cc as (select customer_id, d.daypart, count(*) as n_contacts
       from {fct_interaction} i join {dim_time_of_day} d on d.hour_of_day = hour(i.interaction_ts_utc - interval 8 hour)
       group by all),
ss as (select customer_id, d.daypart, count(*) as n_sessions
       from {fct_session} s join {dim_time_of_day} d on d.hour_of_day = s.hour_of_day
       where customer_id is not null group by all),
grid as (select c.customer_id, p.daypart
         from {int_customer_profile} c cross join (select distinct daypart from {dim_time_of_day}) p)
select g.customer_id, g.daypart, coalesce(tx.n_tx, 0) as n_tx, coalesce(cc.n_contacts, 0) as n_contacts,
       coalesce(ss.n_sessions, 0) as n_sessions
from grid g left join tx using (customer_id, daypart) left join cc using (customer_id, daypart)
left join ss using (customer_id, daypart)
