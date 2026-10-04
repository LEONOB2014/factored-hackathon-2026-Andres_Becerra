-- Periodic snapshot, one row per product and month from the month it opened (or the first month of data) to the
-- last month, dense: the grain of portfolio management and vintage analysis. Flows are the product's own
-- transactions; months_since_open places each row on its vintage curve. Balance, limit, utilisation and days past
-- due exist only as the current snapshot of the source, so they are carried as attributes of the product (the
-- same value on every row), never as monthly measures: no roll rate or balance history can be built from them.
-- grain: product_id, month_start
-- reconcile: n_tx = count(product_id) from {int_transactions_enriched} | month_start = cast(date_trunc('month', transaction_ts_utc) as date)
with months as (select month_start from {dim_month}),
grid as (
    select p.product_id, m.month_start
    from {int_products_enriched} p join months m
      on m.month_start >= cast(date_trunc('month', p.opening_date) as date)
     or (p.opening_date < (select min(month_start) from months) and m.month_start >= (select min(month_start) from months))),
tx as (
    select product_id, cast(date_trunc('month', transaction_ts_utc) as date) as month_start,
           count(*) as n_tx,
           sum(amount_usd) filter (where direction = -1 and transaction_status = 'Approved') as outflow_usd,
           sum(amount_usd) filter (where direction = 1 and transaction_status = 'Approved') as inflow_usd,
           sum(amount_usd) filter (where transaction_type = 'Payment' and transaction_status = 'Approved') as payments_usd,
           count(*) filter (where transaction_status = 'Declined') as n_declined,
           count(*) filter (where response_code = '51') as n_insufficient_funds
    from {int_transactions_enriched} where product_id is not null group by all),
early as (
    -- transactions dated before the product opened (R01) fall outside the product's grid: kept in a pre-opening row
    select t.product_id, t.month_start, t.n_tx, t.outflow_usd, t.inflow_usd, t.payments_usd, t.n_declined,
           t.n_insufficient_funds
    from tx t where not exists (select 1 from grid g where g.product_id = t.product_id and g.month_start = t.month_start)),
rows_ as (
    select g.product_id, g.month_start, false as before_opening from grid g
    union all select product_id, month_start, true from early)
select r.product_id, r.month_start, r.before_opening,
       p.customer_id, p.product_family, p.product_type, p.is_credit_product, p.currency, p.opening_date,
       date_diff('month', cast(date_trunc('month', p.opening_date) as date), r.month_start) as months_since_open,
       cast(date_trunc('quarter', p.opening_date) as date)                                   as vintage_quarter,
       coalesce(tx.n_tx, 0) as n_tx, coalesce(tx.outflow_usd, 0) as outflow_usd, coalesce(tx.inflow_usd, 0) as inflow_usd,
       coalesce(tx.payments_usd, 0) as payments_usd, coalesce(tx.n_declined, 0) as n_declined,
       coalesce(tx.n_insufficient_funds, 0) as n_insufficient_funds,
       p.balance_usd as snapshot_balance_usd, p.credit_limit_usd as snapshot_credit_limit_usd,
       p.utilization as snapshot_utilization, p.days_past_due as snapshot_days_past_due,
       p.dpd_bucket as snapshot_dpd_bucket, p.product_status as snapshot_status
from rows_ r
join {int_products_enriched} p using (product_id)
left join tx using (product_id, month_start)
