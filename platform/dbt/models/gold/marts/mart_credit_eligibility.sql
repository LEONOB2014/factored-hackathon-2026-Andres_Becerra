-- Credit product information & eligibility: latest snapshot per customer, transparent policy rules and
-- adverse-action reason codes. Thresholds are illustrative policy parameters, not a credit policy.
{% set min_score_card = 650 %}
{% set min_score_loan = 680 %}
{% set max_payment_to_inflow = 0.40 %}
with latest as (
    select * from {{ ref('feat_credit_eligibility_pit') }}
    qualify row_number() over (partition by customer_id order by snapshot_date desc) = 1
),
risk as (
    select customer_id, max(days_past_due) as max_dpd, max(utilization) as max_card_utilization
    from {{ ref('int_products_enriched') }}
    group by 1
),
base as (
    select
        l.*,
        r.max_dpd,
        r.max_card_utilization,
        l.avg_payments_usd_3m_pit / nullif(l.avg_inflow_usd_3m_pit, 0) as payment_to_inflow_ratio,
        list_value(
            case when l.customer_status_current <> 'Active'                     then 'R01_CUSTOMER_NOT_ACTIVE' end,
            case when coalesce(r.max_dpd, 0) > 30                               then 'R02_PAST_DUE_OVER_30D' end,
            case when l.credit_score_current is null                           then 'R03_NO_SCORE' end,
            case when l.months_with_inflow_6m_pit < 3                           then 'R04_INSUFFICIENT_INCOME_HISTORY' end,
            case when l.avg_payments_usd_3m_pit / nullif(l.avg_inflow_usd_3m_pit, 0) > {{ max_payment_to_inflow }}
                                                                               then 'R05_HIGH_PAYMENT_BURDEN' end,
            case when l.nsf_declines_3m_pit >= 3                                then 'R06_REPEATED_NSF' end,
            case when l.tenure_days_pit < 180                                   then 'R07_SHORT_TENURE' end
        )                                                               as raw_reasons
    from latest l
    left join risk r using (customer_id)
)
select
    customer_id,
    snapshot_date,
    credit_score_current,
    monthly_income_usd_current,
    avg_inflow_usd_3m_pit,
    payment_to_inflow_ratio,
    max_dpd,
    max_card_utilization,
    has_credit_card_pit,
    has_loan_pit,
    list_filter(raw_reasons, x -> x is not null)                        as decline_reasons,
    len(list_filter(raw_reasons, x -> x is not null)) = 0
        and credit_score_current >= {{ min_score_card }}
        and not has_credit_card_pit                                     as eligible_credit_card,
    len(list_filter(raw_reasons, x -> x is not null)) = 0
        and credit_score_current >= {{ min_score_loan }}                as eligible_personal_loan,
    case when credit_score_current < {{ min_score_card }} then 'R08_SCORE_BELOW_CARD_CUTOFF'
         when credit_score_current < {{ min_score_loan }} then 'R09_SCORE_BELOW_LOAN_CUTOFF' end
                                                                        as score_reason
from base
