# LATAM Bank data platform

The data-engineering platform behind the strategy in [`docs/strategy`](../strategy/README.md): a lakehouse with
medallion zones and a Kimball core, orchestrated by Airflow 3 + Cosmos, with Postgres/pgvector and Neo4j for
serving and GraphRAG, MLflow for ML/DL/GenAI tracking, Redpanda + Flink for real-time fraud, an immutable audit
stack, PII guardrails, differential privacy, residency-aware deployment and regulatory triggers. Runs fully on a
laptop (Docker Compose profiles); the GCP deployment is Terraform per residency region (validated, not applied).

| chapter | content |
|---|---|
| [00 Plan](00_plan.md) | the approved implementation plan: decisions, phases, verification and risks |
| [01 Architecture](01_architecture.md) | naming (medallion + Kimball), zones, system context, orchestration, local vs cloud vs hybrid, storage compartments and networks |
| [02 Data flows](02_data_flows.md) | batch flow and gates, streaming sequence and latency budget, asset graph, lineage producers |
| [03 Data split](03_data_split.md) | historical vs stream holdout, ML splits with embargo, warm-up week |
| [04 Audit and lineage](04_audit_and_lineage.md) | hash chains, WORM anchors, tamper tests, GenAI audit layers, crypto-shredding |
| [05 Privacy and compliance](05_privacy_and_compliance.md) | policies as code, PII choke points, residency, differential privacy scope, regulatory triggers |
| [06 Knowledge and GraphRAG](06_knowledge_and_graphrag.md) | document lifecycle, sync/prune/reconcile, Neo4j model |
| [07 ML and graph learning](07_ml_and_graph_learning.md) | fraud ensemble + detector CI + HITL, TGN, federated GNN, MLflow records |
| [08 Agentic interfaces](08_agentic_interfaces.md) | what the pending agent module will consume and must log |
| [09 Data and model risk methodology](09_data_and_model_risk_methodology.md) | raw schema forensics without metadata, lossless bronze, cell-level findings, audited correction, drift MRM, keys, segmentation, text |
| [ADRs](adr/README.md) | ten architecture decisions |
| [Runbook](runbook.md) | start, run, demo and verify |
| [Generated dbt lineage](generated/dbt_lineage.md) | zone- and model-level lineage from the manifest |
| [Phase 3 evidence](evidence/phase3/README.md) | parity, real-data findings and circuit-breaker control behind 09 §C, with the scripts that reproduce them |

## Repository map
```
platform/
  dbt/                     latam_lakehouse dbt project (silver, gold, features, graph, knowledge, privacy, serving, audit, bigquery)
  airflow/dags/            16 DAGs; include/latam_dags/common.py; tests/
  libs/latam_platform/     config, lakehouse (landing, bronze), governance, pii_guard, audit_ledger, genai_audit,
                           privacy, kb_pipeline, stream, ops, ml/ (fraud_ensemble, tgn, federated_gnn); tests in libs/tests
  services/fraud_scorer/   real-time scorer (Kafka consumer + FastAPI)
  flink/                   Flink image + SQL job
  policies/                data classification, residency, retention, regulatory triggers, KB governance
  docker/                  compose.yml, Postgres init (serving, knowledge, audit), MinIO, Kong, Marquez, Prometheus, Grafana
  infra/terraform/gcp/     modules + envs mx, br, latam-shared
knowledge/                 governed KB documents
```

## What was verified on the running stack (end-to-end Airflow run, 2026-10-03)
| step | result |
|---|---|
| landing → bronze (Airflow) | 12,505 files fingerprinted; 13 tables reconcile (0 rejected, 0 lost); manifests sealed in object-locked MinIO |
| dbt lakehouse (Cosmos, 90+ tasks) | all layers green; data-quality gate and governance gate passed |
| serving publication | 7 tables swapped into Postgres with digests (e.g. customer_360 150,000 rows; recent_transactions 4.28 M) |
| knowledge base | 9 approved documents active and reconciled across registry, pgvector and Neo4j; draft, superseded, retired and expired versions never indexed |
| graph | 14k nodes / 93k edges for the 2 % demo sample in Neo4j |
| regulatory triggers | 10,634 events (consent, complaint SLA at risk, AML typologies) |
| monitoring | PSI ≤ 0.02 on every monitored feature; disparate-impact ratio of the eligibility policy 0.86 (threshold 0.8) |
| fraud model | registered in MLflow with lineage tags; detector CI recall 1.0 on all 5 types; label AUC 0.49 / 0.54 (no signal, as expected); **waiting for model-risk approval** |
| stream demo | 38,149 events replayed in 135 s; **Flink vs dbt parity: 0 mismatches on all 5 features for 7,789 transactions** |
| audit | every step in the hash-chained ledger; `verify_chain` reports 0 problems; anchors in WORM |
| tests | 26 library tests, 19 DAG integrity tests, dbt tests incl. governance; Terraform validate + tflint clean |

## Problems the end-to-end run surfaced (and how they were fixed)
| problem | root cause | fix |
|---|---|---|
| bronze tasks killed (SIGKILL) | whole-table staging in RAM inside a 4 GB scheduler | month-by-month build in a file-backed DuckDB (peak ~0.5 GB) |
| scheduler at 3.7 GB while idle | LocalExecutor pre-forks one ~220 MB worker per `parallelism` slot (default 32) | `parallelism = 4` |
| dbt in Cosmos could not find bronze | Cosmos runs dbt from a temp copy; relative lake paths broke | operators inherit the container env (`append_env`), absolute `LATAM_LAKE_DIR` |
| inquiry mart out of memory | ordered list aggregate over 4.3 M rows does not spill | normalized `serving_recent_transactions` (rank 1–20 per product) |
| Flink job restarting | JobManager checkpoint storage caps state at 5 MB | filesystem checkpoints on a shared volume |
| last streamed windows never emitted | idle source after a finite replay holds the watermark | one warm-up sentinel per partition flushes the watermark |
| 1,865 parity mismatches on `tx_count_7d` | the planner merged windows with the same PARTITION BY/ORDER BY and compiled 7 days as 24 h | distinct equivalent partition keys per window; EXPLAIN shows 3 frames |
| outbound telemetry from Cosmos | default usage metrics to an external endpoint | disabled (`AIRFLOW__COSMOS__ENABLE_TELEMETRY=False`, `DO_NOT_TRACK=1`) |
