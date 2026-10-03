# 05 · dbt: should we, and how

[← 04 SCD and integrity](04_scd_adulteration_integrity.md) · [index](README.md) · next: [06 denormalized tables →](06_denormalized_tables.md)

## 5.1 Recommendation: yes, and it is already running
This project has many derived tables with business logic that regulators may ask about, plus a recurring need for tests
and history. dbt is the lowest-cost way to get versioned SQL, tests, documentation, lineage and SCD2 snapshots in one
tool. `platform/dbt/` is a working dbt-duckdb project over the Parquet files:

| what | count |
|---|---:|
| models | 42 (13 staging views, 7 intermediate, 11 marts, 5 audit, 7 exports) |
| SCD2 snapshots | 4 |
| seeds (reference data) | 3 (`country_codes`, `response_codes`, `dq_rule_slo`) |
| data tests | 86, plus 2 unit tests |
| full build on a laptop (16 GB, 10 cores) | about 85 s, 133 pass, 4 expected warnings, 0 errors |

```bash
cd platform/dbt && export DBT_PROFILES_DIR=.
uv run dbt build                 # seeds, snapshots, models, tests
uv run dbt docs generate && uv run dbt docs serve    # lineage graph + column docs
bash scripts/scd2_demo.sh        # SCD2 demo on a separate DuckDB file
```

The unit test `dispute_links_to_amount_matching_transaction` caught a real bug while this phase was being built. A null
`affected_product_id` made the whole dispute match score null, so candidate ranking became arbitrary. The same pattern
existed in the collections score: `LEAST()` ignores NULLs, so every customer scored 100. Both are fixed and commented.
Untested SQL in a bank fails silently like this.

## 5.2 Project conventions to keep

| layer | materialization | rule |
|---|---|---|
| `staging/` | view | 1:1 with a source. Rename, cast, normalize vocabulary, `row_hash`. No joins except reference seeds. |
| `intermediate/` | table | conformed facts and dimensions, repairs **with flags**, no consumer-specific logic |
| `marts/` | table (incremental in prod) | one grain per model, declared in `meta.grain`, plus `consumers` and `not_for` |
| `audit/` | table | DQ findings, SLO summary, manifests, reconciliation, change logs |
| `exports/` | external Parquet | ML and graph hand-offs. Contracts enforced because Python consumers break silently. |

Naming: `stg_`, `int_`, `mart_`, `feat_` (ML features, PIT-safe), `dq_`, `audit_`, `export_`. Column suffixes: `_pit`
(point-in-time safe), `_current` (not safe for back-testing), `_utc` / `_local`, `_usd`.

## 5.3 What to add next (in order)
1. **Model contracts and access.** Add `contract: {enforced: true}` on marts and exports, `access: public` only for
   marts, and `group` ownership: `risk`, `cx`, `marketing`, `data-platform`. That gives a dbt Mesh-ready project when
   it is split by domain.
2. **Incremental microbatch** on `process_date` for transactions, events and sends, with a 3-day `lookback`. Event
   timestamps fall after `process_date` (late arrivals, and the UTC−6 convention breaks for 8 % of contacts), so the
   lookback window must cover them.
3. **Elementary** (dbt package) for test history, anomaly monitors on volume and freshness, and Slack alerts.
   `dbt-project-evaluator` to keep the DAG healthy.
4. **dbt-expectations** for distribution tests (quantiles, mean ranges) on amounts and scores. These complement the
   hash-based reconciliation.
5. **Semantic layer (MetricFlow)** for governed metrics such as active customers, approval rate, SLA breach rate and
   fraud loss. The same definitions serve dashboards, text-to-SQL agents and regulatory reports. Agents should query
   metrics, not raw tables.
6. **Exposures** declaring each dashboard, model and agent tool that reads a mart. Impact analysis becomes a query.
7. **Slim CI**: `dbt build --select state:modified+ --defer --state prod-artifacts` on every PR, plus SQLFluff and a
   docs-coverage check.
8. **Freshness SLAs** on sources (`loaded_at_field`), wired to the orchestrator.

## 5.4 Engines and editions
- **Local / CI:** dbt-duckdb (this repo). Fast enough for the full 4.4 M-transaction dataset; ideal for synthetic
  development data.
- **Cloud:** keep SQL engine-neutral (ANSI plus a few macros) and swap the adapter: dbt-spark/databricks, dbt-trino
  (Iceberg), dbt-snowflake or dbt-bigquery. DuckDB-specific constructs used here are `ASOF JOIN`, `list()`/`struct_pack`,
  `exclude current row` and the `columns(*)` unpacking. Each needs a macro with a per-adapter implementation. The
  equivalents exist (Spark `rangeBetween`, Snowflake `ASOF JOIN`, Trino `array_agg`/`row`).
- **dbt Core vs a managed dbt platform:** Core plus Dagster is enough to start and keeps everything in your cloud
  account. A managed platform adds a hosted IDE, semantic-layer APIs and CI. Decide when more than one team writes
  models.

## 5.5 Anti-patterns to avoid
- Snapshotting heavily transformed models: snapshot staging (light) or sources. This repo snapshots light staging views.
- Using `timestamp` snapshot strategy on unreliable `updated_at` columns (R06/R07).
- Business logic in Python notebooks that feed production (move it to dbt, keep notebooks for analysis).
- One giant "wide table for everything". Marts are per consumer and per grain; the exports are the only very wide tables.
- Tests that are all `warn`. A-rules must error in prod (`dq_slo_breach_severity_a`).
