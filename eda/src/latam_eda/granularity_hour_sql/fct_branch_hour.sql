-- Periodic snapshot, one row per branch and UTC hour with branch activity (sparse: an hour with no teller or ATM
-- transaction has no row). Each hour carries the branch's scheduled open share for that weekday and hour of the
-- business day, so teller activity in a closed hour is counted where it happens: the opening-hours control.
-- grain: branch_id, hour_start
-- reconcile: n_tx = count(*) filter (where channel in ('Branch', 'ATM') and branch_id is not null) from {int_transactions_enriched}
-- reconcile: atm_cash_out_usd = sum(amount_usd) filter (where channel = 'ATM' and branch_id is not null and is_cash and direction = -1 and transaction_status = 'Approved') from {int_transactions_enriched}
with t as (
    select branch_id, date_trunc('hour', transaction_ts_utc) as hour_start, count(*) as n_tx,
           count(*) filter (where channel = 'Branch') as n_teller,
           count(*) filter (where channel = 'ATM') as n_atm,
           coalesce(sum(amount_usd) filter (where channel = 'ATM' and is_cash and direction = -1
                                               and transaction_status = 'Approved'), 0) as atm_cash_out_usd
    from {int_transactions_enriched}
    where channel in ('Branch', 'ATM') and branch_id is not null
    group by all)
select t.*, h.delivery_day, h.hour_of_day, h.delivery_weekday,
       coalesce(s.open_fraction, 0) as open_fraction, coalesce(s.open_fraction_any_day, 0) as open_fraction_any_day,
       s.branch_id is null as branch_unknown
from t join {dim_hour} h using (hour_start)
left join {dim_branch_schedule} s
  on s.branch_id = t.branch_id and s.iso_weekday = h.delivery_weekday and s.hour_of_day = h.hour_of_day
