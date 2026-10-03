-- Every data-quality finding in one shape: row-level rules (dq_integrity_findings, R-rules) and cell-level
-- source-contract breaches (dq_cell_findings, C-rules). Cell findings carry lineage to the bronze record.
{{ config(materialized='view') }}
select 'row' as finding_level, rule_id, table_name, entity_id,
       null::varchar as column_name, null::varchar as issue_code,
       null::date as partition_date, null::varchar as source_file, null::bigint as record_no
from {{ ref('dq_integrity_findings') }}
union all
select 'cell', s.rule_id, f.table_name, f.entity_id, f.column_name, f.issue_code,
       f.partition_date, f.source_file, f.record_no
from {{ ref('dq_cell_findings') }} f
join (select distinct rule_id, issue_code from {{ ref('dq_cell_rule_slo') }}) s using (issue_code)
