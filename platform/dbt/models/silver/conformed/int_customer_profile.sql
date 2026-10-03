-- Pseudonymized customer profile: the only customer table the marts join. Direct identifiers are
-- replaced by tokens; protected/proxy attributes are split off to int_customer_fairness_attributes.
with fx_now as (
    select currency, usd_per_unit
    from {{ ref('int_fx_usd') }}
    where rate_date = (select max(rate_date) from {{ ref('int_fx_usd') }})
),
mxn as (   -- MXN only exists as a rate: incomes of Mexican customers are in MXN, their accounts in USD
    select exchange_rate as usd_per_unit
    from {{ ref('stg_daily_exchange_rates') }}
    where source_currency = 'MXN' and target_currency = 'USD'
    qualify row_number() over (order by rate_date desc) = 1
)
select
    c.customer_id,
    {{ pii_hash('c.document_number') }}                                   as document_token,
    {{ pii_hash('c.email') }}                                             as email_token,
    {{ pii_hash('c.mobile_phone') }}                                      as phone_token,
    c.country_code,
    c.home_currency,
    c.utc_offset_hours,
    c.city,
    c.segment,
    c.customer_status,
    c.credit_score,
    c.monthly_income_local,
    c.monthly_income_local * case c.home_currency when 'MXN' then (select usd_per_unit from mxn)
                                                  else f.usd_per_unit end   as monthly_income_usd,
    c.occupation,
    c.education_level,
    c.registration_date,
    date_diff('day', cast(c.registration_date as date), {{ as_of() }})      as tenure_days,
    date_diff('year', c.date_of_birth, {{ as_of() }})                       as age_years,
    date_diff('year', c.date_of_birth, cast(c.registration_date as date)) < 18
                                                                            as dq_r05_minor_at_registration,
    c.last_updated > date '{{ var("data_end") }}' + interval 1 day                         as dq_r06_future_last_updated,
    c.accepts_marketing,
    c.row_hash
from {{ ref('stg_customers') }} c
left join fx_now f on f.currency = c.home_currency
