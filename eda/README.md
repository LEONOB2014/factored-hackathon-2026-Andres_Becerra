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

The interactive explorers in 01 need a live kernel (`uv run jupyter lab`); the HTML export
shows the static figures only. Execution takes about a minute and ~6 GB of RAM.

Edit the `.py` source, then rebuild the `.ipynb` and HTML with
`scripts/build_notebook.py`. Notebooks import shared code from `../src` (`../../src` in
`medallion/`).

## Reproduce

Run from this folder:

```bash
uv sync
uv run scripts/download_s3.py                 # AWS credentials in eda/.env (git-ignored); ~10 GB into data/raw
uv run scripts/eda_overview.py                # CSV → data/parquet + reports/eda_overview.md
uv run scripts/build_backup_parquet.py        # data/parquet_backup
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
