# Phase 3 evidence: contract-driven silver and the drift circuit breaker

The tables behind [09 §C.4](../../09_data_and_model_risk_methodology.md#c4-results-2026-10-03). Each one is the
output of a committed script in `platform/dbt/scripts/verify/`, run on 2026-10-03 against the full lossless lake
(23.5 M main records). No values from the data are stored here: relation and column names, counts and verdicts.

| file | question | script |
|---|---|---|
| [`typed_parity.csv`](typed_parity.csv) | do the typed silver models reproduce the typed bronze they replace? | `typed_parity.py` |
| [`determinism_baseline_vs_baseline.csv`](determinism_baseline_vs_baseline.csv) | how much do two builds of the **same** commit differ? (the noise floor) | `compare_lakehouses.py` |
| [`parity_baseline_vs_phase3.csv`](parity_baseline_vs_phase3.csv) | what changes downstream when silver reads lossless bronze? | `compare_lakehouses.py --noise` |
| [`cell_findings_real_data.csv`](cell_findings_real_data.csv) | which contract breaches does the real data have? | `breaker_outcome.py --findings` |
| [`breaker_real_data.csv`](breaker_real_data.csv) | does the circuit breaker hold anything in the real data? | `breaker_outcome.py` |
| [`breaker_positive_control.csv`](breaker_positive_control.csv) | does it hold exactly the partitions a producer change would break? | `mutated_lake.py`, `breaker_outcome.py` |

## Results

**Typed parity.** 15 models, 23,413,140 rows: identical row counts, identical column types and identical
order-independent hashes of every value (`values_identical` is true everywhere).

**Lakehouse parity.** The baseline is commit `acac8e1` (develop before phase 3, silver read typed bronze); phase 3 is
`091a307`. Two builds of the baseline differ in 18 of 84 relations by themselves: surrogate keys hashed with the
snapshot run time, floating-point sums aggregated in parallel, list order, `mode()` ties. Against phase 3, 66 of 84
shared relations are identical and 15 of the 18 differences are inside that noise (`explained_by_noise`). The other
three:

* `audit.audit_partition_manifest`: intended. The partition digests are now over each record's landed bytes
  (`_record_sha256`) instead of the typed row hash; row counts are identical.
* `audit.dq_rule_summary`: intended. It now also carries the cell rules C01–C10 per table (26 → 156 rows).
* `gold.mart_customer_360.main_digital_channel`: noise not seen in this baseline pair. All 2,045 differing customers
  have two or more channels tied for the most events, and both builds picked one of the tied channels (`mode()`
  has no tie-break). Query used (both builds attached under their file names):

  ```sql
  with d as (select a.customer_id, a.main_digital_channel ca, b.main_digital_channel cb
             from baseline_a.gold.mart_customer_360 a join phase3.gold.mart_customer_360 b using (customer_id)
             where a.main_digital_channel is distinct from b.main_digital_channel),
       n as (select customer_id, channel, count(*) k from phase3.silver.stg_digital_events
             where customer_id in (select customer_id from d) group by all),
       m as (select customer_id, max(k) mk from n group by 1)
  select count(*) total, count(*) filter (where na.k = m.mk and nb.k = m.mk) both_tied_modes   -- 2045, 2045
  from d join m using (customer_id)
  left join n na on na.customer_id = d.customer_id and na.channel = d.ca
  left join n nb on nb.customer_id = d.customer_id and nb.channel = d.cb;
  ```

**Real data.** Three cell rules have findings, all known from the raw forensics (09 §A) and inside their SLO:
`Mexico` spelled without the accent in `digital_events` (6.65 %) and `transactions` (0.92 %), and `nan` rendered into
38,142 campaign subjects (2.25 %). No partition is held; 32 `campaign_sends` partitions get severity-B empty-share
reports (`subject`, `was_opened`).

**Positive control.** Six producer changes written into copies of real partitions (`mutated_lake.py`, the real lake
untouched): the five severe ones are held by the intended check with 0 rows reaching staging or gold while the typed
model keeps them all; the rare new category (5 rows) is reported and its partition flows through. Nothing else is
held. The review each hold raises is covered by `platform/libs/tests/test_drift_holds.py`.

## Reproduce
From a checkout with the lake in `data/` (about 15 GB free; each build is about 4.4 GB, delete as you go):

```bash
cd platform
uv run python dbt/scripts/verify/typed_parity.py --out ../docs/platform/evidence/phase3/typed_parity.csv

# build each lakehouse: DBT_PROFILES_DIR=. LATAM_DUCKDB_PATH=<db> uv run dbt build  (from platform/dbt)
#   baseline_a.duckdb, baseline_b.duckdb  from a checkout of acac8e1
#   phase3.duckdb                         from this commit
#   mutated.duckdb                        from this commit with LATAM_LAKE_DIR=<scratch lake> (absolute path)
cd dbt
uv run python scripts/verify/compare_lakehouses.py baseline_a.duckdb baseline_b.duckdb \
    --out ../../docs/platform/evidence/phase3/determinism_baseline_vs_baseline.csv
uv run python scripts/verify/compare_lakehouses.py baseline_a.duckdb phase3.duckdb \
    --noise ../../docs/platform/evidence/phase3/determinism_baseline_vs_baseline.csv \
    --out ../../docs/platform/evidence/phase3/parity_baseline_vs_phase3.csv
uv run python scripts/verify/breaker_outcome.py phase3.duckdb --out ../../docs/platform/evidence/phase3/breaker_real_data.csv \
    --findings ../../docs/platform/evidence/phase3/cell_findings_real_data.csv
uv run python scripts/verify/mutated_lake.py --out ../../data/tmp/lake_mutated
uv run python scripts/verify/breaker_outcome.py mutated.duckdb --mutations ../../data/tmp/lake_mutated/mutations.json \
    --out ../../docs/platform/evidence/phase3/breaker_positive_control.csv
```

`compare_lakehouses.py` must run from `platform/dbt` (views store paths relative to it), and every build must come
from a checkout in the same environment. Run `typed_parity.py` before typed bronze is archived, or it reads the
archive. Local dbt builds rewrite the derived Parquet in `data/lake/{graph,knowledge,features}`; finish with a build
of the commit the stack runs.
