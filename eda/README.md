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
| `src/latam_eda/` | Shared code: DuckDB loader, chart theme, anomaly features | yes |
| `notebooks/` | Numbered notebook series; `# %%` `.py` sources plus executed `.ipynb` | yes |
| `scripts/` | Download, CSV → Parquet, backup build, notebook builder, dashboard export | yes |
| `tests/` | pytest suite (see Tests below) | yes |
| `reports/notebooks/` | HTML export of each notebook | yes |
| `reports/dashboards/` | Interactive D3 dashboards (overlap, time shift, anomalies) | yes; `data/` is regenerated |
| `reports/figures/` | Static PNG charts | yes |
| `reports/tables/` | Summary CSVs the final report reads | yes |
| `reports/eda_overview.md` | Initial EDA of the main data | yes |
| `data/` | Raw download, Parquet, backup Parquet, derived tables, DuckDB file | no |

The ERD and the backup-vs-main summary are reference docs, so they live with the
data dictionary in [`docs/dataset/`](../docs/dataset/).

## Notebook series

Keep one flat, numbered series; the number range shows the topic.

| Range | Topic |
|---|---|
| 01 | Business and data understanding (EDA) |
| 02–06 | Backup vs main: set difference, time shift, record linkage, comparable rows, statistical equivalence |
| 07–10 | Anomaly detection: classical, ML, deep and supervised, method consensus |
| 11 | Evaluation and final report |

Edit the `.py` source, then rebuild the `.ipynb` and HTML with
`scripts/build_notebook.py`. Notebooks import shared code from `../src`.

## Reproduce

Run from this folder:

```bash
uv sync
uv run scripts/download_s3.py                 # AWS credentials in eda/.env (git-ignored); ~10 GB into data/raw
uv run scripts/eda_overview.py                # CSV → data/parquet + reports/eda_overview.md
uv run scripts/build_backup_parquet.py        # data/parquet_backup
uv run scripts/build_notebook.py notebooks/03_time_shift_diagnostics.py --execute
uv run scripts/export_dashboard_data.py       # after notebooks 02–10
uv run scripts/generate_erd.py                # writes docs/dataset/erd.md
```

### Where the data lives

Everything reads `data/` here by default. To use a copy elsewhere, set
`LATAM_EDA_DATA` (e.g. `export LATAM_EDA_DATA=../../s3_preview/data`); the
shared code, the scripts and the tests all honour it. On macOS, `cp -cR` clones
an existing copy without using extra disk space.

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
