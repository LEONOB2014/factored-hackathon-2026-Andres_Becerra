-- Product dimension, SCD Type 2 from snap_products. Same validity convention as dim_customer.
with v as (
    select s.*, row_number() over (partition by product_id order by dbt_valid_from) as version_no
    from {{ ref('snap_products') }} s
)
select
    md5(product_id || '|' || cast(dbt_valid_from as varchar))        as product_sk,
    product_id,
    version_no,
    customer_id,
    product_type,
    product_family,
    is_credit_product,
    currency,
    credit_limit,
    interest_rate,
    opening_date,
    expiration_date,
    product_status,
    opening_channel,
    days_past_due,
    case when version_no = 1 then cast(opening_date as timestamp) else dbt_valid_from end as valid_from,
    coalesce(dbt_valid_to, timestamp '9999-12-31')                   as valid_to,
    dbt_valid_from                                                   as recorded_from,
    dbt_valid_to is null                                             as is_current,
    row_hash
from v
