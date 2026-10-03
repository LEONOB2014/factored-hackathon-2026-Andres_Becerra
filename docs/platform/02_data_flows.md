# 02 · Data flows: batch, stream, assets and lineage

[← 01 architecture](01_architecture.md) · [index](README.md) · next: [03 data split →](03_data_split.md)

## 2.1 Batch flow (landing → serving)

```mermaid
flowchart LR
  S3[(S3)] -->|download_s3.py| LND[landing<br/>data/raw]
  LND -->|SHA-256 manifest| M1[(MinIO WORM<br/>manifests/landing)]
  LND -->|month-chunked read_csv<br/>rejects → quarantine| BR[bronze<br/>partitioned Parquet]
  BR -->|partition digests| M2[(MinIO WORM<br/>manifests/bronze)]
  LND -->|backup folder| QU[quarantine]
  BR --> STG[silver: stg_* views]
  STG --> INT[silver: int_* conformed]
  INT --> SNAP[snapshots SCD2]
  SNAP --> DIM[gold: dim_* SCD2]
  INT --> FCT[gold: fct_*]
  DIM & FCT --> MART[gold: mart_*]
  INT --> FEAT[features: feat_* / ml_*]
  INT & FCT --> GRAPH[graph: graph_* / tgn_* / fgl_*]
  MART --> SERV[serving_* contracts]
  MART --> KBD[knowledge: kb_entity_*]
  INT --> PRIV[privacy_input_*]
  INT & QU --> AUD[audit: dq_*, manifests, reconciliation]
  SERV -->|blue/green swap| PG[(Postgres bank_serving)]
  GRAPH -->|graph_load| NEO[(Neo4j)]
  KBD & DOCS[knowledge/*.md] -->|kb_sync| PGV[(pgvector)] & NEO
  PRIV -->|OpenDP + budget| DP[(DP releases)]
  FEAT -->|train| MLF[MLflow]
  AUD -->|gates| GATE{DQ + governance<br/>gates}
  GATE -->|pass| SERV
```

Gates that stop the flow: landing modified/deleted file (incident), bronze not reconciling or rewriting a
partition, severity-A data-quality SLO breach, governance check failure (missing owner/class/residency,
restricted column outside silver, serving without contract), restricted column at publish time, detector CI
failure, model-risk rejection, stream/batch parity mismatch, broken audit chain.

## 2.2 Streaming flow (real-time fraud) with latency budget

```mermaid
sequenceDiagram
  participant RP as Replayer (holdout)
  participant K as Redpanda
  participant F as Flink SQL (1h/24h/7d windows)
  participant S as Fraud scorer
  participant PG as Postgres (online_features, decisions)
  participant M as MLflow (@champion)
  RP->>K: tx.logins, tx.raw (event-time order, warm-up week first)
  K->>F: tx.raw
  F->>K: tx.features (joined windows)
  F->>PG: online_features.tx_window_features (upsert)
  K->>S: tx.features + tx.logins
  S->>S: complete PIT features from state (history, novelty, geo-velocity)
  S->>M: model loaded once at start (version pinned in every decision)
  S->>PG: decisions.fraud_decision_log (append-only, inputs + reasons)
  S->>K: tx.decisions
```

| hop | budget (p95) | evidence |
|---|---|---|
| broker + Flink windows | < 1 s at demo rates | Flink metrics (Prometheus :9249) |
| scorer feature completion + model | < 50 ms | `fraud_scoring_latency_seconds` |
| decision persisted | batched every 200 rows / 1 s | decision log `decided_at` |

## 2.3 Asset graph (data-aware scheduling)

```mermaid
flowchart LR
  LI[landing_ingest @daily] -->|lake://landing/raw| BB[bronze_build]
  BB -->|lake://bronze| DL[dbt_lakehouse]
  BB -->|lake://bronze| BRC[backup_reconciliation]
  DL -->|duckdb://lakehouse/gold| PS[publish_serving]
  DL --> GL[graph_load]
  DL --> CT[compliance_triggers]
  DL --> MD[monitoring_drift]
  DL --> MFE[ml_fraud_ensemble<br/>HITL approval]
  GL -->|neo4j://neo4j/latam| TG[ml_tgn] & FG[ml_federated_gnn]
  PS -->|serving| SD[stream_demo manual]
  MFE -->|mlflow://fraud_ensemble| SD
  KB[kb_sync @hourly]
  AA[audit_anchor @hourly]
  DP[dp_release @monthly]
  RE[retention_and_erasure @daily]
```

## 2.4 Lineage: who emits what

```mermaid
flowchart LR
  AF[Airflow OpenLineage provider<br/>DAG/task runs, inlets/outlets] --> MQ[(Marquez)]
  CO[Cosmos / dbt<br/>model-level + column-level] --> MQ
  LIB[latam_platform jobs<br/>bronze, kb_sync, publish] -->|lineage_run_id| LED[(audit ledger)]
  MLF[MLflow tags<br/>dbt manifest hash, bronze manifest hash] --> LED
  SC[scorer<br/>model version per decision] --> DEC[(decision log)]
  MQ <-->|run id| LED
```

Every artefact carries a `lineage_run_id` (the Airflow run id): bronze rows (`_ingest_run_id`), publication
log rows, KB versions and snapshots, MLflow runs, ledger events. Joining on it answers "which data, code and
model produced this decision", end to end.

The generated dbt lineage (zone and model level) is in [generated/dbt_lineage.md](generated/dbt_lineage.md).
