# Intent model: held-out report

Tuned with Optuna on grouped 5-fold CV (cv macro-F1 0.7399); confidence threshold 0.73 chosen out-of-fold for 90 % precision (covers 53% of out-of-fold phrasings). MLflow run `7d620b491128481db18b4b22f99cbcd5`.

Held-out set: `eval/intent_test.yaml`, written before tuning, never used to choose parameters.

| model | n | accuracy | macro-F1 | F1 es | F1 pt | ECE | p50 ms | p95 ms |
|---|---|---|---|---|---|---|---|---|
| learned_char_ngram_lr | 132 | 0.818 | 0.820 | 0.789 | 0.849 | 0.081 | 0.287 | 0.451 |
| keyword_baseline | 132 | 0.576 | 0.606 | 0.586 | 0.621 |  | 0.086 | 0.102 |

At the threshold the learned model answers 61% of held-out phrasings itself, 96.3% of them correctly; the rest go to Claude, or to a clarifying question when no model key is configured.
