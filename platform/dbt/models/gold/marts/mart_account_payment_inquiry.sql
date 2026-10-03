-- Account & payment inquiries ("what is my balance", "why was my payment declined", "did my transfer go
-- through"): one row per product with the answer-ready context an agent or a copilot needs in one read. The last 20 transactions
-- per product live in mart_product_recent_transactions (one row each, rank 1 = latest): normalized rows serve and
-- index better than nested lists and keep memory bounded.
with recent as (
    select
        product_id,
        count(*) filter (where transaction_status = 'Pending')                               as pending_count,
        sum(amount) filter (where transaction_status = 'Pending')                            as pending_amount,
        count(*) filter (where transaction_status = 'Declined'
                           and transaction_ts_utc >= {{ as_of() }} - interval 30 day)         as declined_30d,
        count(*) filter (where transaction_status = 'Reversed'
                           and transaction_ts_utc >= {{ as_of() }} - interval 30 day)         as reversed_30d,
        max(transaction_ts_utc) filter (where transaction_type = 'Deposit'
                                          and transaction_status = 'Approved')               as last_deposit_ts,
        max(transaction_ts_utc) filter (where transaction_type = 'Payment'
                                          and transaction_status = 'Approved')               as last_payment_ts,
        arg_max(amount, transaction_ts_utc) filter (where transaction_type = 'Payment'
                                                     and transaction_status = 'Approved')    as last_payment_amount,
        arg_max(response_meaning, transaction_ts_utc) filter (where transaction_status = 'Declined')
                                                                                             as last_decline_reason,
        arg_max(response_suggested_action, transaction_ts_utc) filter (where transaction_status = 'Declined')
                                                                                             as last_decline_action
    from {{ ref('fct_transaction') }}
    group by product_id
),
decline_mix as (
    select product_id, map(list(response_code), list(n)) as declines_by_code_90d
    from (
        select product_id, coalesce(response_code, '<missing>') as response_code, count(*) as n
        from {{ ref('fct_transaction') }}
        where transaction_status = 'Declined' and transaction_ts_utc >= {{ as_of() }} - interval 90 day
        group by all
    )
    group by product_id
)
select
    p.product_id,
    p.customer_id,
    c.document_token,
    c.country_code,
    c.segment,
    p.product_type,
    p.product_family,
    p.product_status,
    p.currency,
    p.current_balance,
    p.balance_usd,
    case when p.product_family = 'credit_card' then p.credit_limit - p.current_balance end as available_credit,
    p.utilization,
    p.days_past_due,
    p.dpd_bucket,
    p.interest_rate,
    p.expiration_date,
    coalesce(r.pending_count, 0)    as pending_count,
    r.pending_amount,
    coalesce(r.declined_30d, 0)     as declined_30d,
    coalesce(r.reversed_30d, 0)     as reversed_30d,
    d.declines_by_code_90d,
    r.last_decline_reason,
    r.last_decline_action,
    r.last_deposit_ts,
    r.last_payment_ts,
    r.last_payment_amount,
    rt.n_recent_transactions
from {{ ref('int_products_enriched') }} p
join {{ ref('int_customer_profile') }} c using (customer_id)
left join recent r using (product_id)
left join (select product_id, count(*) as n_recent_transactions
           from {{ ref('mart_product_recent_transactions') }} group by 1) rt using (product_id)
left join decline_mix d using (product_id)
