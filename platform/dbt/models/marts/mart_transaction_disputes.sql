-- Transaction disputes: one row per transaction/fee complaint, linked to the most likely disputed
-- transaction. The source has no complaint -> transaction key, so the link is probabilistic and carries
-- its evidence; production must capture disputed_transaction_id at intake (see report ch. 06).
with disputes as (
    select *
    from {{ ref('stg_complaints') }}
    where category in ('Transactions', 'Fees')
       or subcategory in ('Cargo no reconocido', 'Cobro indebido')
),
candidates as (
    select
        d.complaint_id,
        t.transaction_id,
        t.transaction_ts_utc,
        t.amount,
        t.currency,
        t.amount_usd,
        t.merchant_name,
        t.channel,
        t.transaction_country_code,
        t.transaction_status,
        t.is_fraud,
        -- evidence score: same product (+3), amount within 1 % (+3), recency (+0..2).
        -- Each term is null-safe: one NULL term would null the whole score (caught by a unit test).
          3 * coalesce(t.product_id = d.affected_product_id, false)::int
        + 3 * coalesce(abs(t.amount - d.claimed_amount) <= 0.01 * d.claimed_amount, false)::int
        + 2 * (1 - date_diff('day', t.transaction_ts_utc, d.created_ts_utc) / 60.0)          as match_score,
        coalesce(t.product_id = d.affected_product_id, false)                               as product_match,
        coalesce(abs(t.amount - d.claimed_amount) <= 0.01 * d.claimed_amount, false)        as amount_match
    from disputes d
    join {{ ref('int_transactions_enriched') }} t
      on t.customer_id = d.customer_id
     and t.transaction_ts_utc between d.created_ts_utc - interval 60 day and d.created_ts_utc
     and (d.affected_product_id is null or t.product_id = d.affected_product_id
          or (d.claimed_amount is not null and abs(t.amount - d.claimed_amount) <= 0.01 * d.claimed_amount))
),
best as (
    select *, count(*) over (partition by complaint_id) as n_candidates
    from candidates
    qualify row_number() over (partition by complaint_id order by match_score desc, transaction_ts_utc desc) = 1
),
history as (
    select complaint_id,
           count(*) over (partition by customer_id order by created_ts_utc
                          range between interval 365 day preceding and current row) - 1 as prior_disputes_365d
    from disputes
)
select
    d.complaint_id,
    d.customer_id,
    c.document_token,
    c.country_code,
    c.segment,
    d.case_type,
    d.category,
    d.subcategory,
    d.reception_channel,
    d.reception_channel = 'Regulator'                                         as came_via_regulator,
    d.priority,
    d.status,
    d.is_closed,
    d.claimed_amount,
    d.claimed_currency,
    d.created_ts_utc,
    -- SLA clocks (hours). Regulatory deadlines differ by country and must come from compliance (seed TBD).
    date_diff('hour', d.created_ts_utc, d.assigned_ts_utc)                    as hours_to_assignment,
    date_diff('hour', d.created_ts_utc, d.first_response_ts_utc)              as hours_to_first_response,
    date_diff('hour', d.created_ts_utc, coalesce(d.resolved_ts_utc, {{ as_of() }}::timestamp))
                                                                              as hours_open_or_to_resolution,
    d.sla_breached,
    d.compensation_granted,
    h.prior_disputes_365d,
    d.is_repeat_complainer,
    -- linkage to the disputed transaction
    b.transaction_id                                                          as linked_transaction_id,
    b.n_candidates,
    b.match_score,
    case when b.product_match and b.amount_match then 'high'
         when b.amount_match                     then 'medium'
         when b.product_match                    then 'low'
         else 'none' end                                                      as link_confidence,
    struct_pack(
        ts := b.transaction_ts_utc, amount := b.amount, currency := b.currency, amount_usd := b.amount_usd,
        merchant := b.merchant_name, channel := b.channel, country := b.transaction_country_code,
        status := b.transaction_status, confirmed_fraud := b.is_fraud)        as evidence_transaction
from disputes d
join {{ ref('int_customer_profile') }} c using (customer_id)
join history h using (complaint_id)
left join best b using (complaint_id)
