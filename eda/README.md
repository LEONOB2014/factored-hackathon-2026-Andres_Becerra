# Exploratory data analysis

Exploration of the LATAM Bank dataset: initial EDA of the main data, a CRISP-DM
study comparing the main dataset (`data/`) with the `data_backup_20260831/`
folder, and anomaly detection over both.

This folder is a self-contained project with its own environment, separate from
the root `pyproject.toml`, so its heavy dependencies (torch, pyod, ruptures,
duckdb) stay out of the app and CI installs.

## Layout

| Path | Contents | In git |
|---|---|---|
| `src/latam_eda/` | Shared code: DuckDB loader, chart theme, table profiling, anomaly features | yes |
| `notebooks/` | Numbered notebook series; `# %%` `.py` sources plus executed `.ipynb` | yes |
| `notebooks/medallion/` | Medallion re-analysis series (raw → bronze → silver → gold) | yes |
| `notebooks/model_risk/` | Model-risk series: raw schema forensics, then keys, drift MRM, segmentation, text | yes |
| `notebooks/pipeline/` | Pipeline walkthrough: the `dbt_lakehouse` DAG replayed step by step in a scratch DuckDB | yes |
| `notebooks/country_{all,mx,co,ar}/` | Country series: the whole platform rebuilt and judged on the whole bank or one country (generated from `country_template/`) | yes |
| `notebooks/backup_{all,mx,co,ar}/` | Backup-as-main series: the same template on `data_backup_20260831` treated as the production source | yes |
| `notebooks/country_compare/` | The three country series side by side | yes |
| `notebooks/dataset_compare/` | Main against the backup run as main, per scope | yes |
| `notebooks/granularity/` | Granularity experiment: the star re-grained (customer, day, branch, agent, product, campaign, case) and judged grain by grain | yes |
| `notebooks/granularity_time/` | Granularity series II: the clock each process runs on, the hour grain, sub-day sequences, and the campaign decision cell with an allocation replay | yes |
| `reports/contracts/` | Inferred, versioned schema contract per table (from the raw text) | yes |
| `scripts/` | Download, CSV → Parquet, backup build, notebook builder, dashboard export | yes |
| `tests/` | pytest suite (see Tests below) | yes |
| `reports/notebooks/` | HTML export of each notebook | yes |
| `reports/dashboards/` | Interactive D3 dashboards (overlap, time shift, anomalies) | yes; `data/` is regenerated |
| `reports/figures/` | Static PNG charts | yes |
| `reports/tables/` | Summary CSVs the final report reads | yes |
| `reports/eda_overview.md` | Initial EDA of the main data | yes |
| `../data/` | Raw download, Parquet, backup Parquet, derived tables (repository-level, shared with the data platform) | no |

The strategy for the next phases (compliance, architecture, SCD, dbt, ML/AI/agents,
deployment) is in [`docs/strategy/`](../docs/strategy/README.md); the dbt project it
builds on is the data platform in `platform/` (architecture, flows, audit and ADRs in
[`docs/platform/`](../docs/platform/README.md)); its dbt lakehouse writes
`data/lake/lakehouse.duckdb` (refresh `reports/tables/warehouse_*.csv` with
`uv run scripts/warehouse_validation.py` after a dbt build).

The ERD and the backup-vs-main summary are reference docs, so they live with the
data dictionary in [`docs/dataset/`](../docs/dataset/).

## Notebook series

Two numbered series, each without gaps. The main-vs-backup study is the flat series in
`notebooks/`; the number range shows the topic.

| Range | Topic |
|---|---|
| 01 | Business and data understanding (EDA) |
| 02–06 | Backup vs main: set difference, time shift, record linkage, comparable rows, statistical equivalence |
| 07–10 | Anomaly detection: classical, ML, deep and supervised, method consensus |
| 11 | Evaluation and final report |

### Medallion re-analysis (`notebooks/medallion/`)

The data followed through the platform's layers, one notebook per layer, each judged
against the one before. Exact statistics come from DuckDB over the full tables; views that
need pandas use a reproducible 200k-row sample; PII is profiled by shape only.

| # | Layer | Status |
|---|---|---|
| 01 | Raw: complete profile of the 13 Parquet tables (types, nulls vs disguised missing, distributions, associations, time, referential integrity, banking views, ipywidgets explorers, findings) | done |
| 02 | Bronze: what ingestion changed | planned |
| 03 | Silver: did conformance fix the raw findings | planned |
| 04 | Gold: Kimball facts and dimensions reconciled with raw totals | planned |

The six interactive explorers in 01 (column, cross-matrix, number by category, time, scatter,
SQL slice) need a live kernel (`uv run jupyter lab`); the HTML export shows the other charts,
which are interactive Plotly too. `uv run pytest -m notebooks -k explorers` drives every
explorer through all tables and options (about 6 minutes). Execution takes about a minute and ~6 GB of RAM.

Edit the `.py` source, then rebuild the `.ipynb` and HTML with
`scripts/build_notebook.py`. Notebooks import shared code from `../src` (`../../src` in
`medallion/`).

### Model-risk series (`notebooks/model_risk/`)

Methodology in [`docs/platform/09_data_and_model_risk_methodology.md`](../docs/platform/09_data_and_model_risk_methodology.md).

| # | Topic | Status |
|---|---|---|
| 01 | Raw schema forensics: the schema inferred from the raw CSV text, file by file (L0–L4), change detection with permutation-calibrated tests, positive controls (synthetic mutations and the backup copy), propagation audit of the typed copies, inferred contracts | done |
| 02+ | Keys and source systems, drift and concept-drift MRM, segmentation, text | planned |

Notebook 01 reads cached fingerprints; build them first:

```bash
uv run scripts/raw_schema_scan.py        # every raw file of both copies, ~10 min, resumable
uv run scripts/mutate_partitions.py      # detector scorecard from ten injected schema changes, ~3 min
uv run scripts/build_notebook.py notebooks/model_risk/01_raw_schema_forensics.py --execute \
    --html-dir "$PWD/reports/notebooks/model_risk"
```

### Pipeline walkthrough (`notebooks/pipeline/`)

The `dbt_lakehouse` Airflow DAG replayed without Airflow: `src/latam_eda/pipeline.py` asks dbt to compile the
project (`dbt compile`, no runs), then executes every compiled statement in a scratch DuckDB
(`data/tmp/pipeline/lakehouse.duckdb`) in the DAG's task-group order, runs the data tests after each group, and stops
between steps to inspect the result. The live lakehouse and the shared lake are never written (external models
become tables in the scratch database).

| # | Topic | Status |
|---|---|---|
| 01 | Orchestration, compilation, lineage, seeds; the forward-dependency defect | done |
| 02 | Lossless bronze → typed silver: contracts, cell findings, the correction overlay | done |
| 03 | The quality gate: profiles, schema drift, the circuit breaker and a what-if simulator | done |
| 04 | Staging: vocabulary joins, timestamps, row hashes, the restricted zone | done |
| 05 | Conformed silver: FX, imputation, direction, flags, the monthly grid | done |
| 06 | Snapshots and the gold core: SCD2, surrogate keys, the star schema | done |
| 07 | Service marts: customer 360, inquiries, cards, disputes, CX | done |
| 08 | Risk and growth marts: credit, collections, AML, campaigns | done |
| 09 | Features: point in time, out-of-time splits, leakage guards | done |
| 10 | Graph and knowledge exports | done |
| 11 | Privacy inputs (DP bounding) and serving tables | done |
| 12 | Audit, the three gates, fidelity against Airflow, prioritised findings | done |

Run the notebooks in order (each builds its part on top of the previous ones; one run alone builds whatever is
missing first). Needs `uv sync` in `platform/` (for dbt), about 6 GB free in `data/tmp/`, and no Airflow dbt run
writing at the same time. The whole platform builds in about four minutes:

```bash
for nb in notebooks/pipeline/[0-9][0-9]_*.py; do
  uv run scripts/build_notebook.py "$nb" --execute --html-dir "$PWD/reports/notebooks/pipeline"
done
```

Personal data and free text are masked in every displayed table (`Pipeline.safe`, from the
`restricted_pii_columns` seed). Delete `data/tmp/pipeline/` when done; it is rebuilt by running the series again.

### Country and backup-as-main series (`notebooks/country_*`, `backup_*`, `country_compare`, `dataset_compare`)

The platform rebuilt once per country, on a lossless country subset of the lake (`src/latam_eda/country.py`:
customers by country, everything they own by `customer_id`, anonymous digital events by IP country, reference data
shared), with every decision taken on that country's data: contract baselines re-estimated on a 180-day reference
window, the business day (the delivery-day clock, ADR-014) and the country's calendar (bank holidays, paydays, month
end, bonus months), per-currency statistics, country SLOs, anomaly and change-point detection, and an out-of-time
learnability test of seven candidate targets.

The series are **generated** from one template so their method cannot drift apart: edit
`notebooks/country_template/`, never the generated folders (a test checks they match). The template has two
dimensions, eight series:

* **scope**: `ALL` (the whole bank, no cut; calendar per customer's country, country fixed effects in
  the calendar regression) or one country (`MX`, `CO`, `AR`);
* **dataset**: `main` (folders `country_*`) or `backup` (folders `backup_*`): `data_backup_20260831` run **as if it
  were main**. `country.build_backup_lake` lays the backup's lossless bronze out as a main lake in
  `data/tmp/backup/lake` (hard links, no extra space): bronze and holdout split at the stream cutoff, empty files with
  main's schema for the tables the backup lacks, main's bronze as the quarantined copy (so reconciliation runs in
  reverse), the backup's own header manifests.

Prose that only one scope or dataset should read sits in `# <ALL>`, `# <COUNTRY>`, `# <MAIN>` or `# <BACKUP>` blocks
of the template's markdown. Each series writes `{country,backup}_{all,mx,co,ar}_<kind>.csv` to `reports/tables`
(size, contract, calendar effects, profile, rule SLOs, reconciliation, anomalies, learnability); the two comparison
notebooks read only those tables.

| # | Topic |
|---|---|
| 01 | Country scope: how the lake is cut, currencies, what is shared |
| 02 | Bronze → typed: the country's contract findings and emptiness |
| 03 | Global versus country contract; reference-window baselines; noise-aware drift; PSI stability |
| 04 | The business day and the country calendar; what the calendar explains (regression with CIs) |
| 05 | Currency, conversion, imputation, incomes, the monthly grid |
| 06 | Snapshots and the gold core |
| 07 | Service marts; the country's regulatory clock for disputes |
| 08 | Risk and growth marts; AML lines and consent law of the country |
| 09 | Point-in-time features plus calendar features against the fraud label |
| 10 | Graph and knowledge |
| 11 | Privacy (cell sizes per country) and serving |
| 12 | Integrity rules against global and country SLOs; the gates |
| 13 | Abnormal days, change points, amount outliers per currency, Isolation Forest against the AML rules |
| 14 | Seven candidate targets evaluated out of time (AUC and AP with intervals, verdicts) |

```bash
uv run scripts/build_country_notebooks.py              # regenerate the eight series from the template
for s in country_all country_mx country_co country_ar backup_all backup_mx backup_co backup_ar; do
  for nb in notebooks/$s/[0-9][0-9]_*.py; do uv run scripts/build_country_notebooks.py --execute "$nb"; done
  d=${s%%_*}; rm -rf ../data/tmp/${d/country/main}/${s#*_}   # that scope's scratch, rebuilt on demand
done
for nb in notebooks/country_compare/01_country_comparison.py notebooks/dataset_compare/01_main_vs_backup.py; do
  uv run scripts/build_notebook.py "$nb" --execute --html-dir "$PWD/reports/notebooks/$(basename $(dirname $nb))"
done
```

Each scope needs `uv sync` in `platform/` and builds its lake and lakehouse in `data/tmp/<dataset>/<scope>/` (main:
about 5.5 GB for the whole bank, 3.9 GB for Mexico, 2.5 GB for Colombia, 1.8 GB for Argentina; the backup is smaller);
run one scope at a time and delete its folder when done. `LATAM_SCOPE_DIR` moves the scratch elsewhere.

### Granularity experiment (`notebooks/granularity/`)

The platform re-grained to the units a bank decides on, and judged grain by grain. An aggregate star of 17 models
(`src/latam_eda/granularity_sql/*.sql`, dbt-style SQL with `{ref}` placeholders, built by
`latam_eda.granularity.Star` on top of the gold layer of the whole-bank scratch lakehouse) declares its grain,
additive reconciliation and dense-grid contracts in each file's header; `Star.check()` tests all three.

| # | Grain | Question |
|---|---|---|
| 01 | all | bus matrix, the aggregate star, its 43 checks, zero inflation and overdispersion per grain |
| 02 | customer × month | activity Markov chain, cohorts, cross-process early warnings, five next-month targets, a contact count model |
| 03 | customer (lifetime) | value concentration, RFM, landmark survival to the first 90-day lapse (Kaplan–Meier, Cox), value proxy |
| 04 | market × day, channel × day | rolling-origin forecasts (seasonal naive, calendar regression, SARIMAX, boosting), Granger tests, control charts |
| 05 | branch × day | cash demand, branch forecasts, hierarchy (bottom-up vs top-down), newsvendor cash policy |
| 06 | agent × day, complaint case | Erlang C staffing, reliability of agent KPIs, accent fairness, censored case survival, SLA-breach classifier |
| 07 | product × month | portfolio activity, vintage curves, why roll rates are impossible, product dormancy, delinquency from payments |
| 08 | category × month, campaign × day | spend mix, campaign funnel and ROI with intervals, campaign heterogeneity, time to convert, fatigue |
| 09 | synthesis | ecological fallacy, information by grain, every test under Benjamini–Hochberg, KPI catalogue, opportunities, downstream impact, promotion decision |

```bash
for nb in notebooks/granularity/0[1-9]_*.py; do
  uv run scripts/build_notebook.py "$nb" --execute --html-dir "$PWD/reports/notebooks/granularity"; done
```

The series uses the whole-bank scratch lakehouse (`data/tmp/main/all`, about 6 GB with the aggregates); delete it
when done.

### Granularity series II (`notebooks/granularity_time/`)

Re-graining in time (the hour, the sub-day sequence) and to the unit marketing allocates budget on (the campaign
decision cell). The hour and cell aggregates live in `src/latam_eda/granularity_time_sql/` with the same header
contracts as the first series (`granularity.open_star(pl, granularity.SQL_DIR_TIME)`).

| # | Grain | Question |
|---|---|---|
| 01 | event timestamp | which clock each process was generated on: hourly profiles, a shift scan of the hour × weekday χ², the match with `process_date`, the reconciliation of the calendar effects on the legal and the delivery clock |
| 02 | market × hour | does the hour add information beyond the day (dispersion index), hourly forecasts, Erlang C on a flat and a peaked profile, Poisson and negative-binomial hourly monitors |
| 03 | event sequence | symmetric before/after windows between processes (1–72 h), burstiness against per-customer Poisson, velocity and the fraud flag |
| 04 | channel × product × objective × segment × market × month | what a conversion measures (open tracking), cell heterogeneity per funnel stage, empirical-Bayes cell rates scored out of time, expected value per send |
| 05 | synthesis | allocation policies replayed on the held-out year with bootstrap intervals, the holdout that would measure uplift, every test under Benjamini–Hochberg, KPIs, downstream impact |

**The clock.** Every process belongs to a daily delivery batch. Its business day is `process_date`, which is the
timestamp shifted −6 h (transactions, digital events, sends) or −8 h (contacts, complaints). The shift is the same in
every market, so it is not legal local time. `latam_eda.country.PROCESS_DAY_OFFSET` holds it, and
`country.utc_offset(code, clock=...)` picks the business or the legal clock (ADR-014).

```bash
for nb in notebooks/granularity_time/0[1-5]_*.py; do
  uv run scripts/build_notebook.py "$nb" --execute --html-dir "$PWD/reports/notebooks/granularity_time"; done
```

01 and 03 read the bronze lake directly (in-memory DuckDB). 02 and 04 build on the whole-bank scratch lakehouse.
05 reads the tables the other four write.

## Reproduce

Run from this folder:

```bash
uv sync
uv run scripts/download_s3.py                 # AWS credentials in the root .env; ~10 GB into ../data/raw
uv run scripts/eda_overview.py                # CSV → ../data/parquet + reports/eda_overview.md
uv run scripts/build_backup_parquet.py        # ../data/parquet_backup
uv run scripts/build_notebook.py notebooks/03_time_shift_diagnostics.py --execute
uv run scripts/build_notebook.py notebooks/medallion/01_raw_tables_profile.py --execute \
    --html-dir "$PWD/reports/notebooks/medallion"   # absolute: the build runs from the notebook folder
uv run scripts/export_dashboard_data.py       # after notebooks 02–10
uv run scripts/generate_erd.py                # writes docs/dataset/erd.md
```

### Where the data lives

Everything reads the repository-level `data/` folder by default, the same one the
data platform uses (worktrees link to it; see
[data and secrets](../docs/development/data-and-secrets.md)). To use another copy, set
`LATAM_EDA_DATA`; the shared code, the scripts and the tests all honour it. On macOS,
`cp -cR` clones an existing copy without using extra disk space.

## Tests

```bash
uv run pytest                          # everything except notebook execution
uv run pytest -m "not data"            # what CI runs: no dataset needed
uv run pytest -m data                  # against the real dataset (skips when absent)
uv run pytest -m notebooks [-k 02]     # execute notebooks, compare their tables to the committed ones
```

| Marker | Needs | Covers |
|---|---|---|
| _(none)_ | nothing | shared code, scripts on synthetic inputs, notebook sources, ERD vs dictionary, committed reports |
| `data` | dataset | schemas vs dictionary, committed findings recomputed, full script runs |
| `slow` | — | anything over a few seconds (kernels, full-data scripts) |
| `notebooks` | dataset | each notebook run end to end in a scratch copy; opt-in |

The `eda-tests` pre-commit hook runs the fast suite on every commit touching
`eda/` or `docs/dataset/`; the `test-eda` CI job runs everything that needs no
dataset. From the repo root, `make eda-test`, `make eda-test-data` and
`make eda-test-notebooks` wrap the same commands.
