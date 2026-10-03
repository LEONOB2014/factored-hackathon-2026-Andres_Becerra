-- USD value of one unit of each currency per day. Note: ARS is flat at ~350/USD for three years in this
-- synthetic feed; real ARS lost >90 % of its value in that window, so inflation-sensitive features are invalid.
select rate_date, source_currency as currency, exchange_rate as usd_per_unit
from {{ ref('stg_daily_exchange_rates') }}
where target_currency = 'USD'
union all
select distinct rate_date, 'USD', 1.0
from {{ ref('stg_daily_exchange_rates') }}
