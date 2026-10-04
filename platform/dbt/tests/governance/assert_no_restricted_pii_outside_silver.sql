-- Data minimisation guard (platform/policies/data_classification.yaml): direct identifiers and free text
-- may exist only in landing, bronze and silver. Any restricted column in a downstream zone fails the build
-- and, in Airflow, blocks publication (regulatory trigger `pii_outside_pii_zone`).
-- depends_on: {{ ref('serving_customer_360') }}
-- depends_on: {{ ref('graph_nodes') }}
-- depends_on: {{ ref('kb_entity_docs') }}
-- depends_on: {{ ref('fct_interaction') }}
-- depends_on: {{ ref('dq_rule_summary') }}
select c.table_schema, c.table_name, c.column_name, r.pii_type
from information_schema.columns c
join {{ ref('restricted_pii_columns') }} r on lower(c.column_name) = r.column_name
where c.table_schema in ('gold', 'features', 'graph', 'knowledge', 'privacy', 'serving', 'audit')
