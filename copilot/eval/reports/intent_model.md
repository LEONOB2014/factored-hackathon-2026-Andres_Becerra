# Intent model: held-out report

Tuned with Optuna on grouped 5-fold CV (cv macro-F1 0.7595); confidence threshold 0.77 chosen out-of-fold for 90 % precision (covers 64% of out-of-fold phrasings). MLflow run `b5ac75aee5ce452785540f9baea4c205`.

Held-out set: `eval/intent_test.yaml`, written before tuning, never used to choose parameters.

| model | n | accuracy | macro-F1 | F1 es | F1 pt | ECE | p50 ms | p95 ms |
|---|---|---|---|---|---|---|---|---|
| learned_char_ngram_lr | 124 | 0.806 | 0.808 | 0.758 | 0.855 | 0.073 | 0.275 | 0.383 |
| keyword_baseline | 124 | 0.613 | 0.652 | 0.631 | 0.668 |  | 0.083 | 0.099 |

At the threshold the learned model answers 63% of held-out phrasings itself, 94.9% of them correctly; the rest go to Claude, or to a clarifying question when no model key is configured.
