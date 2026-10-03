-- Heterogeneous graph, node table (one row per node). node_idx is a dense 0-based index per node_type,
-- which is what PyTorch Geometric HeteroData / DGL heterographs expect. Features are a JSON object so all
-- node types fit one file; loaders expand them per type. Protected attributes are excluded by design.
{{ config(materialized='external', location='../../data/exports/graph_nodes.parquet') }}
with nodes as (
    select 'customer' as node_type, customer_id as node_id, cast(registration_date as timestamp) as created_ts,
           to_json(struct_pack(segment, country_code, customer_status, credit_score, tenure_days,
                               monthly_income_usd)) as features
    from {{ ref('int_customer_profile') }}
    union all
    select 'product', product_id, cast(opening_date as timestamp),
           to_json(struct_pack(product_type, product_family, currency, product_status, balance_usd,
                               credit_limit_usd, interest_rate, days_past_due))
    from {{ ref('int_products_enriched') }}
    union all
    select 'merchant', merchant_name, null,
           to_json(struct_pack(category := any_value(transaction_category), n_tx := count(*)))
    from {{ ref('int_transactions_enriched') }}
    where merchant_name is not null
    group by merchant_name
    union all
    select 'branch', branch_id, cast(branch_opening_date as timestamp),
           to_json(struct_pack(branch_type, country_code, geographic_zone, atm_count, latitude, longitude))
    from {{ ref('stg_branches') }}
    union all
    select 'agent', agent_id, cast(hire_date as timestamp),
           to_json(struct_pack(agent_type, experience_level, specialty, avg_csat))
    from {{ ref('stg_service_agents') }}
    union all
    select 'campaign', campaign_id, cast(start_date as timestamp),
           to_json(struct_pack(campaign_type, campaign_objective, promoted_product, budget))
    from {{ ref('stg_marketing_campaigns') }}
    union all
    select 'country', iso2, null, to_json(struct_pack(home_currency, is_bank_market))
    from (select distinct iso2, home_currency, is_bank_market from {{ ref('country_codes') }})
    union all
    select 'complaint', complaint_id, created_ts_utc,
           to_json(struct_pack(case_type, category, subcategory, priority, status, sla_breached))
    from {{ ref('stg_complaints') }}
    union all
    -- IP addresses seen for >= 2 distinct customers are the only ones that can create shared-device links
    select 'ip', ip_address, min(event_ts_utc), to_json(struct_pack(n_customers := count(distinct customer_id)))
    from {{ ref('stg_digital_events') }}
    where customer_id is not null
    group by ip_address
    having count(distinct customer_id) >= 2
)
select node_type, node_id,
       (dense_rank() over (partition by node_type order by node_id) - 1) as node_idx,
       created_ts, features
from nodes
