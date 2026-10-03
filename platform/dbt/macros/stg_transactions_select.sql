{% macro stg_transactions_select(src) %}
select
    t.transaction_id,
    t.transaction_date                             as transaction_ts_utc,
    t.process_date,
    t.product_id,
    t.customer_id,
    t.transaction_type,
    t.transaction_category,
    t.amount,
    t.currency,
    t.amount_usd                                   as amount_usd_source,
    t.channel,
    t.branch_id,
    t.merchant_name,
    t.merchant_category,
    cc.iso2                                        as transaction_country_code,
    cc.utc_offset_hours                            as transaction_utc_offset_hours,
    t.transaction_city,
    t.transaction_status,
    t.response_code,
    t.is_fraud,
    t.fraud_score,                                 -- legacy score; it IS the label (notebook 09). Never a feature.
    t.latitude,
    t.longitude
from {{ src }} t
left join {{ ref('country_codes') }} cc on cc.raw_name = t.transaction_country
{% endmacro %}
