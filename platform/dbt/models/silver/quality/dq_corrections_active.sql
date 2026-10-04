-- Cell corrections in force: approved through the four-eyes flow (dq_correction_review), applied up to
-- var('corrections_as_of') (default: everything) and not reverted by then. The latest correction of a cell wins.
-- The typed models overlay these values on lossless bronze; bronze itself never changes, so rebuilding with an
-- earlier corrections_as_of reproduces silver and gold as they were at that point of the log.
{% set as_of = var('corrections_as_of', none) %}
with log as (
    select * from {{ source('corrections', 'applied') }}
    where proposal_id is not null
    {% if as_of %}and applied_at <= timestamp '{{ as_of }}'{% endif %}
),
reverted as (
    select distinct reverts_proposal_id as proposal_id from log where kind = 'revert' and reverts_proposal_id is not null
)
select
    zone,
    table_name,
    source_file,
    record_no,
    column_name,
    arg_max(new_value, (applied_at, proposal_id))   as new_value,
    arg_max(old_value, (applied_at, proposal_id))   as old_value,
    arg_max(proposal_id, (applied_at, proposal_id)) as proposal_id,
    max(applied_at)                                 as applied_at
from log
where kind in ('pattern', 'cells')
  and proposal_id not in (select proposal_id from reverted)
group by zone, table_name, source_file, record_no, column_name
