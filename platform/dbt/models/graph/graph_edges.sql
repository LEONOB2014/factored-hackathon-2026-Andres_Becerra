-- Heterogeneous graph, edge table (src_type, rel, dst_type). Event edges keep their timestamp so the
-- same file feeds static GNNs (aggregate per pair) and temporal ones (TGN / temporal sampling).
-- Edges whose foreign key is semantically broken in this dataset (complaint -> product, R25;
-- digital_event -> product, R26) are deliberately NOT exported: a GNN would learn from noise.
{{ config(materialized='external', location=env_var('LATAM_LAKE_DIR', '../../data/lake') ~ '/graph/graph_edges.parquet') }}
select 'customer' as src_type, customer_id as src_id, 'owns' as rel, 'product' as dst_type, product_id as dst_id,
       cast(opening_date as timestamp) as ts, 1.0 as weight, null::boolean as label
from {{ ref('int_products_enriched') }}
union all
select 'product', product_id, 'paid_at', 'merchant', merchant_name, transaction_ts_utc, amount_usd, is_fraud
from {{ ref('fct_transaction') }}
where merchant_name is not null
union all
select 'customer', customer_id, 'transacted_in', 'country', transaction_country_code, max(transaction_ts_utc),
       count(*), bool_or(is_fraud)
from {{ ref('fct_transaction') }}
group by all
union all
select 'product', product_id, 'opened_at', 'branch', opening_branch_id, cast(opening_date as timestamp), 1.0, null
from {{ ref('stg_products') }}
union all
select 'customer', customer_id, 'contacted', 'agent', agent_id, max(interaction_ts_utc), count(*),
       bool_or(was_escalated)
from {{ ref('stg_call_center_interactions') }}
where agent_id is not null
group by all
union all
select 'customer', customer_id, 'filed', 'complaint', complaint_id, created_ts_utc, 1.0, sla_breached
from {{ ref('stg_complaints') }}
union all
select 'complaint', complaint_id, 'handled_by', 'agent', assigned_agent_id, assigned_ts_utc, 1.0, null
from {{ ref('stg_complaints') }}
where assigned_agent_id is not null
union all
select 'customer', customer_id, 'received', 'campaign', campaign_id, max(send_ts_utc), count(*), bool_or(had_conversion)
from {{ ref('stg_campaign_sends') }}
group by all
union all
select 'customer', e.customer_id, 'used_ip', 'ip', {{ pii_hash('e.ip_address') }}, max(e.event_ts_utc), count(*), null
from {{ ref('stg_digital_events') }} e
where e.customer_id is not null
  and {{ pii_hash('e.ip_address') }} in (select node_id from {{ ref('graph_nodes') }} where node_type = 'ip')
group by all
