# LATAM Bank data platform

The data-engineering platform behind the strategy in [`docs/strategy`](../strategy/README.md): a lakehouse with
medallion zones and a Kimball core, orchestrated by Airflow 3 + Cosmos, with Postgres/pgvector and Neo4j for
serving and GraphRAG, MLflow for ML/DL/GenAI tracking, Redpanda + Flink for real-time fraud, an immutable audit
stack, PII guardrails, differential privacy, residency-aware deployment and regulatory triggers. Runs fully on a
laptop (Docker Compose profiles); the GCP deployment is Terraform per residency region (validated, not applied).

| chapter | content |
|---|---|
| [01 Architecture](01_architecture.md) | naming (medallion + Kimball), zones, system context, orchestration, local vs cloud vs hybrid, storage compartments and networks |
| [02 Data flows](02_data_flows.md) | batch flow and gates, streaming sequence and latency budget, asset graph, lineage producers |
| [03 Data split](03_data_split.md) | historical vs stream holdout, ML splits with embargo, warm-up week |
| [04 Audit and lineage](04_audit_and_lineage.md) | hash chains, WORM anchors, tamper tests, GenAI audit layers, crypto-shredding |
| [05 Privacy and compliance](05_privacy_and_compliance.md) | policies as code, PII choke points, residency, differential privacy scope, regulatory triggers |
| [06 Knowledge and GraphRAG](06_knowledge_and_graphrag.md) | document lifecycle, sync/prune/reconcile, Neo4j model |
| [07 ML and graph learning](07_ml_and_graph_learning.md) | fraud ensemble + detector CI + HITL, TGN, federated GNN, MLflow records |
| [08 Agentic interfaces](08_agentic_interfaces.md) | what the pending agent module will consume and must log |
| [ADRs](adr/README.md) | ten architecture decisions |
| [Runbook](runbook.md) | start, run, demo and verify |
| [Generated dbt lineage](generated/dbt_lineage.md) | zone- and model-level lineage from the manifest |

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

## What was verified on the running stack
* Raw layer: 13 tables reconcile with the landing files (0 rejected, 0 lost); rebuilding rewrites no partition.
* Audit: writer cannot update/delete/truncate; owner blocked by triggers; superuser bypass detected by chain
  verification; WORM objects cannot be deleted or have retention shortened, even by root.
* 26 library tests (PII guard, ledger, crypto-shredding, GenAI audit, DP budget, KB governance) and 19 DAG
  integrity tests pass; dbt build green with governance tests; Terraform validates and tflint is clean.
