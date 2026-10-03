-- Row-level data-quality findings in long format (rule_id, entity). This table is the audit trail:
-- every flagged record can be listed, routed to an owner and re-checked after a fix.
-- R08/R09 are v2 definitions (credit cards and loans legitimately carry limits and days past due).
{% set tx = ref('int_transactions_enriched') %}
{% set pr = ref('int_products_enriched') %}
{% set cu = ref('int_customer_profile') %}
{% set rules_tx = [('R01', 'dq_r01_before_product_open'), ('R03', 'dq_r03_approved_without_code'),
                   ('R04', 'dq_r04_currency_mismatch'), ('R10', 'dq_r10_branch_without_id'),
                   ('R17', 'dq_r17_mx_usd_label'), ('R18', 'dq_r18_amount_usd_imputed'),
                   ('R19', 'dq_r19_no_coordinates')] %}
{% set rules_pr = [('R02', 'dq_r02_before_customer_registration'), ('R07', 'dq_r07_future_last_updated'),
                   ('R08', 'dq_r08_limit_on_non_credit'), ('R09', 'dq_r09_dpd_on_non_credit'),
                   ('R22', 'dq_r22_active_expired_card')] %}
{% for rule, col in rules_tx %}
select '{{ rule }}' as rule_id, 'transactions' as table_name, transaction_id as entity_id from {{ tx }} where {{ col }}
union all
{% endfor %}
{% for rule, col in rules_pr %}
select '{{ rule }}', 'products', product_id from {{ pr }} where {{ col }}
union all
{% endfor %}
select 'R05', 'customers', customer_id from {{ cu }} where dq_r05_minor_at_registration
union all
select 'R06', 'customers', customer_id from {{ cu }} where dq_r06_future_last_updated
union all
select 'R11', 'complaints', complaint_id from {{ ref('stg_complaints') }}
 where status in ('Resolved', 'Closed') and resolved_ts_utc is null
union all
select 'R12', 'complaints', complaint_id from {{ ref('stg_complaints') }}
 where claimed_amount is not null and claimed_currency is null
union all
select 'R13', 'complaints', complaint_id from {{ ref('stg_complaints') }}
 where sla_breached and resolution_days <= 5
union all
select 'R15', 'call_center_interactions', interaction_id from {{ ref('stg_call_center_interactions') }}
 where cast(interaction_ts_utc - interval 6 hour as date) <> process_date
union all
select 'R16', 'complaints', complaint_id from {{ ref('stg_complaints') }}
 where cast(created_ts_utc - interval 6 hour as date) <> process_date
union all
select 'R20', 'digital_events', event_id from {{ ref('stg_digital_events') }} where customer_id is null
union all
select 'R21', 'campaign_sends', s.send_id from {{ ref('stg_campaign_sends') }} s
  join {{ ref('stg_customers') }} c using (customer_id) where not c.accepts_marketing
union all
select 'R23', 'customers', c.customer_id from {{ ref('stg_customers') }} c
 where not exists (select 1 from {{ ref('stg_branches') }} b where b.branch_id = c.registration_branch_id)
union all
select 'R24', 'service_agents', a.agent_id from {{ ref('stg_service_agents') }} a
 where a.assigned_branch_id is not null
   and not exists (select 1 from {{ ref('stg_branches') }} b where b.branch_id = a.assigned_branch_id)
union all
-- semantic integrity: the FK resolves, but to someone else's record
select 'R25', 'complaints', k.complaint_id from {{ ref('stg_complaints') }} k
  join {{ ref('stg_products') }} p on p.product_id = k.affected_product_id
 where p.customer_id <> k.customer_id
union all
select 'R26', 'digital_events', e.event_id from {{ ref('stg_digital_events') }} e
  join {{ ref('stg_products') }} p on p.product_id = e.product_id
 where p.customer_id <> e.customer_id
union all
select 'R27', 'call_transcripts', transcript_id from {{ ref('stg_call_transcripts') }} where has_unrendered_placeholder
