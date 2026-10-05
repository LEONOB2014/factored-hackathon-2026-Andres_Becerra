# Kumo probe

Evaluation-only probe of NVIDIA's open tabular and relational foundation models
([Kumo Tabular](https://nvidia.github.io/structured-data-models/api/generated/sdm.models.KumoTabular.html)
and
[Kumo Relational](https://nvidia.github.io/structured-data-models/api/generated/sdm.models.KumoRelational.html))
next to the hour-grain readiness gates. The models run in context. This package
never calls `train()`.

The two scenarios are the gate's quantile-2/3 models in `latam_eda.hour_models`:

| Key | Scorecard scenario | Scorecard model | Metric | Benchmark |
| --- | --- | --- | --- | --- |
| `branch_teller` | `04 branch` | teller transaction outside opening hours | AUC | base rate |
| `agent_handle` | `05 agent and queue` | handle time per agent-hour | MAE (s) | agent's own mean |

Materiality is 0.02 on both, with the gate's root causes (`data defect`, `missing field`).
The difference versus that benchmark goes through `latam_eda.granularity.readiness_verdict`
(200 bootstrap resamples, seed 2026), the same rule as
`eda/reports/tables/granularity_hour_readiness.csv`. Each probe row keeps those
scenario and model strings and adds `opinion` (`kumo tabular` or `kumo relational`)
and `n_context`.

The branch SQL is the gate's query plus `customer_id` and `branch_id`, which are
already the join keys. `open_fraction` becomes the label and is not a feature.
The flat table keeps numeric columns first, then categoricals, at most 100 columns.
Context is a reproducible sample of at most 60,000 train rows (seed 2026). The
test split is the gate's test split. The benchmark is computed on the full train
split, not on the sample.

`structured-data-models` (`import sdm`) is installed only on the GPU image, from
git, because it is not a PyPI release and it needs a CUDA GPU:

```bash
pip install git+https://github.com/NVIDIA/structured-data-models.git
```

Calls follow the docs as of 2026-10-05: `TableTensor.from_pandas`,
`KumoTabular.fit(x=, y=)` / `predict`, `RelatedTables` with the plural link keys,
and `KumoRelational.fit(x, y, related, num_hops=1)` / `predict(x, related)`.
Regression scores use `q500`. Classification scores use the positive-class column.

## Local tests (CPU, sdm mocked)

From this directory:

```bash
uv sync
uv run pytest -q
```

Do not run these tests with the repository-root pytest. That environment does not
install this project or SciPy.

## Modal (not run)

The dataset is ~27 GiB and stays on a Volume. The image does not copy `data/` or `.env`.
A CPU function builds the hour star and writes two parquet frames. An L4 function
scores them. `platform/.venv/bin/dbt` is how `latam_eda.pipeline.compile_project`
finds dbt; the CPU image installs dbt and the job symlinks it into that path.

Approve the spend, then from this directory:

```bash
modal volume create beta-aid-kumo-data
# `data/` in a worktree is a symlink. Upload the main checkout's data directory.
# The volume root is that directory's contents, mounted at /data (so data/lake is /data/lake).
modal volume put beta-aid-kumo-data /path/to/antigravity/data /
uv sync --extra modal
modal run modal_job.py
# if the large checkpoint does not fit on the 24 GiB L4:
modal run modal_job.py --size medium
```

`KUMO_QUERY_BATCH` (default 8192) slices the test split. The published scorecard
has about 41k branch test rows and about 219k agent-hour test rows.

### Cost to approve

Rates from [modal.com/pricing](https://modal.com/pricing) on 2026-10-05. Runtime
was not measured. This is a ceiling, not a quote.

| Resource | Rate | This job's request | Per hour |
| --- | --- | --- | --- |
| Nvidia L4 | $0.000222/s | one GPU | $0.80 |
| Memory | $0.00000222/GiB/s | 32 GiB on the GPU function | $0.26 |
| CPU | $0.0000131/core/s | 8 cores on the materialise function | $0.38 |
| Memory | same | 32 GiB on the materialise function | $0.26 |
| Volume | $0.09/GiB/month, first 1 TiB free | ~27 GiB | $0 |

About one hour of L4 plus memory is $1.06. About one hour of the CPU materialise
is $0.63. A first run that stays near two hours on each function is about $3.40.
Approve a ceiling of **$5** before `modal run`. Set a Modal workspace budget.
Image pull, the default 60-second scale-down, and a longer star build sit inside
that ceiling only while the wall clock stays near that envelope.

`size=large` on 60,000 context rows may run out of memory on an L4. That was not
tried. The cu124 wheel index in the image was not checked against Modal's L4 driver.
The GPU job was not run.
