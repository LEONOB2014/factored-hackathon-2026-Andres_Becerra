-- Customer 360: one row per customer, the shared backbone for the agent copilot, credit, churn,
-- marketing and GraphRAG entity documents. Windows are relative to var('as_of_date').
with tx as (
    select
        customer_id,
        count(*) filter (where transaction_ts_utc >= {{ as_of() }} - interval 30 day)              as tx_count_30d,
        count(*) filter (where transaction_ts_utc >= {{ as_of() }} - interval 90 day)              as tx_count_90d,
        count(*) filter (where transaction_ts_utc >= {{ as_of() }} - interval 365 day)             as tx_count_365d,
        sum(amount_usd) filter (where direction = -1 and transaction_status = 'Approved'
                                  and transaction_ts_utc >= {{ as_of() }} - interval 90 day)        as outflow_usd_90d,
        sum(amount_usd) filter (where direction = 1 and transaction_status = 'Approved'
                                  and transaction_ts_utc >= {{ as_of() }} - interval 90 day)        as inflow_usd_90d,
        avg((transaction_status = 'Declined')::int)
            filter (where transaction_ts_utc >= {{ as_of() }} - interval 90 day)                   as decline_rate_90d,
        avg(is_cross_border::int) filter (where transaction_ts_utc >= {{ as_of() }} - interval 365 day)
                                                                                                   as cross_border_share_365d,
        count(distinct merchant_name) filter (where transaction_ts_utc >= {{ as_of() }} - interval 365 day)
                                                                                                   as distinct_merchants_365d,
        count(*) filter (where is_fraud and transaction_ts_utc >= {{ as_of() }} - interval 365 day) as confirmed_fraud_365d,
        max(transaction_ts_utc)                                                                    as last_tx_ts,
        mode(channel)                                                                              as main_tx_channel
    from {{ ref('fct_transaction') }}
    group by customer_id
),
prod as (
    select
        customer_id,
        count(*)                                                                as n_products,
        count(*) filter (where product_status = 'Active')                       as n_active_products,
        list(distinct product_type order by product_type)                       as product_types,
        sum(balance_usd) filter (where product_family in ('deposit', 'investment')) as deposits_usd,
        sum(balance_usd) filter (where product_family in ('credit_card', 'loan'))   as debt_usd,
        sum(credit_limit_usd) filter (where product_family = 'credit_card')     as card_limit_usd,
        max(days_past_due)                                                      as max_days_past_due,
        bool_or(product_family = 'loan')                                        as has_loan,
        bool_or(product_family = 'credit_card')                                 as has_credit_card,
        bool_or(has_linked_app)                                                 as has_linked_app,
        count(*) filter (where dq_r02_before_customer_registration)             as dq_products_before_registration
    from {{ ref('int_products_enriched') }}
    group by customer_id
),
dig as (
    select
        customer_id,
        count(distinct session_id) filter (where event_ts_utc >= {{ as_of() }} - interval 90 day) as sessions_90d,
        count(*) filter (where event_type = 'Login' and event_ts_utc >= {{ as_of() }} - interval 90 day) as logins_90d,
        count(*) filter (where event_type = 'Error' and event_ts_utc >= {{ as_of() }} - interval 90 day) as app_errors_90d,
        max(event_ts_utc) filter (where event_type = 'Login')                   as last_login_ts,
        mode(channel)                                                           as main_digital_channel
    from {{ ref('stg_digital_events') }}
    where customer_id is not null
    group by customer_id
),
cc as (
    select
        customer_id,
        count(*) filter (where interaction_ts_utc >= {{ as_of() }} - interval 90 day)           as contacts_90d,
        count(*) filter (where was_escalated and interaction_ts_utc >= {{ as_of() }} - interval 365 day) as escalations_365d,
        avg((detected_sentiment in ('Negativo', 'Muy Negativo'))::int)
            filter (where interaction_ts_utc >= {{ as_of() }} - interval 365 day)               as negative_sentiment_share_365d,
        max(interaction_ts_utc)                                                                 as last_contact_ts,
        arg_max(contact_reason, interaction_ts_utc)                                             as last_contact_reason
    from {{ ref('stg_call_center_interactions') }}
    group by customer_id
),
cmp as (
    select
        customer_id,
        count(*) filter (where not is_closed)                                                   as open_cases,
        count(*) filter (where created_ts_utc >= {{ as_of() }} - interval 365 day)              as complaints_365d,
        count(*) filter (where sla_breached and created_ts_utc >= {{ as_of() }} - interval 365 day) as sla_breaches_365d,
        bool_or(reception_channel = 'Regulator')                                                as ever_escalated_to_regulator
    from {{ ref('stg_complaints') }}
    group by customer_id
),
mkt as (
    select
        customer_id,
        count(*) filter (where send_ts_utc >= {{ as_of() }} - interval 365 day)                 as sends_365d,
        count(*) filter (where had_conversion and send_ts_utc >= {{ as_of() }} - interval 365 day) as conversions_365d
    from {{ ref('stg_campaign_sends') }}
    group by customer_id
),
srv as (
    select customer_id,
           arg_max(main_score, survey_ts_utc) filter (where survey_type = 'NPS')  as last_nps_score,
           arg_max(main_score, survey_ts_utc) filter (where survey_type = 'CSAT') as last_csat_score
    from {{ ref('stg_satisfaction_surveys') }}
    group by customer_id
)
select
    p.customer_id,
    p.document_token,
    p.country_code,
    p.city,
    p.segment,
    p.customer_status,
    p.tenure_days,
    p.age_years,
    p.credit_score,
    p.monthly_income_usd,
    p.accepts_marketing,
    coalesce(prod.n_products, 0)                     as n_products,
    coalesce(prod.n_active_products, 0)              as n_active_products,
    prod.product_types,
    coalesce(prod.deposits_usd, 0)                   as deposits_usd,
    coalesce(prod.debt_usd, 0)                       as debt_usd,
    prod.card_limit_usd,
    prod.max_days_past_due,
    coalesce(prod.has_loan, false)                   as has_loan,
    coalesce(prod.has_credit_card, false)            as has_credit_card,
    coalesce(prod.has_linked_app, false)             as has_linked_app,
    coalesce(tx.tx_count_30d, 0)                     as tx_count_30d,
    coalesce(tx.tx_count_90d, 0)                     as tx_count_90d,
    coalesce(tx.tx_count_365d, 0)                    as tx_count_365d,
    coalesce(tx.inflow_usd_90d, 0)                   as inflow_usd_90d,
    coalesce(tx.outflow_usd_90d, 0)                  as outflow_usd_90d,
    tx.decline_rate_90d,
    tx.cross_border_share_365d,
    tx.distinct_merchants_365d,
    coalesce(tx.confirmed_fraud_365d, 0)             as confirmed_fraud_365d,
    tx.last_tx_ts,
    date_diff('day', cast(tx.last_tx_ts as date), {{ as_of() }}) as days_since_last_tx,
    tx.main_tx_channel,
    coalesce(dig.sessions_90d, 0)                    as sessions_90d,
    coalesce(dig.logins_90d, 0)                      as logins_90d,
    coalesce(dig.app_errors_90d, 0)                  as app_errors_90d,
    dig.last_login_ts,
    dig.main_digital_channel,
    coalesce(cc.contacts_90d, 0)                     as contacts_90d,
    coalesce(cc.escalations_365d, 0)                 as escalations_365d,
    cc.negative_sentiment_share_365d,
    cc.last_contact_ts,
    cc.last_contact_reason,
    coalesce(cmp.open_cases, 0)                      as open_cases,
    coalesce(cmp.complaints_365d, 0)                 as complaints_365d,
    coalesce(cmp.sla_breaches_365d, 0)               as sla_breaches_365d,
    coalesce(cmp.ever_escalated_to_regulator, false) as ever_escalated_to_regulator,
    coalesce(mkt.sends_365d, 0)                      as sends_365d,
    coalesce(mkt.conversions_365d, 0)                as conversions_365d,
    srv.last_nps_score,
    srv.last_csat_score,
    -- data-quality context travels with the record so every consumer sees it
    p.dq_r05_minor_at_registration,
    p.dq_r06_future_last_updated,
    coalesce(prod.dq_products_before_registration, 0) as dq_products_before_registration
from {{ ref('int_customer_profile') }} p
left join prod using (customer_id)
left join tx   using (customer_id)
left join dig  using (customer_id)
left join cc   using (customer_id)
left join cmp  using (customer_id)
left join mkt  using (customer_id)
left join srv  using (customer_id)
