# Documentation

| Folder | Contents |
|---|---|
| [`hackathon/`](hackathon/) | Official challenge material — rules, scope and kickoff brief |
| [`dataset/`](dataset/) | LATAM Bank data dictionary, dataset summary, ERD and backup comparison |
| [`specs/`](specs/) | Our own design specs (product, data engineering, ML, agents) |
| [`research/`](research/) | Background research on LATAM banking AI, regulation and modelling |

Exploratory data analysis (notebooks, scripts, reports) lives in [`../eda/`](../eda/).

## hackathon/

- `Factored_AI_Data_Hackathon_2026_Rules.pdf` — rules and specifications
- `Datathon_2026_Kickoff.pdf` — kickoff presentation

## dataset/

- `LATAM_Bank_Complete_Data_Dictionary.pdf` — field-level reference for every table
- `LATAM_Bank_Dataset_Summary.pdf` — high-level overview of the dataset
- `erd.md` — entity relationship diagram (Mermaid), generated from the dictionary by `eda/scripts/generate_erd.py`
- `backup_comparison.md` — what the `data_backup_20260831/` folder is and why it must not be joined to the main data

## specs/

- `PRODUCT_SPEC.md` — product scope and user-facing requirements
- `DATA_ENGINEERING_SPEC.md` — ingestion, medallion layers, dbt models
- `ML_SPEC.md` — models, training and serving
- `AGENT_SPEC.md` — agent graph, tools, RAG and evals

## research/

- `AI Banking Data Solutions.md` — analytics and AI blueprint over the dataset's 13 tables
- `AI Governance in LatAm Banking.md` — governance, architecture and risk, incl. the EU AI Act
- `GNNs in Banking Sector.md` — graph learning architectures for fraud and risk
- `LATAM Banking AI Regulations Report.md` — country-by-country legal frameworks
- `LATAM Fintech AI Regulations.md` — fintech regulation across eleven jurisdictions
