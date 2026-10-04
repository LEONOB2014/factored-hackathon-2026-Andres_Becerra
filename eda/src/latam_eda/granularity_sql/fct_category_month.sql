-- Periodic snapshot, one row per merchant category, market and month: the grain of spend-mix and portfolio
-- analysis for card issuing and merchant partnerships. Transactions without a merchant (withdrawals, transfers,
-- deposits) fall in the 'no merchant' category so that every transaction is counted once and the fact reconciles.
-- grain: category, country_code, month_start
-- reconcile: n_tx = count(*) from {fct_transaction} | month_start = cast(date_trunc('month', transaction_ts_utc) as date)
select coalesce(m.main_category, 'no merchant') as category, t.customer_country_code as country_code,
       cast(date_trunc('month', t.transaction_ts_utc) as date) as month_start,
       count(*) as n_tx, count(distinct t.customer_id) as n_customers,
       sum(t.amount_usd) filter (where t.transaction_status = 'Approved') as approved_usd,
       count(*) filter (where t.transaction_status = 'Declined') as n_declined,
       count(*) filter (where t.is_fraud) as n_flagged_fraud,
       count(*) filter (where t.is_cross_border) as n_cross_border
from {fct_transaction} t left join {dim_merchant} m using (merchant_id)
group by all
