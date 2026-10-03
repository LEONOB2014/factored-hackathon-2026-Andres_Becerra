# Data and secrets

## Data

Nothing under `data/` is ever committed. The dataset is about 10 GB of raw CSVs plus
derived Parquet and DuckDB files; everything generated is reproducible from the scripts in
the repository.

**Where it lives.** One shared `data/` folder in the main checkout (`antigravity/data`).
Worktrees symlink to it (`ln -s ../../antigravity/data data`), so every branch reads the
same files without copying them. The root `.gitignore` ignores `/data` (no trailing slash,
so the symlink is ignored too).

**How code finds it.** Through environment variables with repository-relative defaults,
never hardcoded machine paths:

| Variable | Used by | Default |
|---|---|---|
| `LATAM_EDA_DATA` | `eda/` (code, scripts, tests) | `<repo>/data` |

**Getting it.** `eda/scripts/download_s3.py` downloads the bucket into `data/raw`
(resumable, size-checked) with the AWS credentials from `.env`; the conversion scripts and
notebooks rebuild everything else. On macOS, `cp -cR` clones an existing copy on the same
APFS volume without using extra disk.

**Committed exceptions.** Small, reviewed outputs only: `eda/reports/tables/*.csv`, figures,
executed notebooks and their HTML exports, dbt seeds. Anything over 1 MB is refused by the
`check-added-large-files` hook unless explicitly excluded with a reason.

## Secrets

| File | Holds | Created from |
|---|---|---|
| `.env` (root) | app keys (LLM providers, databases) and the dataset download credentials | `.env.example` |
| `eda/.env` (optional) | overrides for the EDA scripts | — |

Rules:

- `.env*` files are git-ignored (except `*.example`) and kept with mode `600`.
- Never print, log, paste or commit a secret value. Refer to secrets by variable name.
- Every new key is added to the matching `.env.example` with an empty or fake value.
- `detect-secrets` scans every commit against `.secrets.baseline`. When it flags something,
  confirm it is a placeholder or a hash, then ask the maintainer before updating the
  baseline or adding an exclusion. Executed notebooks and their HTML exports are excluded
  because their base64 chart data trips the detectors (approved 2026-10-02).
- A real secret that reaches a commit is rotated first, then removed from history with the
  maintainer.
