-- Holdout zone (transactions with process_date >= var('stream_cutoff')): the slice replayed through
-- Redpanda -> Flink in the streaming demo. Used only for stream/batch parity checks, never for training.
{{ stg_transactions_select(ref('typed_transactions_holdout')) }}
