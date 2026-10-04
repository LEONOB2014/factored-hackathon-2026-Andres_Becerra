# Plan: Compliance-grade data platform (lakehouse medallion + Kimball core) with Airflow, dbt, Flink, Postgres/pgvector, Neo4j, MLflow and a full audit stack

> **Decision record.** The approved implementation plan for the data platform (2026-10-02),
> kept as written. Paths reflect the layout of that time: the dbt project lived in `warehouse/`
> (now [`platform/dbt/`](../../platform/dbt/)) and the EDA scripts in `scripts/` (now
> [`eda/scripts/`](../../eda/scripts/)). What was built and verified is described in the
> chapters of this folder and in the [ADRs](adr/README.md).

## Context
The project has three things today:
- `warehouse/`, a working dbt-duckdb project with 42 models;
- a strategy report in `docs/strategy/`;
- file-based ingestion (CSV → Parquet) that is rebuilt in full on every run.

The user wants this rebuilt as a professional, demo-able data-engineering platform for a regulated LATAM bank. The requirements:
- **Orchestration:** Airflow drives dbt.
- **ML and GenAI tracking:** MLflow tracks the ML, DL and GenAI models.
- **Audit and lineage:** immutable, tamper-evident audit logs and real-time lineage.
- **PII and privacy:** PII guardrails and differential privacy.
- **Residency and regulation:** residency-aware storage and regulatory triggers.
- **Stores:**
  - Postgres as the main structured store, with pgvector for embeddings;
  - Neo4j for GraphRAG;
  - DuckDB for experimentation;
  - BigQuery for cloud analytics marts.
- **Demo data split:** a held-out slice replayed as a real-time stream for fraud detection, and marts for ML, DL and GNN training (TGN and federated graph learning included).
- **Knowledge base:** a governed KB that never serves draft or outdated documents.
- **GenAI audit:** a complete audit stack (model version, prompts, retrieved documents, outputs, human overrides).
- **Docs and skills:** diagrams, plus skills installed at system level.

The Agentic module stays pending; this plan builds everything it will consume.

**User decisions:**
1. GCP is Terraform plus a dbt BigQuery target, validated offline and **not applied**.
2. The **full local stack** runs on Docker Compose profiles.
3. Embeddings use a **local open model**.
4. Streaming uses **Redpanda + Apache Flink**.

## Recommendation (answers to the questions asked)
- **Architecture name: lakehouse with medallion zones and a Kimball core.**
  - **Bronze** is immutable raw landing (object-locked).
  - **Silver** is conformed and cleansed (dbt `stg_` + `int_`).
  - **Gold** is a dimensional core (`dim_`/`fct_`, SCD2 dims) plus consumer marts (`mart_`), feature sets (`feat_`, `ml_`) and graph sets (`graph_`, `tgn_`, `fgl_`).
  - Cross-cutting zones: `audit`, `privacy`, `knowledge`, `serving`.
  - Batch and stream share feature definitions (a Kappa-style stream with batch reprocessing).
- **Orchestration:** Apache Airflow 3 (pinned 3.3.x) using:
  - **Astronomer Cosmos** for dbt (each model becomes a task, and OpenLineage events are emitted);
  - **asset-based scheduling** (data-aware DAG chaining);
  - **human-in-the-loop operators** for compliance approvals.
  - On GCP this maps to Cloud Composer 3.
- **Local vs cloud:** hybrid.
  - **Local:** DuckDB for development and experimentation, and the full Docker stack for demos.
  - **Cloud:** BigQuery holds analytics marts per residency region. Postgres (Cloud SQL) holds operational serving, online features, the KB with pgvector, and decision and audit logs. Neo4j holds the graph.
  - Only tokenised gold and analytics marts go to BigQuery; raw PII stays in country.
- **Residency.** BigQuery offers `northamerica-south1` (Querétaro) for Mexico and `southamerica-east1` (São Paulo) for Brazil. **It has no region in Colombia or Argentina** (verified against GCP docs). For CO and AR the default is São Paulo with a documented transfer basis, keeping per-country datasets, CMEK (customer-managed keys) and tokenisation. This is flagged for legal sign-off.

## Phase 0: System-level skills (installed into `~/.claude/skills`, not the project)
1. Shallow-clone the official repositories to the scratchpad:
   - `dbt-labs/dbt-agent-skills`
   - `astronomer/agents` (Airflow DAG authoring, testing, debugging, lineage)
   - `neo4j-contrib/neo4j-skills` (Cypher, modeling, GraphRAG, import)
   - `mlflow/skills` (tracing, evaluation)
2. **Read every SKILL.md and bundled script before copying.** Copy only the relevant skill folders, with no name clashes against the existing gstack skills.
3. Report what was installed. Skills load in the next Claude Code session.
4. Install `terraform` and `tflint` with Homebrew for offline validation.

## Phase 1: Repository restructure and data split
New layout (`git mv` keeps history):

```
platform/
  dbt/                 ← warehouse/ (project renamed latam_lakehouse)
  airflow/{dags,include,plugins,tests}/
  flink/{sql,Dockerfile}            connector jars: Kafka, JDBC, Postgres driver
  services/{stream_replayer,fraud_scorer,kb_pipeline,graph_loader}/
  libs/{audit_ledger,genai_audit,pii_guard,privacy,lineage}/   shared Python packages
  ml/{fraud_ensemble,tgn,federated_gnn}/
  policies/{data_classification,residency,retention,regulatory_triggers,kb_governance}.yaml
  docker/{compose.yml,postgres-init/,kong.yml,prometheus/,grafana/,minio/}
  infra/terraform/gcp/{modules/*,envs/{mx,br,latam-shared}}
knowledge/             governed KB documents (markdown + YAML front matter)
docs/platform/         architecture, ADRs, diagrams, runbooks
```

**Data split.** These become vars in `dbt_project.yml` and are enforced by a bronze split task:

| set | rule | purpose |
|---|---|---|
| historical | `process_date < stream_cutoff` (default 2026-05-18) | batch marts and training |
| stream holdout | the last 30 days of transactions plus login events | replayed through Redpanda → Flink → scorer |
| ML splits | inside historical: train `< 2025-07-01`, valid `< 2026-01-01`, test `< stream_cutoff`, 7-day embargo | model training |
| demo subset | a deterministic 2 % customer sample | UI and agent demos |

`scripts/eda_overview.py` and `scripts/build_backup_parquet.py` are reused for CSV → Parquet. Bronze becomes `data/lake/bronze/<table>/process_date=…/` with a manifest per partition.

## Phase 2: dbt refactor (DuckDB dev target, BigQuery target)

**Schemas.**

| schema | contents |
|---|---|
| `silver` | `stg_*` views, `int_*` |
| `gold` | `dim_customer` (SCD2 from the snapshot), `dim_product`, `dim_branch`, `dim_agent`, `dim_merchant`, `dim_date`, `dim_country`, `fct_transaction`, `fct_interaction`, `fct_complaint`, `fct_campaign_send`, `fct_digital_session`, plus the existing `mart_*` rebuilt on the gold core |
| `features` | `feat_fraud_realtime_pit`, `feat_credit_eligibility_pit`, `ml_fraud_{train,valid,test}`, `ml_kumo_*` |
| `graph` | renamed exports plus new marts (below) |
| `audit` | existing audit models |
| `privacy` | DP aggregates |
| `serving` | contracts for the tables published to Postgres |

**Renames.**
- `export_graph_nodes/edges` → `graph_nodes` / `graph_edges`
- `export_temporal_tx_events` → `tgn_tx_events`
- `export_kumo_*` → `ml_kumo_*`
- `export_graphrag_*` → `kb_entity_docs` / `kb_entity_triples`

**New marts.**
- `tgn_node_features`
- `tgn_edge_features_by_country`
- `fgl_silo_nodes` / `fgl_silo_edges`: federated graph silos per country. Merchants are shared public nodes, and the residency column decides where each silo may live.
- `feat_fraud_stream_parity`: dbt features computed over the holdout rows, used to test the Flink features against them.
- `serving_*` contracts:
  - `serving_customer_360`
  - `serving_card_support`
  - `serving_account_inquiry`
  - `serving_dispute_case`
  - `serving_credit_eligibility`
  - `online_fraud_features_bootstrap`
- `dp_complaints_by_country_month` and `dp_transactions_by_segment` (privacy).

**Governance metadata on every model** (`meta`): `owner`, `data_class` (public / internal / confidential / restricted-PII), `pii_columns`, `residency`, `retention_days`, `pit_safe`, `consumers`.
- New generic tests enforce the rules: `no_pii_in_zone` (fails when restricted columns reach gold, features, graph or serving) and `residency_declared`.

**Contracts and access.**
- `contract: enforced` on gold, features, graph and serving.
- Groups: platform, risk, cx, marketing, ml.
- `access: public` only for serving, features and graph.
- Exposures for the Airflow publish task, the fraud model, the GraphRAG pipeline and the pending agent tools.

**BigQuery portability.**
- `adapter.dispatch` macros for the DuckDB-only constructs: ASOF join, `list`/`struct`, `exclude current row`, `columns(*)`, `md5`/`sha256`, `date_diff`.
- A `bq` target and a `ci` target in `profiles.yml`.
- `dbt parse --target bq` must pass offline.

## Phase 3: Storage compartments and security (Docker Compose, profiles `core|graph|ml|stream|obs`)

| compartment | store | holds | network |
|---|---|---|---|
| Bronze / WORM | MinIO bucket `bronze` + `audit-anchors`, **object lock COMPLIANCE mode** | raw partitions, manifests, audit chain anchors | `net_data` |
| Analytics (dev) | DuckDB `data/lake/lakehouse.duckdb` | silver / gold / features / graph | Airflow worker only |
| Serving | Postgres `pg-core`, DB `bank_serving` (schemas `serving`, `online_features`, `decisions`) | published marts, online features, append-only fraud decision log | `net_data`, `net_app` |
| Knowledge | Postgres `pg-core`, DB `knowledge` (pgvector, HNSW) | `kb.document_version`, `kb.chunk`, view `kb.active_chunk` | `net_data` |
| Audit | **separate** Postgres `pg-audit`, DB `audit` | `ledger.event` (hash chain), `genai.*`, `compliance.trigger_event`, `privacy.budget_ledger`, `dsar.request` | `net_audit` only |
| Platform metadata | `pg-core` DBs `airflow`, `mlflow`; `pg-lineage` DB `marquez`; `monitoring` | metadata and drift reports | `net_ops` |
| Graph | Neo4j Community | entity graph (tokens only) + KB graph | `net_data` |
| ML artifacts | MinIO bucket `mlflow-artifacts` | models, datasets, model cards | `net_ml` |
| Streaming | Redpanda (topics `tx.raw`, `tx.features`, `tx.decisions`), Flink JobManager + TaskManager | stream | `net_stream` |
| Edge | Kong (DB-less) API gateway: key auth, rate limit, request-id, no direct DB exposure | scorer API (agent API pending) | `net_edge` → `net_app` |
| Observability | Prometheus, Grafana, Marquez web, MLflow UI | metrics, lineage, runs | `net_ops` |

**Postgres roles.**
- The writer role has INSERT only on ledger tables; UPDATE, DELETE and TRUNCATE are revoked and blocked by triggers.
- Readers have no write access.
- The audit DB is unreachable from app networks except through the audit library's insert role.
- Secrets live in `docker/.env` (git-ignored) and Docker secrets. TLS and mTLS are documented as production requirements.

## Phase 4: Integrity, audit and lineage stack (`platform/libs/audit_ledger`, `lineage`, `genai_audit`)

**Ledger.**
- Each row stores `seq`, `event_time`, `actor`, `event_type`, `subject_ref`, `payload_jsonb` (PII redacted or encrypted), `prev_hash` and `row_hash = sha256(prev_hash ‖ canonical_json)`.
- The hourly DAG `audit_anchor` recomputes the chain, writes the head hash and a Merkle root to the object-locked MinIO bucket, and alerts on any break.

**Crypto-shredding.** Personal fields inside immutable logs are encrypted with per-subject data keys. An erasure request (LFPDPPP ARCO, LGPD, Ley 1581, Ley 25.326) destroys the key. The ledger stays verifiable, and the destruction itself is logged.

**Lineage.**
- The OpenLineage provider (Airflow), Cosmos/dbt, the Flink OpenLineage listener, and custom `openlineage-python` events from the KB pipeline, the graph loader and the scorer all report to Marquez. That gives run-time lineage down to column level from dbt.
- Every bronze partition, dbt run, model version and KB version carries a `run_id` that joins the ledger, MLflow and Marquez.

**GenAI audit schema** (built now; the agent module will write to it). All tables are append-only and hash-chained, and each row links to an MLflow trace ID.

| table | records |
|---|---|
| `genai.model_version` | provider, model id, weights hash, quantisation, approval |
| `genai.prompt_version` | full system instructions, template, hash, approver, effective dates |
| `genai.request` | caller, purpose, country, request id |
| `genai.retrieval` | doc id, doc version, chunk id, chunk hash, score, rank, KB snapshot id |
| `genai.generation` | model and prompt versions, parameters, redacted input/output, guardrail verdicts |
| `genai.human_override` | reviewer, original vs final, reason |
| `genai.feedback` | user feedback |

Python decorator `audited_llm_call` with MLflow Tracing; tested with a stub model.

## Phase 5: PII guardrails, privacy, residency, regulatory triggers

**`pii_guard`.**
- Presidio, extended with LATAM recognisers: CURP, RFC, CLABE (MX); CPF, CNPJ, Pix keys (BR); Colombian cédula (CC) and NIT (CO); DNI, CUIT/CUIL, CBU/CVU (AR); card PAN with a Luhn check; emails and phones.
- It runs at four choke points:
  1. KB ingestion, which blocks documents containing PII;
  2. text columns in staging, where they are masked before silver;
  3. GenAI logging (before MLflow and the ledger);
  4. the serving publish step (column classification check).

**Policies as code** (`platform/policies/*.yaml`):
- data classification;
- residency (country → allowed regions; the checker runs as a dbt test and an Airflow pre-publish task; in Terraform as org policy `gcp.resourceLocations`);
- retention per record class;
- KB governance.

**Differential privacy.** The evaluation goes in a doc; the implementation covers:
- DP for **aggregate releases and cross-country analytics only**, using OpenDP locally and `SELECT WITH DIFFERENTIAL_PRIVACY` in the BigQuery macros, with an epsilon budget ledger.
- DP-SGD (Opacus) evaluated for models trained on sensitive attributes.
- DP noise on federated updates (DP-FedAvg).
- Not used for operational fraud, AML or regulatory reports, which legally need exact values.

**Regulatory triggers** (`regulatory_triggers.yaml`, evaluated by the `compliance_triggers` DAG and the stream scorer, written to `compliance.trigger_event`):

| trigger | response |
|---|---|
| consent revoked | send suppression |
| erasure / data-subject request | crypto-shred + lineage-driven purge of marts, vectors and graph |
| complaint SLA at risk | alert |
| AML typology hit | case record |
| PII detected outside a PII zone | block publish + incident |
| residency violation | block |
| model drift or fairness breach | model-risk review via a human-in-the-loop task |
| KB document expired or superseded | prune |
| retention expiry | archive or delete |

## Phase 6: Knowledge base and GraphRAG lifecycle (`kb_pipeline`, Neo4j + pgvector)

**Documents.** `knowledge/*.md` with front matter:
- `doc_id`, `version`, `status` (draft | in_review | approved | superseded | retired);
- `effective_from` / `effective_to`, `owner`, `approver`, `country`, `language`;
- `classification`, `supersedes`, `source_url`, `content_hash`.

**Seed corpus** (about 12 documents), labelled as synthetic internal policies or as regulatory summaries with source links:
- a dispute policy v1 (superseded) and v2;
- a draft AML guidance, which must be excluded;
- an expired document;
- the MED 2.0, LFPDPPP 2025 and PL 2338 summaries, based on facts verified earlier;
- consent, residency, model-risk, GenAI-use and retention standards.

**DAG `kb_sync`.**
1. Detect changes by hash.
2. Validate front matter and the status gate: only `approved` documents inside their effective window.
3. Run the PII scan.
4. Chunk.
5. Embed with a local multilingual sentence-transformers model on MPS.
6. Upsert into pgvector.
7. Extract entities deterministically (dictionary and regex: regulators, regulations, controls C1–C10, rules R01–R27, products, dbt models).
8. Upsert Neo4j: `(:Document)-[:HAS_VERSION]->(:DocVersion)-[:HAS_CHUNK]->(:Chunk)-[:MENTIONS]->(:Entity)`, `(:DocVersion)-[:SUPERSEDES]->`, `(:Control)-[:IMPLEMENTED_BY]->(:DbtModel)`.
9. **Prune.** Superseded, retired and expired versions are removed from the active index and the active graph and archived to an append-only snapshot, so "what did the KB contain at time T" stays answerable.
10. **Reconcile.** The active set in the registry, pgvector and Neo4j must be identical, or the run fails.
11. Emit OpenLineage events and write ledger entries.

**Other loaders.**
- `graph_load` loads `graph_nodes` / `graph_edges` (tokens only) into Neo4j with constraints.
- `kb_entity_docs` feeds the same pgvector index under a `source=warehouse` partition.

## Phase 7: Streaming fraud demo (Redpanda + Flink + scorer)
1. `stream_replayer` publishes the holdout transactions and logins to `tx.raw` in event-time order at a configurable speed (for example one day per minute).
2. **Flink SQL jobs** (custom image with the Kafka, JDBC and Postgres connector jars):
   - watermarks on event time;
   - one statement per OVER window (1 h, 24 h, 7 d);
   - expanding history with `ROWS UNBOUNDED PRECEDING` and state TTL;
   - output to `tx.features` and to `online_features` (JDBC upsert).
3. **`fraud_scorer`** (Python, Kafka consumer plus FastAPI behind Kong):
   - computes novelty flags in keyed state;
   - loads `models:/fraud_ensemble@champion` from MLflow (rules plus IsolationForest/COPOD/robust Mahalanobis, trained by `ml_fraud_ensemble`);
   - writes decisions with reason codes to the `tx.decisions` topic and to the append-only `decisions.fraud_decision_log`;
   - exposes Prometheus metrics (latency p50/p95, alert rate).
4. **Parity DAG:** Flink features vs `feat_fraud_stream_parity` on the holdout; tolerance 0 for counts and 1e-6 for sums.
5. Every 15 minutes the stream lands back into bronze (Kappa loop).

## Phase 8: ML and GNN pipelines (MLflow)
- **`ml_fraud_ensemble`:**
  1. train on `ml_fraud_train`; validate and test out of time;
  2. log parameters, metrics, the dataset version (dbt manifest hash and bronze manifest) and the model card;
  3. register the model;
  4. a human-in-the-loop approval task sets the `@champion` alias.
- **`ml_tgn`:** PyG `TGNMemory` on `tgn_tx_events` (CPU or MPS, bounded epochs), logged to MLflow.
- **`ml_federated_gnn`:**
  - a GraphSAGE task per country silo (`fgl_*`) on the complaint-90d task, using FedAvg / FedProx implemented in PyTorch (Flower documented for production);
  - optional DP noise on updates;
  - compared against a centralised baseline. Results are reported honestly, including "no signal".
- **Monitoring:** `monitoring_drift` runs Evidently on features and scores and writes to the monitoring DB and Grafana.

## Phase 9: Airflow DAGs (`platform/airflow/dags`, Airflow 3, TaskFlow + assets)
1. `landing_ingest`
2. `bronze_build` (CSV → Parquet, holdout split, manifests, WORM)
3. `dbt_lakehouse` (Cosmos task groups per layer, data-quality gate on A-rules)
4. `publish_serving` (DuckDB → Postgres through the DuckDB postgres extension, with contract, PII and residency checks)
5. `graph_load`
6. `kb_sync`
7. `ml_fraud_ensemble`
8. `ml_tgn`
9. `ml_federated_gnn`
10. `stream_demo` (replay, Flink job submission, parity)
11. `audit_anchor`
12. `compliance_triggers`
13. `dp_release`
14. `monitoring_drift`
15. `backup_reconciliation`
16. `retention_and_erasure`

Each DAG has an owner, an SLA, retries, idempotent tasks, OpenLineage, and ledger events on start and finish. `airflow/tests` runs a DagBag import test, a cycle test, and a "every DAG has owner and tags" test.

## Phase 10: GCP Terraform (validated, not applied)
**Modules.**
- `network`: VPC, private service connect, VPC Service Controls perimeter.
- `kms`: CMEK keys per country.
- `gcs_worm`: bucket lock retention.
- `bigquery`: datasets per residency, policy tags and column-level security, row access policies, DP analysis rules.
- `cloudsql_postgres`: pgvector, private IP.
- `composer`: Airflow 3.
- `pubsub_or_managed_kafka`.
- `dataflow_flink` / `gke`.
- `sensitive_data_protection`: DLP inspect templates.
- `api_gateway`: Apigee or API Gateway, with Cloud Armor.
- `org_policy`: `gcp.resourceLocations`.
- `logging`: audit logs routed to a locked bucket.

**Environments:** `mx` (northamerica-south1), `br` (southamerica-east1), `latam-shared` (CO/AR, southamerica-east1, pending legal).

**Checks:** `terraform fmt -check`, `terraform validate`, `tflint`.

## Phase 11: Documentation and diagrams (`docs/platform/`, plus the published artifact page)
**ADRs:**
1. medallion + Kimball
2. Airflow + Cosmos
3. Postgres + pgvector vs a dedicated vector DB
4. Neo4j for GraphRAG
5. Flink for streaming
6. DuckDB dev vs BigQuery prod
7. residency strategy
8. crypto-shredding vs immutability
9. DP scope
10. federated graph learning

**Mermaid diagrams:**
- system context;
- zones and compartments with networks;
- batch data flow (bronze → serving);
- stream flow with latency budget;
- KB / GraphRAG document lifecycle (state machine plus prune);
- audit stack (ledger → anchor → verification);
- GenAI audit sequence (request → retrieval → generation → override);
- lineage graph (OpenLineage producers → Marquez);
- residency map (country → region → datasets);
- DAG asset graph;
- local vs GCP deployment.

**The Agentic module** is drawn as a pending component, with its interfaces: serving schema, `kb.active_chunk`, Neo4j, MLflow model registry, `genai_audit`.

**Also:** a runbook (how to start each profile and run the demo), an update to `docs/strategy` references (warehouse path), the README, and a refreshed artifact page.

## Verification (per phase; commit after each with Conventional Commits)
- **dbt:**
  - `dbt build` (DuckDB) green after the refactor, with the 4 expected warnings plus the new tests;
  - `dbt parse --target bq` passes;
  - `no_pii_in_zone` and `residency_declared` are green.
- **Compose:**
  - `docker compose --profile core --profile graph --profile ml up -d`, then all health checks pass;
  - stream and observability profiles are started separately to respect the 16 GB RAM;
  - `docker stats` peak is recorded in the runbook.
- **Airflow:**
  - the DagBag test passes;
  - trigger `landing_ingest → … → publish_serving` end to end;
  - Marquez shows the lineage graph from bronze to serving.
- **Immutability:**
  - `UPDATE` and `DELETE` on `ledger.event` fail;
  - deleting an object-locked MinIO object fails;
  - `audit_anchor` verifies the chain;
  - a deliberately tampered row in a copy is detected.
- **KB:**
  - after marking a document superseded and adding v2, the old version is absent from `kb.active_chunk` and the active Neo4j graph and present in the archive;
  - the draft document is never indexed;
  - the reconciliation check passes;
  - a PII-bearing test document is blocked.
- **Stream:**
  - replaying one holdout day gives a parity check with 0 mismatches;
  - scorer p95 latency is reported;
  - decisions are appended and visible in Grafana.
- **ML:**
  - MLflow shows runs with dataset lineage tags;
  - the champion alias is set only after the approval task;
  - TGN and federated runs are logged.
- **Privacy:** epsilon is debited in `privacy.budget_ledger`, and a query over budget is refused.
- **Terraform:** `fmt` / `validate` / `tflint` are clean.
- **Repo:** unit tests for `pii_guard` (synthetic identifiers per country), `audit_ledger` (chain and tamper), `genai_audit` (stub model run, all tables written).

## Risks and constraints
- **Resources:** 16 GB RAM and 47 GB of free disk. Images total about 12–15 GB; profiles are started selectively.
- **Third-party installs:** Docker images and Maven connector jars come from official sources, and Hugging Face downloads one multilingual embedding model. All of these are standard and listed in the runbook.
- **Version pinning:** Airflow 3.3, Cosmos, Flink connectors and OpenLineage versions are pinned and verified at install time; incompatibilities are resolved by pinning down a minor version.
- **Cloud scope:** nothing is deployed or billed. Terraform covers design and validation only.
- **Legal:** residency for CO and AR, retention periods and trigger deadlines are policy parameters that must be confirmed by counsel.
