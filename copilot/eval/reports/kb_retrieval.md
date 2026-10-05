# Knowledge-base retrieval: held-out comparison

28 ES/PT questions over English documents (`eval/kb_questions.yaml`); thresholds chosen on the dev split, metrics on the test split. Governance violations count any returned chunk of a document outside the active set (retired, superseded, draft or expired).

| retriever | threshold | hit@1 | hit@3 | mrr | answerable_kept | unanswerable_rejected | governance_violations | graph_expanded_hits | latency_ms_p50 | latency_ms_p95 |
|---|---|---|---|---|---|---|---|---|---|---|
| bundled | 0.7929 | 0.75 | 0.938 | 0.833 | 0.938 | 0.0 | 0 | 0 | 10.9 | 150.7 |
| pgvector | 0.7929 | 0.75 | 0.938 | 0.833 | 0.938 | 0.0 | 0 | 0 | 14.8 | 17.0 |
| graph | 0.9028 | 0.688 | 0.938 | 0.802 | 0.875 | 0.6 | 0 | 9 | 24.3 | 38.7 |
| hybrid(pgvector+graph) | 0.0327 | 0.75 | 0.938 | 0.833 | 0.938 | 0.0 | 0 | 21 | 38.2 | 43.2 |
