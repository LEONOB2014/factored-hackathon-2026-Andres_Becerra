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
