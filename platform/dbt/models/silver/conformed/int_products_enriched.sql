-- Product state with USD balances, utilization and product-level data-quality flags.
with fx_now as (
    select currency, usd_per_unit
    from {{ ref('int_fx_usd') }}
    where rate_date = (select max(rate_date) from {{ ref('int_fx_usd') }})
)
select
    p.product_id,
    p.customer_id,
    p.product_type,
    p.product_family,
    p.is_credit_product,
    p.currency,
    p.current_balance,
    p.current_balance * f.usd_per_unit                                     as balance_usd,
    p.credit_limit,
    p.credit_limit * f.usd_per_unit                                        as credit_limit_usd,
    case when p.product_family = 'credit_card' and p.credit_limit > 0
         then p.current_balance / p.credit_limit end                       as utilization,
    p.interest_rate,
    p.opening_date,
    p.expiration_date,
    p.product_status,
    p.opening_channel,
    p.has_linked_app,
    p.days_past_due,
    case when p.days_past_due is null then null
         when p.days_past_due = 0  then 'current'
         when p.days_past_due <= 30 then '01-30'
         when p.days_past_due <= 60 then '31-60'
         when p.days_past_due <= 90 then '61-90'
         else '90+' end                                                    as dpd_bucket,
    p.last_transaction_date,
    p.opening_date < cast(c.registration_date as date)                     as dq_r02_before_customer_registration,
    p.last_updated > date '{{ var("data_end") }}' + interval 1 day                        as dq_r07_future_last_updated,
    p.product_family in ('deposit', 'investment', 'insurance', 'debit_card')
        and p.credit_limit is not null                                     as dq_r08_limit_on_non_credit,
    p.product_family in ('deposit', 'investment', 'insurance', 'debit_card')
        and p.days_past_due is not null                                    as dq_r09_dpd_on_non_credit,
    p.product_family in ('credit_card', 'debit_card') and p.product_status = 'Active'
        and p.expiration_date < {{ as_of() }}                              as dq_r22_active_expired_card,
    p.row_hash
from {{ ref('stg_products') }} p
join {{ ref('stg_customers') }} c using (customer_id)
left join fx_now f on f.currency = p.currency
