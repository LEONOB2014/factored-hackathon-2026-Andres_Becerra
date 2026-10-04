-- Historical + holdout transactions enriched with the same macro as int_transactions_enriched.
-- Exists only so the stream parity model can compute batch features for the replayed slice with the
-- full history in its windows. `_zone` tells the two apart.
with unioned as (
    select *, 'bronze' as _zone from {{ ref('stg_transactions') }}
    union all by name
    select *, 'holdout' as _zone from {{ ref('stg_transactions_holdout') }}
)
select e.*, u._zone
from ({{ enrich_transactions('unioned') }}) e
join unioned u using (transaction_id)
