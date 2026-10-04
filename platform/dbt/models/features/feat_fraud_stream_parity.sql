-- Batch reference for the streaming path: the same fraud_features() macro computed over history + holdout,
-- restricted to the replayed (holdout) transactions. The stream_parity DAG compares Flink's online features
-- with this table row by row; any difference blocks a release of either side.
with events as (
    select * from {{ ref('stg_digital_events') }}
    union all by name
    select * from {{ ref('stg_digital_events_holdout') }}
)
select f.*
from ({{ fraud_features(ref('int_transactions_enriched_with_holdout'), 'events') }}) f
where f.anchor_ts >= timestamp '{{ var("stream_cutoff") }}'
