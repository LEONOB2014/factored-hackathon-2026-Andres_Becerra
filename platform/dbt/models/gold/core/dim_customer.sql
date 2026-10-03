-- Customer dimension, SCD Type 2 from snap_customers, pseudonymized (tokens only, no direct identifiers).
-- The first observed version is treated as valid since registration because no earlier history exists;
-- later versions start at the snapshot time (system time). customer_sk identifies one version.
with v as (
    select
        s.*,
        row_number() over (partition by customer_id order by dbt_valid_from) as version_no
    from {{ ref('snap_customers') }} s
)
select
    md5(customer_id || '|' || cast(dbt_valid_from as varchar))       as customer_sk,
    customer_id,
    version_no,
    {{ pii_hash('document_number') }}                                 as document_token,
    country_code,
    home_currency,
    city,
    segment,
    customer_status,
    credit_score,
    monthly_income_local,
    occupation,
    education_level,
    cast(registration_date as date)                                   as registration_date,
    accepts_marketing,
    case when version_no = 1 then cast(registration_date as timestamp) else dbt_valid_from end as valid_from,
    coalesce(dbt_valid_to, timestamp '9999-12-31')                    as valid_to,
    dbt_valid_from                                                    as recorded_from,
    dbt_valid_to is null                                              as is_current,
    row_hash
from v
