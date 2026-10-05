# Documentation

Documentation of **BETA AID** (Banking Evolutionary Transformation and AI Deployment), built for LATAM Bank's dataset
in the Factored AI & Data Hackathon 2026. Read in this order to follow the project from data to product.

| Folder | Contents |
|---|---|
| [`hackathon/`](hackathon/) | Official challenge material: rules, scope and kickoff brief |
| [`dataset/`](dataset/) | LATAM Bank data dictionary, dataset summary, ERD and backup comparison |
| [`strategy/`](strategy/README.md) | The data, compliance and AI strategy that came out of the exploratory study (chapters 01–13) |
| [`platform/`](platform/README.md) | The data platform as built: architecture, flows, audit, privacy, knowledge base, ML, agent interfaces, runbook, evidence |
| [`platform/adr/`](platform/adr/README.md) | Architecture decisions ADR-001 to ADR-020 |
| [`development/`](development/README.md) | How we work: git workflow, releasing, data and secrets, remote compute (Modal), approved plans |
| [`specs/`](specs/) | The original design specs, written before building; each carries a note on what was built instead |
| [`research/`](research/) | Background research on LATAM banking AI, regulation and modelling |

Code-level documentation lives next to the code:
- [`copilot/README.md`](../copilot/README.md): the card copilot's design, evaluation and limits;
- [`eda/README.md`](../eda/README.md): the exploratory analysis;
- [`knowledge/README.md`](../knowledge/README.md): the governed knowledge base;
- [`platform/contracts/README.md`](../platform/contracts/README.md): the source data contracts.

## hackathon/

- `Factored_AI_Data_Hackathon_2026_Rules.pdf`: rules and specifications
- `Datathon_2026_Kickoff.pdf`: kickoff presentation

## dataset/

- `LATAM_Bank_Complete_Data_Dictionary.pdf`: field-level reference for every table
- `LATAM_Bank_Dataset_Summary.pdf`: high-level overview of the dataset
- `erd.md`: entity relationship diagram (Mermaid), generated from the dictionary by `eda/scripts/generate_erd.py`
- `backup_comparison.md`: what the `data_backup_20260831/` folder is and why it must not be joined to the main data

## strategy/

Thirteen chapters, written after the exploratory study and before the platform was built:
- evidence synthesis;
- compliance by country;
- architecture;
- SCD and record integrity;
- dbt;
- denormalised tables;
- graph and foundation models;
- ML, DL and agents;
- deployment;
- roadmap;
- plan evaluation;
- development path;
- the data-readiness audit.

They are the record of the reasoning. Where the platform departed from them, the ADRs say so.

## platform/

Chapters 00–09:
- plan;
- architecture;
- data flows;
- data split;
- audit and lineage;
- privacy and compliance;
- knowledge and GraphRAG;
- ML and graph learning;
- agentic interfaces, now implemented by the copilot;
- data and model risk methodology.

Also in this folder: the runbook, generated dbt lineage, and the evidence folders with the scripts that reproduce
each claim.

## development/

- `git-workflow.md`, `releasing.md`, `data-and-secrets.md`: the procedures behind [`AGENTS.md`](../AGENTS.md)
- `modal.md`: remote compute on Modal
- `plans/`: approved implementation plans

## specs/

Written at the start of the hackathon as the target design. They are kept unchanged as the record of intent; a status
note at the top of each says what was built and where.

- `PRODUCT_SPEC.md`: product scope and user stories
- `DATA_ENGINEERING_SPEC.md`: ingestion, medallion layers, dbt models
- `ML_SPEC.md`: models, training and serving
- `AGENT_SPEC.md`: agent graph, tools, RAG and evaluations

## research/

- `AI Banking Data Solutions.md`: analytics and AI blueprint over the dataset's 13 tables
- `AI Governance in LatAm Banking.md`: governance, architecture and risk, including the EU AI Act
- `GNNs in Banking Sector.md`: graph learning architectures for fraud and risk
- `LATAM Banking AI Regulations Report.md`: country-by-country legal frameworks
- `LATAM Fintech AI Regulations.md`: fintech regulation across eleven jurisdictions
