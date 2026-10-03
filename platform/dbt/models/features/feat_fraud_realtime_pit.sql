-- Real-time fraud features: one row per transaction, every feature computed only from events strictly
-- available at authorization time (prior rows of the same customer; same-timestamp peers count as prior,
-- matching what a streaming aggregator would have seen). The same definitions are written as Flink SQL in
-- the report (ch. 06) so offline training and online scoring share one contract.
-- fraud_score is deliberately absent: it deterministically encodes the label (notebook 09).

{{ fraud_features(ref('int_transactions_enriched'), ref('stg_digital_events')) }}
