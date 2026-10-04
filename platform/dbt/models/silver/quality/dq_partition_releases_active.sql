-- Partitions released from a schema-drift hold through the four-eyes flow (kind 'release' in the correction log),
-- applied up to var('corrections_as_of') and not reverted by then.
{% set as_of = var('corrections_as_of', none) %}
with log as (
    select * from {{ source('corrections', 'applied') }}
    where proposal_id is not null
    {% if as_of %}and applied_at <= timestamp '{{ as_of }}'{% endif %}
)
select distinct table_name, partition_date, proposal_id, approved_by, applied_at
from log
where kind = 'release'
  and proposal_id not in (select reverts_proposal_id from log where kind = 'revert' and reverts_proposal_id is not null)
