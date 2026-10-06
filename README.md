<div align="center">

# BETA AID

### Banking Evolutionary Transformation and AI Deployment

**An AI copilot that LATAM Bank can put in front of its card holders. It works because the data underneath has been
made trustworthy first.**

[![CI](https://github.com/LEONOB2014/factored-hackathon-2026-Andres_Becerra/actions/workflows/ci.yml/badge.svg)](https://github.com/LEONOB2014/factored-hackathon-2026-Andres_Becerra/actions/workflows/ci.yml)
[![Version](https://img.shields.io/badge/version-0.4.0-2563eb)](CHANGELOG.md)
[![License: MIT](https://img.shields.io/badge/license-MIT-16a34a)](LICENSE)
[![Conventional Commits](https://img.shields.io/badge/commits-conventional-fe5196?logo=conventionalcommits&logoColor=white)](https://www.conventionalcommits.org/en/v1.0.0/)
[![pre-commit](https://img.shields.io/badge/pre--commit-enabled-FAB040?logo=pre-commit&logoColor=white)](.pre-commit-config.yaml)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)

[![Correct outcome](https://img.shields.io/badge/correct%20outcome-0.950%20held%20out-0f766e)](copilot/eval/reports/challenge.md)
[![Unsafe outcomes](https://img.shields.io/badge/unsafe%20outcomes-0%2F120%20after%20fix-0f766e)](copilot/eval/reports/challenge_after_fix.md)
[![Retrieval](https://img.shields.io/badge/retrieval%20hit%403-0.94-0f766e)](copilot/eval/reports/kb_retrieval.md)
[![Governance violations](https://img.shields.io/badge/governance%20violations-0-0f766e)](copilot/eval/reports/kb_retrieval.md)
[![Lossless bronze](https://img.shields.io/badge/bronze-13%2F13%20tables%20reconciled-0f766e)](docs/platform/README.md#what-was-verified-on-the-running-stack-end-to-end-airflow-run-2026-10-03)

[![Python](https://img.shields.io/badge/Python-3.12-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![dbt](https://img.shields.io/badge/dbt-1.12%20docs-FF694B?logo=dbt&logoColor=white)](https://beta-aid-dbt-docs.netlify.app)
[![DuckDB](https://img.shields.io/badge/DuckDB-lakehouse-FFF000?logo=duckdb&logoColor=black)](https://duckdb.org/)
[![Airflow](https://img.shields.io/badge/Airflow-3.1-017CEE?logo=apacheairflow&logoColor=white)](platform/airflow)
[![Flink](https://img.shields.io/badge/Flink-1.19-E6526F?logo=apacheflink&logoColor=white)](platform/flink)
[![Postgres](https://img.shields.io/badge/Postgres-pgvector-4169E1?logo=postgresql&logoColor=white)](docs/platform/adr/ADR-003.md)
[![Neo4j](https://img.shields.io/badge/Neo4j-GraphRAG-4581C3?logo=neo4j&logoColor=white)](docs/platform/06_knowledge_and_graphrag.md)
[![MLflow](https://img.shields.io/badge/MLflow-tracking-0194E2?logo=mlflow&logoColor=white)](docs/platform/07_ml_and_graph_learning.md)
[![Modal](https://img.shields.io/badge/Modal-live-7FEE64)](https://aleonardobecerra--beta-aid-copilot-web.modal.run)
[![Cloud Run](https://img.shields.io/badge/Cloud%20Run-MX%20%C2%B7%20SA-4285F4?logo=googlecloud&logoColor=white)](docs/platform/adr/ADR-021.md)
[![Netlify](https://img.shields.io/badge/console-Netlify-00C7B7?logo=netlify&logoColor=white)](https://beta-aid-console.netlify.app)

**[Try the copilot](https://aleonardobecerra--beta-aid-copilot-web.modal.run)** ·
**[Open the console](https://beta-aid-console.netlify.app)** ·
**[Grain Atlas](https://aleonardobecerra--beta-aid-copilot-web.modal.run/atlas)** ·
[Architecture](docs/platform/01_architecture.md) · [Lakehouse docs (dbt)](https://beta-aid-dbt-docs.netlify.app) ·
[Decisions (ADRs)](docs/platform/adr/README.md) ·
[Evaluation](copilot/eval/reports/)

<sub>Factored AI & Data Hackathon 2026 · built by Andrés Becerra</sub>

</div>

---

## Why this exists

It is 11 p.m. and a card holder writes *"mi tarjeta no pasa"* ("my card won't go through"). Today that means a queue,
then an agent switching between systems to work out whether the card is blocked, expired, flagged for fraud or simply
over its limit.

LATAM Bank serves Mexico, Colombia and Argentina, in Spanish and Portuguese. Its data has 686,296 contact-centre
interactions and 67,095 complaints. Of its 140,040 cards, more than 65,000 have a clear, rule-based next action. Many of
those contacts could be answered in seconds.

**The hard part is not the chatbot.** A bank cannot put a model in front of customers unless:
- the facts it reads are true;
- the actions it takes are safe, confirmed and audited;
- the cases it should not handle reach a person.

BETA AID is built in that order: **data you can prove → decisions you can govern → a copilot you can trust.**

## What makes it different

| | |
|---|---|
| 🧾 **The data is proven, not assumed** | Every landed record is kept byte-exact with a fingerprint and per-file proofs. All 13 tables reconcile with 0 rejected and 0 lost. Quality rules flag rows; they never overwrite them. |
| 🚦 **The data decides what AI is allowed** | Readiness gates measure which decisions each grain of data can support. Several popular models are *not* trainable from this data, and the [Grain Atlas](https://aleonardobecerra--beta-aid-copilot-web.modal.run/atlas) says so. |
| ⚖️ **The model recommends; it never decides** | Decision rights follow RAPID. A versioned policy agrees or vetoes, tools act only on the signed-in customer's own cards, and a person decides fraud, limits, disputes and complaints. |
| 🔒 **Every action is confirmed** | HMAC sessions with step-up, a two-step confirmation with read-back, idempotency and a hash-chained audit log for each turn. |
| 🧪 **Evaluated like a regulator would** | The challenge set was frozen and hashed **before** the first scored run. The one unsafe case was reported, fixed and re-run in the open. |
| 🌎 **Residency is enforced, not a slide** | One deployment per residency region. A customer from the other region is refused (401). |

## Try it in two minutes

| Where | What to do |
|---|---|
| **[Copilot (Modal)](https://aleonardobecerra--beta-aid-copilot-web.modal.run)** | Sign in as a demo customer with the test code shown on the page. Ask *"mi tarjeta no pasa"*, then ask it to block a card and watch it confirm before acting. |
| **[Console (Netlify)](https://beta-aid-console.netlify.app)** | Chat simulator → fraud handoff → **agent desk** (four eyes: an agent cannot approve their own request) → supervisor view. |
| **[Grain Atlas](https://aleonardobecerra--beta-aid-copilot-web.modal.run/atlas)** | Which decisions the data can and cannot support, at every grain. |
| **Regional copilots** | Mexico in Querétaro: [`beta-aid-mx`](https://beta-aid-mx-621442591789.northamerica-south1.run.app). Colombia and Argentina in São Paulo: [`beta-aid-sa`](https://beta-aid-sa-621442591789.southamerica-east1.run.app). |

Some control-plane screens in the console still run on labelled demo data; the chat, desk and handoffs call the real
copilot.

## Results

Every number comes from held-out data, with Wilson 95 % intervals. The 120 ES/PT challenge cases, the intent phrasings
and the retrieval questions are pinned by [`MANIFEST.sha256`](copilot/eval/MANIFEST.sha256), committed before scoring.

| Copilot, 120 frozen ES/PT cases | Keyword router | **BETA AID (learned)** |
|---|---|---|
| Correct final outcome | 0.875 [0.80, 0.92] | **0.950** [0.90, 0.98] |
| Safe automated resolution, in-scope cases | 0.841 | **0.937** |
| Missed transfers (person must decide) | 4 / 27 | **1 / 27** |
| Unnecessary transfers | 2 / 63 | **0 / 63** |
| Unsafe outcomes, frozen run → after the fix | 1 / 120 → 0 / 120 | 1 / 120 → **0 / 120** |
| Latency per turn, p50 / p95 | 2.0 / 20.8 ms | 2.9 / 22.5 ms |

- **The unsafe case.** In the frozen run, one Portuguese prompt injection got past the guard. The policy still routed
  it to a person. The guard was fixed and the same frozen set was re-run, giving 0/120 unsafe and 0.958 correct
  ([after-fix report](copilot/eval/reports/challenge_after_fix.md)). The headline above stays the pre-fix figure.
- **Intent model:** accuracy 0.818 against 0.576 for keywords, on 132 held-out phrasings across 15 intents. It was tuned
  with Optuna and tracked in MLflow.
- **Retrieval:** hit@3 0.94 on 28 ES/PT questions, the same for pgvector, GraphRAG and hybrid. Zero retired,
  superseded, draft or expired documents were returned ([report](copilot/eval/reports/kb_retrieval.md)).
- **Platform, end-to-end run (2026-10-03):**
  - 12,505 files fingerprinted;
  - every dbt layer green behind the quality and governance gates;
  - 7 serving tables published with digests;
  - Flink and dbt streaming features in parity, 0 mismatches over 7,789 transactions;
  - the audit chain verified with 0 problems ([evidence](docs/platform/README.md#what-was-verified-on-the-running-stack-end-to-end-airflow-run-2026-10-03)).

## Architecture

<img src="docs/assets/architecture/beta-aid-architecture.svg" alt="BETA AID infrastructure and data flow: public internet, Google Cloud regions, Modal and the private Docker networks of the data platform, with animated flows" width="100%">

The diagram is generated by [`scripts/diagrams/architecture.py`](scripts/diagrams/architecture.py). It shows:
- the network boundaries exactly as [`compose.yml`](platform/docker/compose.yml) declares them;
- one copilot service per residency region;
- the gate every request passes.

The logical view:

```mermaid
flowchart LR
  subgraph SRC["LATAM Bank sources"]
    S3[("S3 bucket<br/>13 tables · 23.5 M rows")]
  end

  subgraph PLAT["Data platform · Airflow 3 + Cosmos · dbt on DuckDB"]
    direction TB
    BR["bronze_raw<br/>lossless · fingerprinted · WORM manifests"]
    SI["silver<br/>contract typing · quality rules R01–R27"]
    GO["gold<br/>Kimball core (SCD2) · use-case marts"]
    AG["aggregates<br/>day · cell · hour grains"]
    SV["serving contracts<br/>customer 360 · card support · disputes"]
    BR --> SI --> GO
    GO --> AG
    GO --> SV
  end

  subgraph STREAM["Streaming"]
    RP[("Redpanda")] --> FL["Flink<br/>online fraud features"]
  end

  subgraph STORE["Operational stores"]
    PG[("Postgres<br/>bank_serving · online_features")]
    PGV[("pgvector<br/>kb.active_chunk")]
    N4J[("Neo4j<br/>knowledge graph")]
  end

  subgraph KB["Governed knowledge"]
    MD["knowledge/*.md<br/>approved · versioned · in-window"]
  end

  subgraph GOV["Control plane"]
    RG["readiness gates<br/>Grain Atlas"]
    AU[("hash-chained<br/>audit ledger")]
  end

  subgraph APP["BETA AID"]
    CP["card copilot<br/>ES · PT"]
    CO["console<br/>chat · desk · supervisor · atlas"]
  end

  S3 --> BR
  AG --> RG
  SV -->|"digest-checked publish"| PG
  FL --> PG
  MD --> PGV
  MD --> N4J
  SV -->|"serving snapshot per region"| CP
  PGV -->|"index verified identical"| CP
  N4J --> CP
  CP <--> CO
  PLAT -.-> AU
  CP -.-> AU
```

### How the data flows

```mermaid
flowchart LR
  L["landing<br/>(object store)"] -->|"fingerprint<br/>per record"| B["bronze_raw<br/>original text + lineage"]
  B -->|"country scopes<br/>ALL · MX · CO · AR"| T["silver typed<br/>schema-drift breaker"]
  T --> Q["silver quality<br/>flags, holds,<br/>four-eyes corrections"]
  Q --> C["silver conformed<br/>FX to USD · clocks −6/−8 h"]
  C --> K["gold core<br/>8 dims · 5 facts"]
  K --> M["gold marts<br/>card support · disputes ·<br/>eligibility · AML · CX"]
  K --> A["aggregates<br/>33 models, contract-tested"]
  M --> S["serving<br/>7 published contracts"]
  K --> F["features · graph ·<br/>privacy (DP inputs)"]
  S -->|"digest-checked swap"| P[("Postgres<br/>bank_serving")]
```

The lakehouse has 131 dbt models, every one documented ([browse the dbt docs](https://beta-aid-dbt-docs.netlify.app)), and every layer is tested. Contracts make a renamed or retyped serving column fail the
build instead of breaking the copilot. Details: [data flows](docs/platform/02_data_flows.md) and
[ADR-017](docs/platform/adr/ADR-017.md).

### Data model

The gold core is a Kimball constellation: five facts sharing eight dimensions. Six of those dimensions are conformed
(grey), and each use-case mart is keyed back to the core.

<img src="docs/assets/star-schemas/gold_core_constellation.svg" alt="Gold core fact constellation: five facts sharing eight dimensions" width="100%">

<img src="docs/assets/star-schemas/mart_card_support.svg" alt="Star schema of mart_card_support, the mart behind the copilot" width="100%">

The bus matrix and one star per fact and per mart are in [**the data model**](docs/platform/data_model.md).

### One copilot turn

```mermaid
sequenceDiagram
  autonumber
  actor C as Card holder (ES/PT)
  participant G as Gateway + guards
  participant I as Identity
  participant N as Intent model
  participant P as Policy
  participant T as Tools
  actor A as Agent desk
  C->>G: "bloquea mi tarjeta"
  G->>G: mask card numbers · injection and cross-customer guard
  G->>I: HMAC session (step-up for actions)
  I->>N: classify (Claude only when unsure)
  N->>P: recommendation
  alt A0 · answer
    P->>T: read verified facts (serving_card_support)
    T-->>C: grounded answer
  else A2 · act after confirmation
    P-->>C: read-back, "confirm?"
    C->>T: confirm (idempotent)
    T-->>C: done + audit entry
  else A3 · a person decides
    P->>A: handoff packet (fraud, limits, disputes, complaints)
    A->>A: four eyes: a second agent approves
  end
```

The policy has three levels:
- A0: answer;
- A2: act after confirmation;
- A3: hand off.

Nine card vetoes sit on top of them, all in a versioned [`policy.yaml`](copilot/src/copilot/policy.yaml). The design is
in the [copilot README](copilot/README.md) and [ADR-019](docs/platform/adr/ADR-019.md).

### Residency by design

```mermaid
flowchart LR
  MX["Customers in Mexico"] --> RMX["beta-aid-mx<br/>northamerica-south1 · Querétaro"]
  COAR["Customers in Colombia and Argentina"] --> RSA["beta-aid-sa<br/>southamerica-east1 · São Paulo"]
  RMX -.->|"customer from the other region"| X["401 refused"]
  RSA -.-> X
  CON["Console · Netlify"] --> RMX
  CON --> RSA
```

Each regional service holds only its own countries' data. The region map mirrors
[`residency.yaml`](platform/policies/residency.yaml) ([ADR-007](docs/platform/adr/ADR-007.md),
[ADR-021](docs/platform/adr/ADR-021.md)).

## What the data taught us

The exploratory phase ([ADR-015](docs/platform/adr/ADR-015.md), [eda/README](eda/README.md)) turned up five findings
that shaped every later decision:
- **The backup folder is not a copy.** It is a second, independently generated bank. Never join it to the main data.
- **Timestamps run on delivery-day clocks:**
  - −6 h for transactions, digital events and sends;
  - −8 h for contacts and complaints ([ADR-014](docs/platform/adr/ADR-014.md)).
- **`fraud_score ≥ 35` means fraud in every case.** It is a leaked label, not a feature, and the behavioural signal
  alone carries almost none.
- **Many models are not trainable from this data.** The readiness gates turn that into a data-collection audit rather
  than a weak model ([ADR-018](docs/platform/adr/ADR-018.md)).
- **Card support has the cleanest decision data.** 140,040 cards, a rule-based next action for over 65,000 of them, and
  499 flagged for fraud review. That is why the copilot starts there.

## What is in the repository

| Area | Path | Status |
|---|---|---|
| Card-service copilot | [`copilot/`](copilot/) | ✅ Built, evaluated and deployed: policy, verified actions, handoff, RAG and GraphRAG, held-out evaluation ([README](copilot/README.md)) |
| BETA AID Console | [`console/`](console/) | 🚧 Chat simulator, agent desk and supervisor on the real copilot per region; control-plane screens being wired ([README](console/README.md)) |
| Data platform | [`platform/`](platform/) | ✅ Run end to end: lossless bronze, dbt silver to serving, Airflow 3 with country scopes, audit ledger, knowledge base, streaming features, read-only Data API ([docs](docs/platform/README.md)) |
| Governed knowledge base | [`knowledge/`](knowledge/) | ✅ Approved, versioned documents indexed in pgvector and Neo4j |
| Exploratory analysis and readiness | [`eda/`](eda/) | ✅ Dataset study, anomaly detection, grain series, country and pipeline replays, the Grain Atlas ([README](eda/README.md)) |
| Architecture decisions | [`docs/platform/adr/`](docs/platform/adr/README.md) | ✅ ADR-001 to ADR-021 |
| Strategy and research | [`docs/strategy/`](docs/strategy/README.md), [`docs/research/`](docs/research/) | 📚 The analysis that shaped the plan |
| Backend API, agent graph | `backend/`, `agents/` | 🧱 Original scaffolds; the copilot replaced them as the served application |
| Legacy dbt scaffold | `data_engineering/` | 🧱 Superseded by `platform/dbt`; the CI "dbt Tests" job still runs it |
| ML packages, monitoring, infrastructure | `ml/`, `monitoring/`, `infrastructure/` | 🧱 Scaffolds; platform ML lives in `platform/libs/latam_platform/ml`, GCP Terraform in `platform/infra` |

## Technology

| Layer | Stack |
|---|---|
| Ingestion and orchestration | S3 and MinIO (object lock), Airflow 3.1 with Cosmos, one DAG per country scope |
| Lakehouse | dbt 1.12 on DuckDB; Kimball core with SCD2 snapshots; contract-tested aggregates; BigQuery targets designed per region |
| Streaming | Redpanda, Flink 1.19 and a fraud scorer; batch and stream share one feature definition |
| Serving and knowledge | Postgres 16 with pgvector (HNSW, governed `kb.active_chunk` view), Neo4j 5, Kong gateway |
| ML and observability | MLflow, Optuna, Marquez (OpenLineage), Prometheus and Grafana; federated graph learning simulated per silo |
| Copilot | Python 3.12, FastAPI, a tuned intent model with Claude as fallback, policy as code, HMAC sessions |
| Console | TanStack Start (React), Observable Plot, Bun, Vitest |
| Deployment | Modal, Google Cloud Run per residency region, Netlify; Terraform for GCP |
| Quality | pre-commit (ruff, mypy, detect-secrets), Conventional Commits with commitizen, GitHub Actions |

## Quick start

Prerequisites: Python 3.11+, [uv](https://docs.astral.sh/uv/), Docker and Make. Data never enters git; see
[data and secrets](docs/development/data-and-secrets.md).

```bash
make setup                         # root env + pre-commit and commit-msg hooks

# the copilot
make copilot-setup && make copilot-test
make copilot-snapshot              # demo snapshot from the local lakehouse (data/copilot/, git-ignored)
make copilot-dev                   # http://127.0.0.1:8000 (UI, /api, /atlas)

# the platform, by development stage (platform/docker/compose.yml profiles)
make stack-env                     # once: random secrets for the stack
make stack-copilot                 # pgvector, Neo4j, MLflow only
make stack-dev                     # full pipeline stack: Postgres, MinIO, Airflow 3, Neo4j, MLflow
make stack-stream                  # add Redpanda, Flink, the fraud scorer and Kong
make stack-obs                     # add Marquez, Prometheus and Grafana
make copilot-kb                    # bundled knowledge index, verified against pgvector and Neo4j
make copilot-eval                  # frozen challenge set and retriever comparison

# the exploratory analysis
make eda-setup && make eda-test
```

Run the `stack-*` targets from the checkout that hosts the stack, because its bind mounts are relative to that
checkout. The full runbook is in [`docs/platform/runbook.md`](docs/platform/runbook.md). Deployment needs no Docker:
- `make copilot-deploy` ships the copilot to Modal (see [`modal_app.py`](copilot/deploy/modal_app.py));
- `make copilot-deploy-gcp` ships it to Cloud Run, once per residency region.

## Dataset

<details>
<summary><b>13 tables · 23.5 M rows · 2023-06-17 → 2026-06-17 · MXN, COP, ARS and USD</b> (row counts measured; several differ from the documented sizes)</summary>

| Table | Type | Rows (measured) | Documented |
|-------|------|----------------:|-----------:|
| `customers` | Dimension | 150,000 | 150K |
| `products` | Dimension | 400,000 | 400K |
| `branches` | Dimension | 350 | 350 |
| `service_agents` | Dimension | 1,200 | 1.2K |
| `marketing_campaigns` | Dimension | 200 | 200 |
| `transactions` | Fact | 4,425,008 | 5M |
| `digital_events` | Fact | 15,620,994 | 10M |
| `call_center_interactions` | Fact | 686,296 | 800K |
| `call_transcripts` | Fact | 171,321 | 200K |
| `satisfaction_surveys` | Fact | 212,759 | 250K |
| `complaints` | Fact | 67,095 | 80K |
| `campaign_sends` | Fact | 1,746,801 | 2M |
| `daily_exchange_rates` | Reference | 13,164 | 3K |

The schema and relationships are in the [ERD](docs/dataset/erd.md), generated from the
[data dictionary](docs/dataset/LATAM_Bank_Complete_Data_Dictionary.pdf).

</details>

## How we work

The rules for people and coding agents are in [`AGENTS.md`](AGENTS.md), imported by `CLAUDE.md`. Procedures are in
[`docs/development/`](docs/development/README.md).

- **Branches:**
  - `main` is production and `develop` is integration;
  - every work branch lives in its own worktree and merges by pull request.
- **Versions:** SemVer 0.x until submission, recorded in the [`CHANGELOG.md`](CHANGELOG.md).
- **Commits:** Conventional Commits, enforced by commitizen.
- **Quality gate:** pre-commit is the single gate, locally and in CI.
- **CI** runs on pull requests into `main` and `develop`:
  - lint, format and type check;
  - unit tests, EDA tests and platform tests;
  - copilot tests and console tests;
  - integration and dbt jobs.

## Documentation

[`docs/README.md`](docs/README.md) is the index. It covers:
- the hackathon brief and the dataset;
- the [platform chapters](docs/platform/README.md) and the [21 ADRs](docs/platform/adr/README.md);
- the strategy and the original design specs;
- the research and the development guides.

## License

[MIT](LICENSE) · **Andrés Becerra** · Factored AI & Data Hackathon 2026
