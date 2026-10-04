-- BigQuery-native analytics view: daily fraud and decline KPIs per country/channel for dashboards.
-- Built only on BigQuery targets; the lakehouse equivalent is gold.fct_transaction.
{{ config(enabled=target.type == 'bigquery', materialized='view', schema='analytics') }}
select
    date_key,
    customer_country_code                                   as country_code,
    channel,
    count(*)                                                as tx_count,
    countif(transaction_status = 'Declined')                as declined_count,
    countif(is_fraud)                                       as confirmed_fraud_count,
    sum(amount_usd)                                         as amount_usd,
    safe_divide(countif(is_fraud), count(*))                as fraud_rate
from {{ source('published', 'fct_transaction') }}
group by 1, 2, 3
