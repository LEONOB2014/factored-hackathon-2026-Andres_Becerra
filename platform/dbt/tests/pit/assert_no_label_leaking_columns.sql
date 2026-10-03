-- depends_on: {{ ref('feat_fraud_realtime_pit') }}
-- depends_on: {{ ref('feat_credit_eligibility_pit') }}
-- Guardrail: feature tables must never expose the legacy fraud_score (it encodes the label).
select table_name, column_name
from information_schema.columns
where table_schema in ('features', 'graph', 'serving')
  and column_name ilike '%fraud_score%'
