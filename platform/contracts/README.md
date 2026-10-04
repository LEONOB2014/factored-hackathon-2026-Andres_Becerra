# Source contracts

What each source column **is**: type, accepted formats, key pattern, vocabulary and variant spellings, scale
baseline, personal-data class. Silver types lossless bronze against these files (the `typed_*` models), every cell
that breaks one is flagged in `audit.dq_cell_findings`, and a partition that breaks one severely is held by the
schema-drift circuit breaker. Method and results: [docs/platform/09 §C](../../docs/platform/09_data_and_model_risk_methodology.md#c-contract-driven-silver-and-cell-level-findings).

| file | role |
|---|---|
| `sources/<table>.yml` | the reviewed contract of one source table: the source of truth, changed by pull request |
| `value_classes.yml` | the value classes (formats) a contract can accept; identical to the raw forensics' classes |

Change a contract, then regenerate the dbt artefacts and rebuild (runbook §9):

```bash
cd platform/dbt
uv run python scripts/generate_silver_from_contracts.py   # typed models, profile, findings, seed
DBT_PROFILES_DIR=. uv run dbt build -s +dq_rule_summary
```

`scripts/generate_source_contracts.py` seeded these files from the forensics once; rerunning it overwrites reviewed
edits, so use it only to start a contract for a new table.

These are **source** contracts (inputs). The enforced dbt contracts of the serving models (outputs) are generated
by `platform/dbt/scripts/generate_contracts.py`.
