-- Periodic snapshot, one row per branch and the branch's local day, dense over the branches that ever served a
-- transaction: the grain of cash logistics. A branch (with its ATMs) must hold enough cash for the day's withdrawals
-- without holding idle cash, and cash-in-transit is scheduled per branch and day. Withdrawals and deposits are the
-- approved cash movements served at the branch or its ATMs; amounts are in USD (comparable across markets) and in the
-- currency the cash was dispensed in.
-- grain: branch_id, local_date
-- reconcile: n_tx = count(branch_id) from {int_transactions_enriched}
-- dense: branch_id from {dim_branch} x local_date from {dim_data_day}
with b as (select b.branch_id, b.country_code, b.atm_count, c.utc_offset_hours
           from {dim_branch} b left join {dim_country} c using (country_code)),
tx as (
    select t.branch_id, cast(t.transaction_ts_utc + to_hours(coalesce(b.utc_offset_hours, -6)) as date) as local_date,
           count(*) as n_tx, count(*) filter (where t.channel = 'ATM') as n_atm_tx,
           count(*) filter (where t.channel = 'Branch') as n_counter_tx,
           count(*) filter (where t.transaction_type = 'Withdrawal' and t.transaction_status = 'Approved') as n_withdrawals,
           sum(t.amount_usd) filter (where t.transaction_type = 'Withdrawal' and t.transaction_status = 'Approved') as withdrawals_usd,
           sum(t.amount) filter (where t.transaction_type = 'Withdrawal' and t.transaction_status = 'Approved') as withdrawals_amount,
           sum(t.amount_usd) filter (where t.transaction_type = 'Deposit' and t.transaction_status = 'Approved') as deposits_usd,
           count(*) filter (where t.response_code = '51') as n_insufficient_funds
    from {int_transactions_enriched} t left join b using (branch_id)
    where t.branch_id is not null group by all),
cp as (
    select related_branch_id as branch_id, cast(created_ts_utc as date) as local_date, count(*) as complaints_linked
    from {fct_complaint} where related_branch_id is not null group by all),
grid as (
    select br.branch_id, d.local_date
    from (select distinct branch_id from {int_transactions_enriched} where branch_id is not null) br
    cross join (select distinct local_date from {dim_data_day}) d)
select g.branch_id, g.local_date, b.country_code, b.atm_count,
       coalesce(tx.n_tx, 0) as n_tx, coalesce(tx.n_atm_tx, 0) as n_atm_tx, coalesce(tx.n_counter_tx, 0) as n_counter_tx,
       coalesce(tx.n_withdrawals, 0) as n_withdrawals, coalesce(tx.withdrawals_usd, 0) as withdrawals_usd,
       coalesce(tx.withdrawals_amount, 0) as withdrawals_amount, coalesce(tx.deposits_usd, 0) as deposits_usd,
       coalesce(tx.n_insufficient_funds, 0) as n_insufficient_funds, coalesce(cp.complaints_linked, 0) as complaints_linked
from grid g
left join b using (branch_id)
left join tx using (branch_id, local_date)
left join cp using (branch_id, local_date)
