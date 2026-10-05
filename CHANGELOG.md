# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/) (0.x until the hackathon submission).
Entries are generated from Conventional Commits by commitizen; see
[docs/development/releasing.md](docs/development/releasing.md).

## v0.3.0 (2026-10-05)

### Highlights

- **The exploratory and evaluation phase is closed.** The platform built for v0.2.0 was used as an instrument: every
  data mart was re-grained to the units a bank decides on, and its predictive power was judged in search of a
  solvable problem.
- **Granularity series I** (`eda/notebooks/granularity`). An aggregate star of 17 models at customer, day, branch,
  agent, product, campaign and case grain, checked by 43 contracts. Dormancy turns out to be an exposure law
  (c·r^k in products held), not behaviour. Campaigns are the only grain with a decision attached.
- **Granularity series II** (`granularity_time`).
  - **The clock.** The source runs on delivery-day clocks: −6 h for transactions, digital events and sends; −8 h for
    contacts and complaints ([ADR-014](docs/platform/adr/ADR-014.md)). The earlier "Argentine Monday" was an artefact
    of legal local time.
  - **Campaigns.** Voice and WhatsApp cannot attribute conversions. A channel-mix policy converts +22 % at the same
    number of contacts in an out-of-time replay.
- **Granularity series III** (`granularity_hour`): every fact table at the hour, with the dimensions the hour needs.
  - Eleven candidate models were trained whatever the signal: 0 green, 2 amber, 9 red under one readiness gate.
  - Three data defects only the hour can see: teller hours, agent shifts, and the SLA flag.
  - [Strategy chapter 13](docs/strategy/13_data_readiness_audit.md) turns the red gates into an audit of the data
    collection process. `eda/scripts/readiness_check.py` re-judges every model when new data arrives.
- **Next.** v0.4.0 starts spec-driven development, with the P0 platform work of strategy chapter 12 (§12.7–§12.8).
  Training moves to GPU compute ([docs/development/modal.md](docs/development/modal.md)).

### Upgrade notes

- No breaking change. The hour star is built with `granularity.open_star(pl, [SQL_DIR_TIME, SQL_DIR_HOUR])`.
- The day-grain aggregates now group by `process_date`, the delivery day. Calendar effects of the country series
  changed accordingly (weekends about −39 % in every market).
- CI: the Codecov upload no longer fails the unit-test job (`continue-on-error`); the tests still decide it.

### Docs and CI

- **docs**: ADR-014 *Timestamps carry an explicit clock*; strategy chapter 13 *Data readiness audit*; strategy chapter
  12 E13–E16; the Modal remote compute plan.
- **ci**: keep a Codecov outage from failing the unit tests job.

### Feat

- **eda**: add granularity series III, the bank at the hour
- **eda**: add the hour-grain star, readiness gates and the data audit
- **eda**: add granularity series II, the clock and the campaign cell
- **eda**: measure the delivery-day clock and add the hour and cell star
- **eda**: judge every grain of the re-grained star for value
- **eda**: add an aggregate star re-grained to the bank's decision units

### Fix

- **eda**: re-run the scoped and granularity series on the business clock

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
