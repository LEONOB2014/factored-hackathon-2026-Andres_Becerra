-- One row per transaction. Vocabulary is normalized (México/Mexico -> MX) but values are not repaired
-- here; repairs and data-quality flags live in int_transactions_enriched so they stay auditable.
{{ stg_transactions_select(ref('typed_transactions')) }}
