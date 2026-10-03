-- GraphRAG corpus: one short, factual, PII-free document per entity, generated deterministically from the
-- marts (no LLM involved, so nothing is hallucinated at indexing time). community_key pre-groups entities
-- for hierarchical community summaries (Microsoft GraphRAG / LightRAG style). Customers are referenced by
-- token only; re-identification happens behind an authorization check, never inside the index.
{{ config(materialized='external', location=env_var('LATAM_LAKE_DIR', '../../data/lake') ~ '/knowledge/kb_entity_docs.parquet') }}
select
    'customer:' || left(document_token, 16)                        as doc_id,
    'customer'                                                      as entity_type,
    customer_id                                                     as entity_id,
    country_code || '|' || segment                                  as community_key,
    format('Customer {} ({} segment, {}), status {}, tenure {} days. Holds {} products ({}). '
           || 'Last 90 days: {} transactions, inflow {} USD, outflow {} USD, decline rate {}. '
           || 'Digital: {} logins in 90 days, main channel {}. Service: {} contacts in 90 days, last reason {}, '
           || '{} open cases, {} complaints in 365 days ({} SLA breaches). Data-quality notes: {} products dated before registration.',
           left(document_token, 16), segment, country_code, customer_status, tenure_days,
           n_products, array_to_string(product_types, ', '),
           tx_count_90d, round(inflow_usd_90d, 0), round(outflow_usd_90d, 0), coalesce(round(decline_rate_90d, 3), 0),
           logins_90d, coalesce(main_digital_channel, 'none'), contacts_90d, coalesce(last_contact_reason, 'none'),
           open_cases, complaints_365d, sla_breaches_365d, dq_products_before_registration) as text,
    current_timestamp                                               as generated_at
from {{ ref('mart_customer_360') }}
union all
select
    'complaint:' || complaint_id, 'complaint', complaint_id, category || '|' || priority,
    format('Complaint {} ({}, {}/{}) received via {} on {}, priority {}, status {}. Claimed {} {}. '
           || 'SLA breached: {}. Resolution: {}',
           complaint_id, case_type, category, coalesce(subcategory, 'n/a'), reception_channel,
           cast(created_ts_utc as date), priority, status, coalesce(cast(claimed_amount as varchar), 'no amount'),
           coalesce(claimed_currency, ''), sla_breached, coalesce(resolution, 'pending')),
    current_timestamp
from {{ ref('stg_complaints') }}
union all
select
    'agent:' || agent_id, 'agent', agent_id, agent_type || '|' || experience_level,
    format('Agent {} ({}, {} experience, specialty {}), shift {}, average CSAT {}, about {} interactions per month.',
           agent_id, agent_type, experience_level, coalesce(specialty, 'general'), work_shift,
           round(avg_csat, 2), total_monthly_interactions),
    current_timestamp
from {{ ref('stg_service_agents') }}
union all
select
    'campaign:' || campaign_id, 'campaign', campaign_id, campaign_objective,
    format('Campaign {} "{}": {} via {}, promotes {}, targets segment {} in {}, runs {} to {}, status {}.',
           campaign_id, campaign_name, campaign_objective, campaign_type, coalesce(promoted_product, 'no product'),
           coalesce(target_segment, 'all'), coalesce(target_country, 'all countries'), start_date, end_date,
           campaign_status),
    current_timestamp
from {{ ref('stg_marketing_campaigns') }}
