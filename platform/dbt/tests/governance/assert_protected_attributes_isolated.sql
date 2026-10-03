-- Protected and proxy attributes (gender, accent, marital status, age band) may appear only in
-- silver.int_customer_fairness_attributes, which model-risk uses to measure disparate impact.
-- depends_on: {{ ref('feat_fraud_realtime_pit') }}
-- depends_on: {{ ref('serving_customer_360') }}
-- depends_on: {{ ref('fct_interaction') }}
select c.table_schema, c.table_name, c.column_name
from information_schema.columns c
join {{ ref('protected_attributes') }} p on lower(c.column_name) = p.column_name
where c.table_schema in ('gold', 'features', 'graph', 'knowledge', 'privacy', 'serving')
