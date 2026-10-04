# Phase 4 evidence: four-eyes correction and restore

The run behind [09 §D](../../09_data_and_model_risk_methodology.md#d-audited-correction-and-restore), produced by
`platform/dbt/scripts/verify/corrections_e2e.py` on 2026-10-04 against the full lossless lake. Nothing in the real
lake was modified: the script works on a scratch lake (symlinks to the lossless zones, one mutated partition from
`mutated_lake.py` so that partitions are held, its own correction log). Corrections go through
`latam_platform.dq_corrections` exactly as the `dq_correction_review` DAG calls it: staged as `steward`, applied as
`approver`.

| file | what it shows |
|---|---|
| [`corrections_e2e.json`](corrections_e2e.json) | the measures at each step (below) |
| [`base_vs_corrected.csv`](base_vs_corrected.csv) | which relations the corrections changed, and which columns |
| [`base_vs_reverted.csv`](base_vs_reverted.csv) | after reverting everything: identical to the uncorrected build |
| [`corrected_vs_as_of.csv`](corrected_vs_as_of.csv) | a rebuild as of the moment before the reverts: identical to the corrected build |

## The corrections applied
| proposal | kind | entries | findings it resolves |
|---|---|---|---|
| `e2e-mexico-tx` | pattern `transactions.transaction_country`: `Mexico` → `México` | 40,515 cells | 40,515 V2 |
| `e2e-mexico-de` | pattern `digital_events.ip_country`: `Mexico` → `México` | 1,038,174 cells | 1,038,174 V2 |
| `e2e-nan-subject` | pattern `campaign_sends.subject`: the most frequent subject with a rendered `nan` → empty | 38,142 cells | 38,142 P |
| `e2e-one-cell` | cells: one `transaction_city` | 1 cell | — (a correction of a valid value) |
| `e2e-release` | release of a held `digital_events` partition | 1 | — |

Each applied file is read-only (`read_only: true`); the staged files are removed on apply.

## Results
| measure | uncorrected | corrected | all reverted | as of before the reverts |
|---|---|---|---|---|
| cell findings | 1,126,808 | 1,126,808 | 1,126,808 | 1,126,808 |
| findings marked corrected | 0 | **1,116,831** | 0 | 1,116,831 |
| C04 rate, transactions / digital events | 0.912 % / 6.642 % | **0 / 0** | 0.912 % / 6.642 % | 0 / 0 |
| C06 rate, campaign sends | 2.247 % | **0** | 2.247 % | 0 |
| held partitions | 5 | **4** | 5 | 4 |
| typed transactions still spelled `Mexico` | 39,356 | **0** | 39,356 | 0 |
| typed transaction rows carrying a correction | 0 | 39,357 | 0 | 39,357 |

* **Findings are never deleted.** They record what the source sent; a corrected one shows its
  `correction_proposal_id` and `corrected_value`, and the gate stops counting it.
* **Restore is exact.** After one revert of all five proposals, the build equals the uncorrected one on all 109
  relations (`base_vs_reverted.csv`).
* **Rebuild as of any point.** `corrections_as_of` set to the moment before the reverts reproduces the corrected
  build on all 109 relations (`corrected_vs_as_of.csv`).
* **Gold changes only where expected** (`base_vs_corrected.csv`): `transaction_city` in the transaction fact (the
  one-cell correction), and the digital-event consumers (sessions, logins, graph, knowledge, the fraud login
  features) because the released partition flows again. The `Mexico` spellings change nothing in gold, since both
  already mapped to `MX`; the `nan` subject is not carried into gold.

The builds use the reproducible models of `fix/reproducible-gold`; without them, "identical" would be blurred by build
noise. The review DAG itself (human approval in Airflow, the ledger events and the four-eyes refusal) is covered by
`platform/libs/tests/test_dq_corrections.py`, the DAG integrity tests and the live demonstration (runbook §11).

## Reproduce
```bash
cd platform
uv run python dbt/scripts/verify/corrections_e2e.py --scratch ../data/tmp/verify/e2e \
    --profiles <dir with a bounded profiles.yml> --out ../docs/platform/evidence/phase4
```
About 20 minutes and 5 GB of free disk (one build at a time).
