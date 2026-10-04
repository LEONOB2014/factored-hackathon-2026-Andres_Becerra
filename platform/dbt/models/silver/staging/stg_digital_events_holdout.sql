-- Holdout zone (digital_events with process_date >= var('stream_cutoff')): the slice replayed through
-- Redpanda -> Flink in the streaming demo. Used only for stream/batch parity checks, never for training.
{{ stg_digital_events_select(ref('typed_digital_events_holdout')) }}
