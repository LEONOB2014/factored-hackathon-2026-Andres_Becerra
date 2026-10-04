# Reproducible gold: evidence

A compliance rebuild has to give the same bytes as the original build. Before `fix/reproducible-gold`, two builds
of the same commit differed in up to 25 of 108 relations. These tables are the outputs of
`platform/dbt/scripts/verify/compare_lakehouses.py`, run on 2026-10-04 against the full lake, each build compared
through its fingerprint (per relation: row count, a sum of row hashes, a sum of hashes per column). They hold
relation and column names, counts and verdicts only.

| file | builds compared | identical | different |
|---|---|---|---|
| [`reproducible_vs_reproducible.csv`](reproducible_vs_reproducible.csv) | two builds of this branch | **108 of 108** | 0 |
| [`develop_vs_develop.csv`](develop_vs_develop.csv) | two builds of `develop` (`dbb8c4b`), the noise floor | 83 | 25 |
| [`develop_vs_reproducible.csv`](develop_vs_reproducible.csv) | `develop` vs this branch, `--noise develop_vs_develop.csv` | 85 | 23, **all inside the noise** |

**What was order-dependent, and the fix** (`platform/dbt/macros/determinism.sql`):

| cause | where | fix |
|---|---|---|
| surrogate keys hashed with the snapshot run time | `dim_customer`, `dim_product` → `fct_transaction` | `md5(id \|\| version_no)` |
| DOUBLE sums aggregated in parallel | monthly grid, AML, collections, credit, customer 360, privacy, fraud state, federated graph | `exact_sum` / `exact_avg` / `exact_stddev`: DECIMAL(38, 9) sums, cast back to DOUBLE |
| `list()` / `map(list())` without order | payment inquiry, card support, fraud state | `ORDER BY` inside the aggregate |
| `mode()`, `any_value()` | customer 360, merchant dimension, graph nodes, digital sessions | `stable_mode()`; `arg_min(x, (ts, id))` |
| ties in `arg_max(x, ts)`, ROWS windows, `lag`, `lead`, `row_number` | fraud features, CX journey, recent transactions, disputes, DP bounding | tie-break by the row id |

`develop_vs_reproducible.csv` shows that every column the fix changes was already varying between two builds of
`develop`: the fix changes no value that was stable before, it pins the ones that were not. One-time effect to know:
`customer_sk` and `product_sk` take new values (breaking for anything that stored them).

**Guard.** `platform/libs/tests/test_dbt_determinism.py` (CI) fails on any new `mode()`, `any_value()`, unordered
`list()`/`string_agg()` or key hashed with snapshot time. Floating-point sums cannot be detected statically; rerun
the two-build check after changing aggregates:

```bash
cd platform/dbt
DBT_PROFILES_DIR=<profile with memory_limit 4GB> LATAM_DUCKDB_PATH=/tmp/a.duckdb uv run dbt build
uv run python scripts/verify/compare_lakehouses.py --fingerprint /tmp/a.duckdb --out /tmp/a.json   # then delete a.duckdb
# repeat as b, then:
uv run python scripts/verify/compare_lakehouses.py /tmp/a.json /tmp/b.json --out diff.csv          # expect 0 different
```

Builds used `LATAM_LAKE_DIR` pointing at a shadow lake (symlinks to the real zones, own output folders), so the
shared `data/lake/{graph,knowledge,features}` files were not rewritten, and a profile with DuckDB memory 4 GB and
spill 6 GB, so a 16 GB laptop running the Docker stack does not swap.
