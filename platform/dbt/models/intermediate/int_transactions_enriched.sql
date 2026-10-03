-- The conformed transaction fact: one row per transaction with repaired USD amount, local time,
-- direction, decoded response and one boolean per data-quality rule. Every downstream mart reads this.
with tx as (
    select
        t.*,
        p.product_family,
        p.product_type,
        p.currency                               as product_currency,
        p.opening_date                           as product_opening_date,
        c.country_code                           as customer_country_code,
        c.home_currency                          as customer_home_currency
    from {{ ref('stg_transactions') }} t
    join {{ ref('stg_products') }}  p using (product_id)
    join {{ ref('stg_customers') }} c on c.customer_id = t.customer_id
),
fx as (
    select tx.*, f.usd_per_unit
    from tx
    asof left join {{ ref('int_fx_usd') }} f
        on f.currency = tx.currency and f.rate_date <= tx.process_date
)
select
    transaction_id,
    transaction_ts_utc,
    {{ to_local('transaction_ts_utc', 'transaction_utc_offset_hours') }}       as transaction_ts_local,
    process_date,
    customer_id,
    product_id,
    product_family,
    product_type,
    transaction_type,
    coalesce(transaction_category, 'Unknown')                                 as transaction_category,
    channel,
    branch_id,
    merchant_name,
    transaction_country_code,
    customer_country_code,
    transaction_city,
    transaction_status,
    fx.response_code,
    rc.meaning                                                                as response_meaning,
    rc.suggested_action                                                       as response_suggested_action,
    amount,
    currency,
    -- USD amounts are only populated for non-USD rows in the source; recompute the rest from the daily rate.
    case when currency = 'USD' then amount
         else coalesce(amount_usd_source, amount * usd_per_unit) end          as amount_usd,
    case transaction_type
        when 'Deposit'    then  1
        when 'Adjustment' then  0
        else                   -1 end                                         as direction,   -- assumption: no counterparty/sign in source
    transaction_type in ('Deposit', 'Withdrawal') and channel in ('ATM', 'Branch')
                                                                              as is_cash,
    transaction_country_code <> customer_country_code                         as is_cross_border,
    hour(transaction_ts_local)                                                as local_hour,
    isodow(transaction_ts_local) >= 6                                         as is_weekend,
    latitude,
    longitude,
    is_fraud,
    fraud_score,
    -- data-quality flags (see dq_rule_slo seed)
    cast(transaction_ts_utc as date) < product_opening_date                   as dq_r01_before_product_open,
    transaction_status = 'Approved' and fx.response_code is null                 as dq_r03_approved_without_code,
    currency <> product_currency                                              as dq_r04_currency_mismatch,
    channel = 'Branch' and branch_id is null                                  as dq_r10_branch_without_id,
    customer_country_code = 'MX' and currency = 'USD'                         as dq_r17_mx_usd_label,
    currency <> 'USD' and amount_usd_source is null                           as dq_r18_amount_usd_imputed,
    channel in ('ATM', 'POS') and latitude is null                            as dq_r19_no_coordinates
from fx
left join {{ ref('response_codes') }} rc
    on rc.response_code = coalesce(fx.response_code, '<missing>')
