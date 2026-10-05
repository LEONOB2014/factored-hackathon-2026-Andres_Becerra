-- fct_branch_hour: sum(atm_cash_out_usd) equals sum(amount_usd) filter (where channel = 'ATM' and branch_id is not null and is_cash and direction = -1 and transaction_status = 'Approved') of its atomic source.
with l as (select sum(atm_cash_out_usd) as v from {{ ref('fct_branch_hour') }}),
     r as (select sum(amount_usd) filter (where channel = 'ATM' and branch_id is not null and is_cash and direction = -1 and transaction_status = 'Approved') as v from {{ ref('int_transactions_enriched') }})
select l.v as aggregate_value, r.v as atomic_value from l, r
where abs(coalesce(l.v, 0) - coalesce(r.v, 0)) > 1e-6 * greatest(1, abs(coalesce(r.v, 0)))
