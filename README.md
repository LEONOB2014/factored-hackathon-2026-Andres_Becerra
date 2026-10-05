# BETA AID

### Banking Evolutionary Transformation and AI Deployment · Factored AI & Data Hackathon 2026

> A Spanish and Portuguese customer-service copilot for LATAM Bank's card holders, built on a governed, auditable data
> platform. It answers from verified facts, acts only after the customer confirms, answers policy questions from an
> approved knowledge base with citations, and knows when to stop and hand the case to a person.

[![CI](https://github.com/LEONOB2014/factored-hackathon-2026-Andres_Becerra/actions/workflows/ci.yml/badge.svg)](https://github.com/LEONOB2014/factored-hackathon-2026-Andres_Becerra/actions/workflows/ci.yml)

**Live demo:** [aleonardobecerra--beta-aid-copilot-web.modal.run](https://aleonardobecerra--beta-aid-copilot-web.modal.run). Sign in as one of the demo customers with the test code shown on the page; the Grain Atlas is at [`/atlas`](https://aleonardobecerra--beta-aid-copilot-web.modal.run/atlas).

LATAM Bank is the hackathon's synthetic bank (Mexico, Colombia, Argentina; 13 tables). BETA AID is what we built for
it: the data platform that makes its data trustworthy, the readiness control plane that decides which models the data
can support, and the copilot that serves its customers.

## What is in the repository

| Area | Path | Status |
|---|---|---|
| Card-service copilot | [`copilot/`](copilot/) | ✅ Built and evaluated: policy, verified actions, handoff, RAG and GraphRAG, held-out evaluation, Modal deployment ([README](copilot/README.md)) |
| Data platform | [`platform/`](platform/) | ✅ Built and run end to end: lossless bronze, dbt silver, gold, aggregates and serving, Airflow 3 with country scopes, audit ledger, knowledge base, streaming fraud features ([docs](docs/platform/README.md)) |
| Governed knowledge base | [`knowledge/`](knowledge/) | ✅ Approved, versioned documents indexed in pgvector and Neo4j |
| Exploratory analysis and readiness | [`eda/`](eda/) | ✅ Closed in v0.3.0: dataset study, anomaly detection, grain series, country and pipeline replays; the Grain Atlas ([README](eda/README.md)) |
| Architecture decisions | [`docs/platform/adr/`](docs/platform/adr/README.md) | ✅ ADR-001 to ADR-020 |
| Strategy and research | [`docs/strategy/`](docs/strategy/README.md), [`docs/research/`](docs/research/) | 📚 Record of the analysis that shaped the plan |
| Backend API, agent graph | `backend/`, `agents/` | 🧱 Original scaffolds; the copilot replaced them as the served application |
| Legacy dbt scaffold | `data_engineering/` | 🧱 Superseded by `platform/dbt`; the CI "dbt Tests" job still runs this scaffold |
| ML packages, monitoring, infrastructure | `ml/`, `monitoring/`, `infrastructure/` | 🧱 Scaffolds; platform ML lives in `platform/libs/latam_platform/ml`, GCP Terraform in `platform/infra` |

## How it fits together

```
 S3 bucket ─▶ landing ─▶ bronze_raw (lossless, fingerprinted, WORM manifests)
                         │  country cut per scope: ALL · MX · CO · AR          Airflow 3 + Cosmos, one DAG per scope
                         ▼
             dbt: silver ─▶ gold (Kimball core, marts) ─▶ aggregates (day · cell · hour grains, contract-tested)
                         │                              ─▶ features · graph · knowledge · privacy · serving · audit
                         ▼
   readiness gates ─▶ Grain Atlas (control plane: which decisions the data can support)       eda/ + ADR-018/019
                         │
   serving.serving_card_support ──┐      knowledge/*.md ─▶ pgvector + Neo4j (approved, in-window only)
                                  ▼                         │
                        BETA AID card copilot  ◀────────────┘
   gateway ─▶ identity ─▶ intent (tuned model; Claude when unsure) ─▶ policy (A0 · A2 · A3) ─▶ tools ─▶ reply
                                          trace + hash-chained audit · handoff packet to a person
```

Decision rights follow RAPID:
- the model **recommends**;
- a versioned policy **agrees** or vetoes;
- tools **perform** on the session customer's own cards only;
- the serving marts and the knowledge base are the **input**;
- a person **decides** fraud, limit changes, disputes and complaints.

Details: [copilot design](copilot/README.md), [platform architecture](docs/platform/01_architecture.md),
[ADR-019](docs/platform/adr/ADR-019.md).

## Results (held out, frozen before scoring)

The copilot's challenge set, intent phrasings and retrieval questions are pinned by
[`copilot/eval/MANIFEST.sha256`](copilot/eval/MANIFEST.sha256). They were committed before the first scored run.

| Copilot, 120 ES/PT cases (deterministic path) | keyword baseline | learned model |
|---|---|---|
| Correct final outcome (Wilson 95 %) | 0.875 [0.80, 0.92] | **0.950** [0.90, 0.98] |
| Safe automated resolution, in-scope cases | 0.841 | **0.937** |
| Missed / unnecessary transfers | 4/27 · 2/63 | **1/27 · 0/63** |
| Unsafe outcomes | 1/120 | 1/120 |
| Latency per turn, p50 / p95 | 2.0 / 20.8 ms | 2.9 / 22.5 ms |

- **Intent model:** accuracy 0.818 against 0.576 for keywords, on 132 held-out phrasings and 15 intents.
- **Retrieval:** hit@3 0.94 on 28 ES/PT questions. Zero retired, superseded or expired documents were returned.
- **The one unsafe case** is a Portuguese prompt injection the guard missed. The policy routed it to a person; it is
  reported, not hidden.

Full reports: [`copilot/eval/reports/`](copilot/eval/reports/). The Claude-assisted variant is measured when an API key
is configured.

Platform evidence from the end-to-end run is in the [platform README](docs/platform/README.md#what-was-verified-on-the-running-stack-end-to-end-airflow-run-2026-10-03):
- 13 tables reconciled losslessly;
- every dbt layer green behind quality and governance gates;
- Flink and dbt streaming features in parity (0 mismatches);
- the audit chain verified.

## Quick start

Prerequisites: Python 3.11+, [uv](https://docs.astral.sh/uv/), Docker, Make. Data never enters git; see
[data and secrets](docs/development/data-and-secrets.md).

```bash
make setup                         # root env + pre-commit and commit-msg hooks

# the copilot
make copilot-setup && make copilot-test
make copilot-snapshot              # demo snapshot from the local lakehouse (data/copilot/, git-ignored)
make copilot-dev                   # http://127.0.0.1:8000 — UI, /api, /atlas

# the platform, by development stage (platform/docker/compose.yml profiles)
make stack-env                     # once: random secrets for the stack
make stack-copilot                 # pgvector, Neo4j, MLflow only
make stack-dev                     # full pipeline stack: Postgres, MinIO, Airflow 3, Neo4j, MLflow
make copilot-kb                    # bundled knowledge index, verified against pgvector and Neo4j
make copilot-eval                  # frozen challenge set and retriever comparison

# the exploratory analysis
make eda-setup && make eda-test
```

Run the `stack-*` targets from the checkout that hosts the stack: its bind mounts are relative to that checkout. The
full runbook is in [`docs/platform/runbook.md`](docs/platform/runbook.md). Deployment needs no Docker: the copilot
ships to Modal (`make copilot-deploy`, see [`copilot/deploy/modal_app.py`](copilot/deploy/modal_app.py)).

## What the data taught us

The exploratory phase ([ADR-015](docs/platform/adr/ADR-015.md), [eda/README](eda/README.md)) turned up five things
that shaped every later decision:
- **The backup folder is not a copy.** It is a second, independently generated bank: never join it to the main data.
- **Timestamps run on delivery-day clocks:** −6 h for transactions, digital events and sends; −8 h for contacts and
  complaints ([ADR-014](docs/platform/adr/ADR-014.md)).
- **`fraud_score ≥ 35` means fraud in every case.** It is a leaked label, not a feature, and the behavioural signal
  alone carries almost none.
- **Many models are not trainable from this data.** The readiness gates turn that into a data-collection audit rather
  than a model ([ADR-018](docs/platform/adr/ADR-018.md)).
- **Card support has the cleanest decision data:** 140,040 cards, a rule-based next action for over 65,000 of them,
  and 499 flagged for fraud review. That is why the copilot starts there.

## Dataset

13 tables, process dates 2023-06-17 → 2026-06-17, currencies MXN/COP/ARS/USD. Row counts are **measured** from the
main folder; several differ from the documented sizes.

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

Schema and relationships: [ERD](docs/dataset/erd.md), generated from the
[data dictionary](docs/dataset/LATAM_Bank_Complete_Data_Dictionary.pdf).

## Quality and workflow

The rules for people and coding agents are in [`AGENTS.md`](AGENTS.md), imported by `CLAUDE.md`. Procedures are in
[`docs/development/`](docs/development/README.md).

- `main` is production and `develop` is integration; work branches each live in their own worktree and merge by pull
  request.
- Versioning is SemVer 0.x until submission, with [`CHANGELOG.md`](CHANGELOG.md).
- Commits follow Conventional Commits, enforced by commitizen.
- pre-commit is the single quality gate, locally and in CI.
- CI runs on pull requests into `main` and `develop`:
  - lint, format and type check;
  - backend unit tests;
  - EDA tests;
  - platform library tests;
  - copilot tests;
  - integration and dbt jobs on the legacy scaffolds.

## Documentation

[`docs/README.md`](docs/README.md) indexes it all: the hackathon brief, the dataset, the platform chapters and ADRs, the
strategy, the original design specs, research and the development guides.

## License and author

MIT · **Andrés Becerra**, Factored AI & Data Hackathon 2026
