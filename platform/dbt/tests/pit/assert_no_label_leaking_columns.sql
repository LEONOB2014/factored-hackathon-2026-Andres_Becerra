-- depends_on: {{ ref('feat_fraud_realtime_pit') }}
-- depends_on: {{ ref('feat_credit_eligibility_pit') }}
-- Guardrail: feature tables must never expose the legacy fraud_score (it encodes the label).
select table_name, column_name
from information_schema.columns
where table_schema in ('marts', 'exports')
  and (table_name like 'feat_%' or table_name like 'export_kumo_%')
  and column_name ilike '%fraud_score%'
