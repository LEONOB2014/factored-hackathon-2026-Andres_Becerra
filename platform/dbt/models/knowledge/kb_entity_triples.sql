-- Knowledge-graph triples with provenance, for a property-graph store (Neo4j, Memgraph, Spanner Graph,
-- Neptune) behind GraphRAG. Aggregated relations only (no per-transaction triples): the KG answers
-- "who/what is connected", the warehouse answers "how much/when" through governed SQL tools.
{{ config(materialized='external', location=env_var('LATAM_LAKE_DIR', '../../data/lake') ~ '/knowledge/kb_entity_triples.parquet') }}
select
    src_type || ':' || src_id                          as subject,
    rel                                                as predicate,
    dst_type || ':' || dst_id                          as object,
    max(ts)                                            as last_seen_ts,
    count(*)                                           as n_events,
    'graph_edges'                               as provenance
from {{ ref('graph_edges') }}
where rel <> 'paid_at'
group by all
union all
select 'product:' || product_id, 'paid_at', 'merchant:' || merchant_name, max(transaction_ts_utc), count(*),
       'int_transactions_enriched'
from {{ ref('int_transactions_enriched') }}
where merchant_name is not null
group by all
