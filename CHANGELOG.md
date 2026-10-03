# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/) (0.x until the hackathon submission).
Entries are generated from Conventional Commits by commitizen; see
[docs/development/releasing.md](docs/development/releasing.md).

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
