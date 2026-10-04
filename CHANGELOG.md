# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/) (0.x until the hackathon submission).
Entries are generated from Conventional Commits by commitizen; see
[docs/development/releasing.md](docs/development/releasing.md).

## v0.2.0 (2026-10-04)

### Highlights

- **Compliance-grade data platform.** Lossless bronze with a byte-exact completeness proof; silver typed against
  reviewed source contracts, behind a circuit breaker; four-eyes data corrections with human approval; a gold Kimball
  core and ten use-case marts; features, graph, knowledge, privacy and serving layers; an audit layer; Airflow 3 +
  Cosmos, Flink streaming and a real-time fraud scorer; reproducible gold across builds. See `docs/platform`.
- **The analyses that judged it.** The dbt DAG replayed step by step without Airflow (`eda/notebooks/pipeline`); the
  platform rebuilt per country and for the whole bank (`country_*`); the quarantined backup run as if it were the
  source (`backup_*`, `dataset_compare`). They found six defects that passed every test, showed that contracts and
  SLOs must be country-keyed, that only dormancy is learnable today, and that no control notices data that never
  arrives.
- **The development path.** `docs/strategy/12_development_path.md` and ADR-011 to ADR-013 turn that evidence into the
  build plan for analytics, data marts, ML, deep learning and agents, with the exit criteria of v0.3.0.

### Upgrade notes

- Surrogate keys change once: rebuild gold, serving and publish together (see BREAKING CHANGE).
- The EDA reads the dataset from `<repo>/data` (or `LATAM_EDA_DATA`). The scoped EDA series keep their scratch in
  `data/tmp/<dataset>/<scope>/`, configurable with `LATAM_SCOPE_DIR` (replaces `LATAM_COUNTRY_DIR`).

### BREAKING CHANGE

- `customer_sk` and `product_sk` values change once: they were `md5(id || snapshot time)` and are now
  `md5(id || version_no)`. Anything that stored them must reload; gold, serving and publish rebuild together.
- `eda/data` is no longer read by default: move the dataset to `<repo>/data` or set `LATAM_EDA_DATA`.

### Feat

- **eda**: run the backup as main and compare it with main
- **eda**: add whole-bank scope and backup-as-main dataset to the template
- **eda**: rebuild and judge the platform country by country
- **eda**: replay the dbt_lakehouse DAG in a scratch DuckDB
- **eda**: execute the correction workbench on a corrected build
- **eda**: add the correction workbench notebook
- **airflow**: add dq_correction_review with human approval
- **platform**: add the four-eyes data-correction library
- **dbt**: overlay approved corrections on lossless bronze in silver
- **airflow**: raise drift reviews and retire the typed bronze build
- **dbt**: type silver from lossless bronze against the source contracts
- **dbt**: add reviewed source contracts seeded from the raw forensics
- **airflow**: build, verify and seal lossless bronze in bronze_build
- **bronze**: add lossless bronze of record with a completeness proof
- **bronze**: add a quote-aware record splitter with byte-exact rebuild
- **eda**: add the raw schema forensics notebook and contracts
- **eda**: add raw CSV schema forensics and change detection
- **eda**: make the raw tables profile fully interactive
- **eda**: add raw tables profile notebook
- **eda**: add table profiling helpers and matplotlib theme
- **infra**: add GCP Terraform for per-country residency deployment
- **stream**: add Flink features, fraud scorer and stream demo DAG
- **airflow**: add ingestion, lakehouse, serving and compliance DAGs
- **kb**: add governed knowledge base and GraphRAG sync
- **privacy**: add OpenDP count releases with budget ledger
- **audit**: add audit ledger, GenAI audit and PII guard libraries
- **dbt**: add gold core, governance gates and BigQuery targets
- **warehouse**: add use-case marts, PIT tests and ML exports
- **warehouse**: add dbt staging, SCD2 snapshots and audit layer

### Fix

- **dbt**: make gold reproducible across builds
- **verify**: combine hashes by sum, not XOR, when comparing builds
- **bronze**: check that the typed-bronze archive really is read-only
- **airflow**: import UTC inside the external-python tasks
- **bronze**: verify lossless bronze one stored partition at a time
- **eda**: calibrate change detection on the real raw data
- **eda**: never drop or silently re-type rows when building Parquet
- **docker**: run the platform stack from a worktree (#11)
- **eda**: treat time-of-day columns as categories
- **eda**: let plotly axes grow their margin to fit long labels
- **eda**: count no placeholders in an all-null text column
- **flink**: stop the planner merging the 7-day window into 24 h
- **stream**: flush watermarks, checkpoint to disk, fresh topics
- **airflow**: run dbt with absolute paths and bounded workers
- **docker**: start Airflow, MLflow and Neo4j cleanly

### Refactor

- **bronze**: let partition digests use a given column
- **dbt**: serve recent transactions as rows, not nested lists
- **platform**: restructure into a medallion lakehouse
- **eda**: read the dataset from the repository data folder

### Perf

- **bronze**: build facts month by month in a spillable DuckDB

## v0.1.0 (2026-10-03)

### Feat

- **eda**: add executed notebooks and their HTML exports
- **eda**: read the dataset location from LATAM_EDA_DATA
- **eda**: add D3 dashboards for overlap, time shift and anomalies
- **eda**: add notebook 11 (evaluation and report)
- **eda**: add notebook 10 (method comparison and consensus)
- **eda**: add notebook 09 (deep and supervised detectors)
- **eda**: add notebook 08 (ML anomaly detectors)
- **eda**: add notebook 07 (classical anomaly detection)
- **eda**: add notebook 06 (statistical equivalence)
- **eda**: add notebook 05 (comparison of comparable rows)
- **eda**: add notebook 04 (alignment and record linkage)
- **eda**: add notebook 03 (time-shift diagnostics)
- **eda**: add notebook 02 (inventory and set difference)
- **eda**: add notebook tooling and notebook 01 (data understanding)
- **eda**: add first-pass comparison of backup and main data
- **eda**: add dataset overview script and initial report
- **eda**: add S3 bucket inventory and download scripts

### Fix

- **eda**: make notebook 06 reproducible
- **eda**: make samples and rankings reproducible
- **eda**: flag foreign transactions of non-Mexican customers
- **ci**: stop the eval job filling the runner's disk
- **ci**: gate at step level, not with job-level hashFiles
- **db**: correct invalid GRANT in init_db.sql
- **ci**: create database schemas before running dbt
- **build**: make the editable install work at all
- **agents**: resolve ruff and mypy errors blocking pre-commit

### Refactor

- **eda**: make the pipeline scripts importable and testable
- **agents**: use StrEnum for the str-valued enums
