# 01 · Architecture: lakehouse with medallion zones and a Kimball core

[index](README.md) · next: [02 data flows →](02_data_flows.md)

## 1.1 What the architecture is called, and why
**A lakehouse organised in medallion zones, with a Kimball dimensional core in gold and consumer-specific
marts on top.** The medallion zones (bronze, silver, gold) describe *trust and processing level*. Kimball
(dimensions, facts, SCD2) describes *how gold is modelled*. "Marts" are the consumer-facing denormalized
tables built on the dimensional core. dbt's own layer names (staging, intermediate, marts) map onto the zones:

| zone | contents | dbt | store (local) | store (GCP) | data class |
|---|---|---|---|---|---|
| landing | files exactly as received, SHA-256 manifest | — | `data/raw` | GCS (bucket lock) | restricted PII |
| **bronze_raw** (bronze of record) | every landed record, every field as its original text; each file proven byte-exact against the landing SHA-256 and re-verified from storage | sources `bronze_raw`, `holdout_raw` | `data/lake/bronze_raw`, `holdout_raw` + MinIO WORM partitions and proofs | GCS (bucket lock) | restricted PII |
| quarantine | the untrusted backup folder, lossless | source `quarantine_raw` | `data/lake/quarantine/backup_20260831_raw` | GCS (restricted) | restricted PII |
| archive | the retired typed bronze (read-only, not deleted) | — | `data/lake/archive/bronze_typed_v1` | — | restricted PII |
| **silver** | `typed_` (lossless bronze typed against the reviewed source contracts, every record kept, breaches in `_dq_issues`), schema-drift circuit breaker (`dq_partition_*`, `dq_schema_drift`), cleansed and conformed (`stg_`, `int_`), PII tokenised for downstream | `models/silver` | DuckDB `silver` (+ `audit` for the breaker) | BigQuery / Spark | restricted → confidential |
| **gold** | Kimball core (`dim_` SCD2, `fct_`) + marts (`mart_`) | `models/gold` | DuckDB `gold` | BigQuery `published_<cc>` | confidential |
| features | point-in-time ML features and splits (`feat_`, `ml_`) | `models/features` | DuckDB + Parquet | BigQuery / feature store | confidential |
| graph | GNN/TGN/federated exports (`graph_`, `tgn_`, `fgl_`) | `models/graph` | Parquet → Neo4j | Neo4j (in region) | confidential |
| knowledge | entity documents for GraphRAG | `models/knowledge` | Parquet → pgvector/Neo4j | Cloud SQL + Neo4j | internal |
| privacy | contribution-bounded inputs; DP releases | `models/privacy` + OpenDP | DuckDB + Parquet | BigQuery `privacy_<cc>` | confidential → public |
| serving | contracts published to Postgres | `models/serving` | Postgres `bank_serving` | Cloud SQL | confidential |
| audit | DQ findings, manifests, reconciliation, SCD change log | `models/audit` | DuckDB `audit` | BigQuery + WORM | confidential |

Batch and stream share feature definitions: one dbt macro (`fraud_features`) is the reference, the Flink job
implements the same windows, and a parity check proves they agree (Kappa-style stream with batch reprocessing).

## 1.2 System context

```mermaid
flowchart LR
  subgraph Sources
    S3[(S3 datathon bucket)]
    CORE[Core banking / card switch<br/>future CDC]
  end
  subgraph Lake["Lakehouse (DuckDB local / BigQuery+GCS cloud)"]
    L[landing] --> B[bronze_raw] --> SV[silver] --> G[gold]
    G --> F[features] & GR[graph] & K[knowledge] & P[privacy] & SE[serving]
    B -.quarantine.-> Q[quarantine]
  end
  S3 --> L
  CORE -.-> L
  AF{{Airflow 3 + Cosmos}} -. orchestrates .- Lake
  SE --> PG[(Postgres<br/>bank_serving)]
  K --> PGV[(Postgres pgvector<br/>knowledge)] & NEO[(Neo4j)]
  GR --> NEO
  F --> ML[MLflow<br/>experiments + registry]
  ML --> SC[fraud scorer]
  RP[(Redpanda)] --> FL[Flink] --> SC --> PG
  KONG[Kong gateway] --> SC
  G --> BQ[(BigQuery analytics<br/>per residency region)]
  AUD[(pg-audit<br/>hash-chained ledger)] --- WORM[(MinIO / GCS<br/>object lock)]
  AGENT[[Agentic module<br/>PENDING]] -. read-only tools .-> PG & PGV & NEO & ML
  AGENT -. audit .-> AUD
```

## 1.3 Orchestration: Airflow 3 + Cosmos
* **Airflow 3.1** (Composer 3 in GCP) with **asset-based scheduling**: `landing_ingest` emits the landing
  asset → `bronze_build` → `dbt_lakehouse` → (`publish_serving`, `graph_load`, `compliance_triggers`,
  `monitoring_drift`, `ml_fraud_ensemble`) → `graph` → (`ml_tgn`, `ml_federated_gnn`). See [02](02_data_flows.md).
* **Cosmos** renders each dbt layer as a task group (one task per model, tests per group), so failures,
  retries and lineage are per model, and OpenLineage events flow to Marquez.
* **Human-in-the-loop** (`ApprovalOperator`) gates model promotion; nothing reaches `@champion` without it.
* **Isolation:** Airflow, dbt and the platform/ML code run in three separate Python environments inside the
  image, so dependency upgrades of one cannot break the others.
* Every DAG writes start/finish/failure events to the hash-chained audit ledger.

Why Airflow over Dagster or Prefect for this bank: managed offering in the target cloud (Composer), mature
OpenLineage provider, native HITL in 3.1, and the operational familiarity regulators and auditors already have.

## 1.4 Local, cloud or hybrid
**Hybrid by data class.** Experimentation and demos run fully local (DuckDB + Docker). Production runs in GCP
per residency region. Only tokenised gold/serving/privacy outputs are published to BigQuery for analytics;
raw PII never leaves its in-country (or legally approved) region.

```mermaid
flowchart TB
  subgraph Local["Local demo (Docker Compose profiles, 1 laptop)"]
    direction LR
    LA[Airflow 3] --- LD[(DuckDB lakehouse)]
    LA --- LPG[(pg-core: serving, knowledge, mlflow, airflow, marquez)]
    LA --- LAU[(pg-audit: isolated network)]
    LA --- LM[(MinIO object lock)]
    LA --- LN[(Neo4j)] & LML[MLflow] & LR[Redpanda + Flink] & LMQ[Marquez]
  end
  subgraph MX["GCP northamerica-south1 (Mexico)"]
    direction LR
    CMX[Composer 3] --- BMX[(BigQuery published_mx / analytics_mx / privacy_mx)]
    CMX --- SMX[(Cloud SQL serving + pgvector)] & AMX[(Cloud SQL audit)] & GMX[(GCS bucket lock)]
  end
  subgraph BR["GCP southamerica-east1 (Brazil; CO/AR pending legal)"]
    direction LR
    CBR[Composer 3] --- BBR[(BigQuery *_br)]
    CBR --- SBR[(Cloud SQL serving + pgvector)] & ABR[(Cloud SQL audit)] & GBR[(GCS bucket lock)]
  end
  Local -. same DAGs, dbt project, policies .-> MX & BR
```

| option | verdict |
|---|---|
| Everything local (DuckDB, Docker) | right for development, CI and demos on synthetic data; not for production PII |
| Everything in one cloud region | violates residency for at least one country; single region is a concentration risk |
| **Hybrid by data class (recommended)** | lakehouse + serving + audit per residency region; BigQuery analytics layer per region; DP aggregates are the only cross-border analytics |
| "Some marts in BigQuery" only | sound as the analytics layer (implemented: `models/bigquery`, targets `bq_mx`/`bq_br`); the serving and audit stores still need their own in-region homes |

## 1.5 Storage compartments and network segmentation
Each store has one purpose, its own credentials and its own network. In GCP these become separate projects or
instances inside a VPC Service Controls perimeter (Terraform: `platform/infra/terraform/gcp`).

```mermaid
flowchart LR
  subgraph net_edge["net_edge (public)"]
    K[Kong API gateway<br/>key auth · rate limit · request id]
  end
  subgraph net_app["net_app (internal)"]
    SC[fraud scorer API]
  end
  subgraph net_stream["net_stream (internal)"]
    RP[(Redpanda)] --- FJ[Flink JM/TM] --- GW[Flink SQL gateway]
  end
  subgraph net_data["net_data (internal)"]
    PG[(pg-core)] --- NEO[(Neo4j)] --- MIN[(MinIO WORM)]
  end
  subgraph net_audit["net_audit (internal, audit only)"]
    AU[(pg-audit)]
  end
  subgraph net_ml["net_ml (internal)"]
    MLF[MLflow] --- ART[(mlflow-artifacts)]
  end
  subgraph net_ops["net_ops (UIs on 127.0.0.1)"]
    AF[Airflow] --- MQ[Marquez] --- GR[Grafana/Prometheus]
  end
  K --> SC
  SC --> RP & PG & MLF & AU
  AF --> PG & AU & MIN & NEO & MLF & GW & RP
```

| store | holds | writer roles | reader roles | immutability |
|---|---|---|---|---|
| landing (`data/raw`) | files as received | ingestion only | bronze build | SHA-256 manifest in WORM |
| bronze_raw (`data/lake/bronze_raw`) | original-text records, proof manifests | bronze build | dbt (silver `typed_` models), auditors | append-only by record-digest check; partitions and proofs in WORM; `bronze-raw-verify` rebuilds every file |
| archive (`data/lake/archive/bronze_typed_v1`) | the retired typed bronze | `archive-typed-bronze` (once) | auditors | read-only files and directories; moved, never copied or deleted; per-zone SHA-256 in `ARCHIVE_*.json` and the ledger |
| MinIO `bronze-worm`, `audit-anchors` | manifests, chain anchors | `latam-platform` user (put only) | auditors | **object lock COMPLIANCE** |
| pg-core `bank_serving` | serving tables, online features, decisions | `publisher`, `scorer` (decisions append-only) | `app_reader` | decision log append-only (triggers) |
| pg-core `knowledge` | KB registry, chunks (pgvector) | `publisher` | `app_reader` reads **only** `kb.active_chunk` | registry/events append-only |
| **pg-audit** `audit` | ledger, GenAI audit, triggers, DP budget, DSAR, keys | `audit_writer` (INSERT only) | `audit_reader` | hash chains + no UPDATE/DELETE/TRUNCATE + WORM anchors |
| pg-core `mlflow` + MinIO artifacts | runs, registry, models | MLflow server | MLflow server | registry versions immutable; aliases audited |
| pg-core `marquez` | OpenLineage events | Marquez | Marquez | append-only event log |
| Neo4j | entity graph (tokens), KB graph | Airflow | agents (pending) | rebuilt from lakehouse/KB (derived) |
