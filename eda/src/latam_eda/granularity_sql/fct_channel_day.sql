-- Periodic snapshot, one row per market, transaction channel and local day, dense over the channels a market uses:
-- the grain at which channel capacity is planned (ATM fleet, branch tellers, app infrastructure) and channel
-- migration is measured.
-- grain: country_code, channel, local_date
-- reconcile: n_tx = count(*) from {int_transactions_enriched}
-- dense: country_code from {fct_country_day} x channel from {int_transactions_enriched} x local_date from {fct_country_day}
with off as (select customer_id, country_code from {int_customer_profile}),
tx as (
    select o.country_code, t.channel, t.process_date as local_date,
           count(*) as n_tx,
           sum(t.amount_usd) filter (where t.transaction_status = 'Approved') as approved_usd,
           count(*) filter (where t.transaction_status = 'Declined') as n_declined,
           count(*) filter (where t.response_code = '51') as n_insufficient_funds
    from {int_transactions_enriched} t join off o using (customer_id) group by all),
grid as (
    select d.country_code, c.channel, d.local_date
    from (select distinct country_code, local_date from {fct_country_day}) d
    cross join (select distinct channel from {int_transactions_enriched}) c)
select g.country_code, g.channel, g.local_date,
       coalesce(tx.n_tx, 0) as n_tx, coalesce(tx.approved_usd, 0) as approved_usd,
       coalesce(tx.n_declined, 0) as n_declined, coalesce(tx.n_insufficient_funds, 0) as n_insufficient_funds
from grid g left join tx using (country_code, channel, local_date)
