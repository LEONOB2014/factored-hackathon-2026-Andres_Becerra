select
    date as rate_date, source_currency, target_currency, exchange_rate, buy_rate, sell_rate, source as rate_source
from {{ ref('typed_daily_exchange_rates') }} src
where {{ not_held('src', 'daily_exchange_rates') }}
