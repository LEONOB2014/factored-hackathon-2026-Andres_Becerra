# Factored Datathon 2026: Data Engineering Specification

> **Status (2026-10-05): design-time specification.** Written at the start of the hackathon and kept unchanged as
> the record of intent; the project is now **BETA AID** (Banking Evolutionary Transformation and AI Deployment).
> What was built is [`platform/`](../platform/README.md):
> - a DuckDB lakehouse with lossless bronze and object-locked manifests;
> - dbt-duckdb silver, gold, multi-grain aggregates and serving, with BigQuery targets ([ADR-006](../platform/adr/ADR-006.md));
> - Airflow 3 with Cosmos, one DAG per country scope ([ADR-020](../platform/adr/ADR-020.md));
> - Flink streaming features in parity with dbt ([ADR-005](../platform/adr/ADR-005.md));
> - dbt contracts and governance gates in place of Great Expectations.

## 1. Overview
This specification governs the entire data engineering pipeline for the Factored AI & Data Hackathon 2026 project. The pipeline supports an AI-first banking customer service system for LATAM (Mexico, Colombia, Argentina).

## 2. Dataset Context
- **Total Volume**: 19M rows across 13 tables.
- **Date Range**: June 2023 - June 2026.
- **Languages**: Spanish (MX, CO, AR accents) + Portuguese.
- **Currencies**: MXN, COP, ARS, USD.
- **Data Quality Challenges**: 2% duplicates, 5% nulls, late arrivals, schema evolution.

### Tables
**Dimension Tables**:
- `customers` (150K)
- `products` (400K)
- `branches` (350)
- `service_agents` (1200)
- `marketing_campaigns` (200)

**Fact Tables**:
- `transactions` (5M)
- `call_center_interactions` (800K)
- `call_transcripts` (200K)
- `satisfaction_surveys` (250K)
- `digital_events` (10M)
- `complaints` (80K)
- `campaign_sends` (2M)

**Reference Tables**:
- `daily_exchange_rates` (3000)

## 3. Lakehouse Architecture
We follow a Medallion architecture using Delta Lake format (or Apache Hudi/Iceberg) over Google Cloud Storage (GCS) / S3:
- **Bronze (Raw)**: Raw data ingested from source systems (CSV/JSON/DB dumps). Appended as-is. Minimal schema validation to avoid data loss.
- **Silver (Cleaned)**: Deduplicated, standardized, parsed, and typed data. Null handling and domain constraint validations are applied.
- **Gold (Business Marts)**: Aggregated, business-level views optimized for reporting and ML serving (e.g., Customer 360, Dispute Timeline).

## 4. Ingestion Pipeline
**Flow**: CSV → GCS (Bronze) → PostgreSQL Raw (for operational lookup) / Spark Bronze Layer.

### Schema Contracts
We use Pandera / Great Expectations for initial schema validation before ingestion into the Bronze layer.

```python
import pandera as pa
from pandera.typing import Series

class CustomerSchema(pa.SchemaModel):
    customer_id: Series[str] = pa.Field(unique=True, nullable=False)
    country_code: Series[str] = pa.Field(isin=["MX", "CO", "AR"], nullable=False)
    created_at: Series[pa.DateTime]
    # ...
```

## 5. Spark ETL Jobs

### Bronze → Silver
**Deduplication Strategy**: Use window functions to pick the latest record in case of late arrivals or duplicates.

```python
from pyspark.sql.window import Window
from pyspark.sql.functions import col, row_number, coalesce, lit

def clean_transactions(spark, bronze_df):
    windowSpec = Window.partitionBy("transaction_id").orderBy(col("ingested_at").desc())

    silver_df = bronze_df \
        .withColumn("row_num", row_number().over(windowSpec)) \
        .filter(col("row_num") == 1) \
        .drop("row_num") \
        .withColumn("amount", col("amount").cast("decimal(18,2)")) \
        .withColumn("currency", coalesce(col("currency"), lit("USD"))) # Impute default

    return silver_df
```

### Silver → Gold
Aggregating facts to create a customer 360 view.

```python
def build_customer_360(spark, customers_df, transactions_df, interactions_df):
    # Customer-level aggregations
    tx_agg = transactions_df.groupBy("customer_id").agg(...)
    return customers_df.join(tx_agg, on="customer_id", how="left")
```

## 6. dbt Project

### Structure
```
dbt_project/
├── models/
│   ├── staging/      # 1:1 with Silver tables (rename, cast)
│   ├── intermediate/ # Complex joins (customer_products, transaction_enriched, dispute_timeline)
│   └── marts/        # Business aggregates (customer_360, dispute_analytics, agent_performance)
├── tests/
└── dbt_project.yml
```

### Staging Pattern (e.g., `stg_transactions.sql`)
```sql
WITH source AS (
    SELECT * FROM {{ source('silver', 'transactions') }}
)
SELECT
    transaction_id,
    customer_id,
    product_id,
    CAST(amount AS DECIMAL(18,2)) AS amount,
    currency,
    DATE(transaction_date) AS transaction_date
FROM source
```

### Marts Pattern (e.g., `dispute_timeline.sql`)
```sql
WITH interactions AS (
    SELECT * FROM {{ ref('int_interaction_full') }}
),
complaints AS (
    SELECT * FROM {{ ref('stg_complaints') }}
)
SELECT
    c.complaint_id,
    c.customer_id,
    c.transaction_id,
    c.status,
    i.interaction_id,
    i.transcript_summary
FROM complaints c
LEFT JOIN interactions i ON c.interaction_id = i.interaction_id
ORDER BY c.created_at ASC
```

### Testing
Use built-in dbt tests in `schema.yml`:
```yaml
models:
  - name: stg_transactions
    columns:
      - name: transaction_id
        tests:
          - unique
          - not_null
      - name: currency
        tests:
          - accepted_values:
              values: ['MXN', 'COP', 'ARS', 'USD']
```

## 7. Data Quality Framework
- **Tools**: Great Expectations
- **Metrics Tracked**: Null percentage per column, freshness of late-arriving data, duplicate counts, cross-table referential integrity (e.g., every `transaction_id` in `complaints` exists in `transactions`).
- **Alerting**: Failure logs sent via Slack/Email, managed by Airflow callbacks.

## 8. Orchestration
Apache Airflow DAGs control pipeline execution.
- **Daily Batch (`dag_daily_lakehouse_etl`)**:
  - `Ingest_GCS` -> `Spark_Bronze_to_Silver` -> `dbt_run_models` -> `dbt_test` -> `Great_Expectations_Quality_Gate`.
- **Weekly ML (`dag_weekly_model_retraining`)**:
  - Triggers MLflow retraining jobs using Gold marts as feature stores.

## 9. Partitioning & Clustering Strategy
- **Fact Tables (e.g., `transactions`, `digital_events`)**:
  - Partitioned by `process_date` (Year/Month/Day).
  - Clustered by `customer_id` to speed up Customer 360 queries.
- **Dimension Tables (e.g., `customers`, `branches`)**:
  - Partitioned by `country_code` (MX, CO, AR).

## 10. Streaming Demo
Real-time transaction scoring architecture using Kafka and Spark Structured Streaming.

### Kafka Topic Schema (`tx-events`)
```json
{
  "type": "record",
  "name": "TransactionEvent",
  "fields": [
    {"name": "transaction_id", "type": "string"},
    {"name": "customer_id", "type": "string"},
    {"name": "amount", "type": "double"},
    {"name": "currency", "type": "string"},
    {"name": "timestamp", "type": "long"}
  ]
}
```

### Spark Structured Streaming
```python
df = spark \
  .readStream \
  .format("kafka") \
  .option("kafka.bootstrap.servers", "broker:9092") \
  .option("subscribe", "tx-events") \
  .load()

parsed_df = df.selectExpr("CAST(value AS STRING)") \
  .select(from_json(col("value"), schema).alias("data")) \
  .select("data.*")

# Process and write stream to Silver Delta table / Redis for real-time serving
```

## 11. Data Lineage & Documentation
- **dbt docs**: Configured to auto-generate dictionary and column-level lineage via `dbt docs generate` integrated into CI/CD.
- **Metadata**: Published to a unified data catalog (e.g., Datahub or Amundsen).
