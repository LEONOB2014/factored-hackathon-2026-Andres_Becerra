select
    date as rate_date, source_currency, target_currency, exchange_rate, buy_rate, sell_rate, source as rate_source
from {{ source('raw', 'daily_exchange_rates') }}
