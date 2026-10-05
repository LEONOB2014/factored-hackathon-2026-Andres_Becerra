-- Merchant categories, the slicing dimension of the spend-mix fact. 'no merchant' holds the transactions that have no
-- merchant (withdrawals, transfers, deposits), so that every transaction belongs to exactly one category.
-- grain: category
select main_category as category, count(*) as n_merchants, list(merchant_name order by merchant_name) as merchants
from {dim_merchant} group by 1
union all
select 'no merchant', 0, []
