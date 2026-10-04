-- Card support (block/unblock, declines, travel, expiry, reissue): one row per debit or credit card with
-- a deterministic next-best-action that an agent or an LLM copilot can explain but not invent.
with tx as (
    select * from {{ ref('fct_transaction') }}
    where product_family in ('credit_card', 'debit_card')
),
agg as (
    select
        product_id,
        max(transaction_ts_utc) filter (where transaction_status = 'Approved')                   as last_approved_ts,
        count(*) filter (where transaction_status = 'Declined' and response_code = '05'
                           and transaction_ts_utc >= {{ as_of() }} - interval 30 day)            as declines_do_not_honor_30d,
        count(*) filter (where transaction_status = 'Declined' and response_code = '14'
                           and transaction_ts_utc >= {{ as_of() }} - interval 30 day)            as declines_invalid_card_30d,
        count(*) filter (where transaction_status = 'Declined' and response_code = '51'
                           and transaction_ts_utc >= {{ as_of() }} - interval 30 day)            as declines_insufficient_funds_30d,
        count(*) filter (where transaction_status = 'Declined' and response_code = '54'
                           and transaction_ts_utc >= {{ as_of() }} - interval 30 day)            as declines_expired_30d,
        count(*) filter (where is_cross_border and transaction_ts_utc >= {{ as_of() }} - interval 90 day)
                                                                                                 as foreign_tx_90d,
        list(distinct transaction_country_code order by transaction_country_code) filter (where is_cross_border
                                                         and transaction_ts_utc >= {{ as_of() }} - interval 90 day)
                                                                                                 as foreign_countries_90d,
        count(*) filter (where is_fraud and transaction_ts_utc >= {{ as_of() }} - interval 365 day) as confirmed_fraud_365d,
        count(*) filter (where channel in ('Web', 'App') and transaction_ts_utc >= {{ as_of() }} - interval 30 day)
                                                                                                 as card_not_present_30d
    from tx
    group by product_id
),
streak as (   -- declines after the last approval = what the customer is experiencing right now
    select tx.product_id, count(*) as current_decline_streak
    from tx join agg using (product_id)
    where tx.transaction_status = 'Declined'
      and tx.transaction_ts_utc > coalesce(agg.last_approved_ts, timestamp '1900-01-01')
    group by tx.product_id
),
cases as (
    select affected_product_id as product_id,
           count(*) filter (where not is_closed)                        as open_cases,
           arg_max(subcategory, (created_ts_utc, complaint_id))         as last_case_subcategory
    from {{ ref('stg_complaints') }}
    where affected_product_id is not null
    group by 1
),
contacts as (
    select product_id,
           count(*) filter (where interaction_ts_utc >= {{ as_of() }} - interval 30 day) as contacts_30d
    from (
        select unnest(mentioned_product_ids) as product_id, interaction_ts_utc
        from {{ ref('stg_call_center_interactions') }}
        where mentioned_product_ids is not null
    )
    group by 1
)
select
    p.product_id,
    p.customer_id,
    c.document_token,
    c.country_code,
    p.product_type,
    p.product_status,
    p.product_status = 'Blocked'                                  as is_blocked,
    p.expiration_date,
    date_diff('day', {{ as_of() }}, p.expiration_date)            as days_to_expiry,
    p.dq_r22_active_expired_card                                  as is_active_but_expired,
    p.credit_limit,
    p.current_balance,
    p.utilization,
    p.days_past_due,
    a.last_approved_ts,
    coalesce(s.current_decline_streak, 0)                         as current_decline_streak,
    coalesce(a.declines_do_not_honor_30d, 0)                      as declines_do_not_honor_30d,
    coalesce(a.declines_invalid_card_30d, 0)                      as declines_invalid_card_30d,
    coalesce(a.declines_insufficient_funds_30d, 0)                as declines_insufficient_funds_30d,
    coalesce(a.declines_expired_30d, 0)                           as declines_expired_30d,
    coalesce(a.foreign_tx_90d, 0)                                 as foreign_tx_90d,
    a.foreign_countries_90d,
    coalesce(a.card_not_present_30d, 0)                           as card_not_present_30d,
    coalesce(a.confirmed_fraud_365d, 0)                           as confirmed_fraud_365d,
    coalesce(k.open_cases, 0)                                     as open_cases,
    k.last_case_subcategory,
    coalesce(ct.contacts_30d, 0)                                  as contacts_30d,
    -- rule-based next best action, ordered by priority; auditable and explainable by construction
    case
        when coalesce(a.confirmed_fraud_365d, 0) > 0 and p.product_status <> 'Blocked' then 'FRAUD_REVIEW_AND_BLOCK'
        when p.dq_r22_active_expired_card or coalesce(a.declines_expired_30d, 0) > 0  then 'REISSUE_CARD'
        when p.expiration_date between {{ as_of() }} and {{ as_of() }} + interval 45 day then 'PROACTIVE_RENEWAL'
        when coalesce(a.declines_invalid_card_30d, 0) >= 3                            then 'VERIFY_CARD_DATA'
        when coalesce(a.declines_do_not_honor_30d, 0) >= 3                            then 'REVIEW_RISK_BLOCK'
        when p.utilization >= 0.95 or coalesce(a.declines_insufficient_funds_30d, 0) >= 3 then 'EXPLAIN_LIMIT_OR_OFFER_INCREASE_REVIEW'
        when p.product_status = 'Blocked'                                             then 'UNBLOCK_AFTER_STRONG_AUTH'
        else 'NONE'
    end                                                           as next_best_action
from {{ ref('int_products_enriched') }} p
join {{ ref('int_customer_profile') }} c using (customer_id)
left join agg a      using (product_id)
left join streak s   using (product_id)
left join cases k    using (product_id)
left join contacts ct using (product_id)
where p.product_family in ('credit_card', 'debit_card')
