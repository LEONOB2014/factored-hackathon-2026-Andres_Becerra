# Plan: make this repo the home of the data platform, with a develop → main release flow

## Context

The EDA phase is finished and merged on `main` (5 PRs). The compliance-grade data platform
(medallion lakehouse + Kimball core, Airflow 3 + Cosmos, dbt, Flink, Postgres/pgvector, Neo4j,
MLflow, full audit stack, GCP Terraform) was built elsewhere in 20 commits plus one
uncommitted dependency change, and ran end to end on 2026-10-03 (parity 0 mismatches,
`verify_chain` clean). This repo must become the single home of the project from now on:
all code, docs, plans, data and running state come here; nothing in the repo refers to the
other folder; the work lands as homologous commits; and development switches to a
professional `develop` → `main` flow driven by `AGENTS.md` / `CLAUDE.md`.

Decisions taken (maintainer answers + judgement where asked):
- **Branching**: long-lived `develop` (integration, tested) and `main` (production, release
  only). Feature branches are short-lived, start from the latest `develop`, merge back by PR.
  Releases go `develop` → `main` by PR and are tagged. (The rule text said "from the latest
  main"; that contradicts "branched from development", so `develop` is the base and only
  `hotfix/*` branches start from `main`.)
- **Worktrees**: one per branch under `../antigravity-worktrees/<type>-<desc>`; this checkout
  stays on `main` and is only ever fast-forwarded.
- **Pushes**: commit locally; every `git push` (branches and tags) waits for explicit
  maintainer approval of that push.
- **Old scaffold**: replaced by the platform in its own PR (judgement; easy to revert):
  `data_engineering/`, `infrastructure/terraform/`, duplicated compose services.
- **PRs**: standards → platform (homologous series) → integration → docs, all into `develop`
  with merge commits, branches kept; then release PR `develop` → `main`.
- **Data**: one shared, git-ignored `data/` at the root of this checkout, holding everything
  (raw, lake, models_cache, EDA parquet/derived, legacy warehouse outputs); skip only `tmp/`.
- **Versions**: SemVer 0.x until hackathon submission. `v0.1.0` = EDA phase (current `main`),
  `v0.2.0` = data platform.

## Phase 0: prepare (local, no pushes)

1. Clone the data with APFS copy-on-write into `./data/`: `raw`, `lake`, `models_cache`,
   `parquet`, `parquet_backup`, `derived`, `exports`, `warehouse.duckdb`,
   `warehouse_scd2_demo.duckdb`. Verify sizes match; remove the now-duplicate `eda/data` clone.
2. Copy the secrets (never committed): AWS download credentials into `./.env` (merged with the
   app keys), and `platform/docker/.env` with mode 600. That file must be reused, not
   regenerated: the existing Docker volumes `latam-platform_*` (pg-core, pg-audit, MinIO,
   Neo4j, Airflow config, Flink checkpoints) were initialized with those passwords and are
   reused as-is because the compose project name stays `latam-platform`.
3. Copy the platform plan into `docs/platform/00_plan.md` and this plan into
   `docs/development/plans/` (both scrubbed of machine paths).
4. Create `develop` from `main`; tag `v0.1.0` on the current `main` commit `4bfac4a`
   (annotated, "EDA phase"). **Ask approval** to push `develop` and the tag.

## PR 1: `docs/agent-standards` → develop (worktree)

Sources checked during writing: agents.md format, Claude Code memory docs (CLAUDE.md
`@AGENTS.md` import), Conventional Commits 1.0.0, SemVer 2.0.0, Keep a Changelog 1.1.0,
`git worktree` manual, GitHub docs on PRs and releases.

- `AGENTS.md` (canonical, tool-neutral). Sections: project map; setup per environment (root
  app, `eda/`, `platform/`); test/lint commands; **branching** (main/develop/feature/
  release/hotfix, `<type>/<short-description>`, under a day of work, from latest `develop`);
  **worktrees** (one per branch, the main checkout is read-only and ff-only, cleanup after
  merge, data via the shared `data/` symlink); **commits** (Conventional Commits types and
  this repo's scopes: `eda, platform, dbt, airflow, stream, flink, audit, privacy, kb, infra,
  docker, backend, agents, ml, ci, deps`, `!`/`BREAKING CHANGE:`, examples, one logical
  change per commit, message from a file); **day-to-day** (commit locally, run hooks, push only
  after approval of that push); **PRs** (title = Conventional Commit, template, base
  `develop`, green CI, merge commit vs squash rule, never delete branches); **versioning and
  releases** (0.x rules, release branch, `cz bump`, CHANGELOG, tag on main, GitHub release,
  back-merge to develop, hotfixes); **data** (never in git, shared `data/`, env vars
  `LATAM_DATA_DIR`/`LATAM_EDA_DATA`/`LATAM_LAKE_DIR`, regeneration commands); **secrets**
  (`.env` files, `bootstrap_env.py`, detect-secrets baseline policy, never print secrets);
  agent conduct (stop and ask on destructive or outward actions).
- `CLAUDE.md`: imports `@AGENTS.md` plus Claude-specific notes (plan mode for multi-file work,
  ask before every push, keep the memory up to date).
- `.github/pull_request_template.md`; `CHANGELOG.md` (generated with `cz changelog` for v0.1.0).
- `.pre-commit-config.yaml`: `no-commit-to-branch --branch main --branch develop`.
- `ci.yml`: also run on pull requests into `develop`; add a `pull_request` title check is not
  needed (commitizen guards commits).
- `.env.example`: add `AWS_*`/`S3_BUCKET` names; `README.md` workflow section points to
  `AGENTS.md`.

## PR 2: `feat/data-platform` → develop: the homologous commit series

Replayed by a script that takes each original commit's tree delta (`git show <c>:<path>`)
and writes it through a path map, then applies the adaptations below, runs the hooks
(ruff format/fix, whitespace) and commits with the original message (only path words
adjusted, e.g. `warehouse/` → `platform/dbt/`).

**Path map**: `warehouse/**` → `platform/dbt/**` (adapting `../data` → `../../data`);
`platform/**`, `knowledge/**`, `docs/platform/**`, `docs/strategy/**` → same;
`scripts/*` → `eda/scripts/`; `reports/**` → `eda/reports/**`; `docs/erd.md` →
`docs/dataset/erd.md`; root `pyproject.toml`/`uv.lock` → `platform/pyproject.toml` (own uv
project, Python 3.12, hatchling, package `libs/latam_platform`, CPU torch on Linux like
`eda/`); `.gitignore` entries → root `.gitignore` (plus `!platform/dbt/seeds/*.csv`);
root `README.md` rows → `eda/README.md`; `main.py`, `CLAUDE.md`, `.githooks` → not ported.

**Adaptations**: in-content paths `scripts/`, `notebooks/`, `reports/`, `src/latam_eda`
→ `eda/...`; `landing_ingest` calls `/opt/latam/eda/scripts/download_s3.py`;
`warehouse_validation.py` resolves the repo root; `eda/tests/test_notebook_sources.py`
accepts `warehouse_*.csv` produced by that script; root ruff gets `platform/**`
per-file-ignores (same style as `eda/**`) and `latam_platform` as first-party; any
detect-secrets findings are checked one by one and, if they are placeholders, listed for
maintainer approval before the baseline changes.

**Commits** (original order and messages):

0. `refactor(eda): read the dataset from the repository data folder` (prerequisite: EDA
   default `eda/data` → `<repo>/data`, scrub the two existing references to the other folder)
1. `build: add dbt-core and dbt-duckdb` (creates `platform/pyproject.toml`)
2. `feat(warehouse): add dbt staging, SCD2 snapshots and audit layer`
3. `feat(warehouse): add use-case marts, PIT tests and ML exports`
4. `docs(strategy): add next-phase data, compliance and AI strategy`
5. `refactor(platform): restructure into a medallion lakehouse`
6. `feat(dbt): add gold core, governance gates and BigQuery targets`
7. `build(docker): add compartmentalized local platform stack`
8. `feat(audit): add audit ledger, GenAI audit and PII guard libraries`
9. `feat(privacy): add OpenDP count releases with budget ledger`
10. `feat(kb): add governed knowledge base and GraphRAG sync`
11. `fix(docker): start Airflow, MLflow and Neo4j cleanly`
12. `feat(airflow): add ingestion, lakehouse, serving and compliance DAGs`
13. `perf(bronze): build facts month by month in a spillable DuckDB`
14. `feat(stream): add Flink features, fraud scorer and stream demo DAG`
15. `feat(infra): add GCP Terraform for per-country residency deployment`
16. `docs(platform): add architecture, flows, audit, privacy and ADRs`
17. `docs: point strategy and README at the platform layout`
18. `fix(airflow): run dbt with absolute paths and bounded workers`
19. `refactor(dbt): serve recent transactions as rows, not nested lists`
20. `fix(stream): flush watermarks, checkpoint to disk, fresh topics`
21. `fix(flink): stop the planner merging the 7-day window into 24 h`
22. `docs(platform): record end-to-end run results and fixes`
23. `build(platform): add torch-geometric for the TGN module` (the uncommitted change)
24. `docs(strategy): fix lake paths in the graph chapter and the reproduce block` (brace paths
    in `07_graph_and_foundation_models.md`, `cd ../..` in `docs/strategy/README.md`)
25. `docs(platform): add the platform plan` (`docs/platform/00_plan.md`)

## PR 3: `chore/platform-integration` → develop

- `ci`: new `test-platform` job (`uv sync --locked` in `platform/`, `pytest libs/tests`
  (Postgres tests skip), `dbt parse --target ci` + `latam_platform.cli governance-check`);
  `terraform fmt -check` + `validate -backend=false` for `envs/{mx,br,latam-shared}`; drop
  the Postgres `test-dbt` job.
- `chore`: retire `data_engineering/` and `infrastructure/terraform/`; root
  `docker-compose.yml` keeps the app (`api`, `redis`) and joins the platform network; fix
  `make up` (no `frontend`); Makefile `platform-*` targets (`up`, `bootstrap`, `test`,
  `dbt-build`, `tf-validate`); compose binds `${LATAM_HOST_DATA_DIR:-../../data}` so a
  worktree can use the shared data.
- `ci`: scope sqlfluff to `platform/dbt` with the DuckDB dialect if it passes cleanly;
  otherwise remove it with the reason in the commit.
- `test(airflow)`: let the DAG integrity tests take the DAG folder from an env var so they
  run outside the container too.

## PR 4: `docs/platform-docs` → develop

Root `README.md` (status table, real architecture diagram, platform quick start, data and
release sections), `docs/README.md` (platform, strategy, development, knowledge),
`docs/specs/DATA_ENGINEERING_SPEC.md` and `ML_SPEC.md` (notes pointing at the ADRs that
supersede Spark, Delta and Kafka), `eda/README.md` (shared data folder), runbook paths
for worktrees.

## Release: `release/v0.2.0` → main

From `develop`: `cz bump --increment MINOR` (pyproject version + CHANGELOG), PR into `main`
(merge commit); after merge tag `v0.2.0` on `main`, publish a GitHub release from the
changelog section, and open `chore/sync-main` → `develop` so `develop` carries the release
commit. Each push still asks for approval.

## Verification

- On each commit of the series: all hooks pass, including `eda-tests`.
- After PR 2, in the `develop` worktree with the shared data: `uv run pytest` in `eda/` (all
  markers) and `platform/` (26 library tests with `pg-core` up); `dbt parse` and
  governance-check; `terraform validate` for the three environments.
- Stack: `docker compose --profile core --profile graph --profile ml --profile stream
  --profile obs up -d` from the `develop` worktree reuses the existing volumes; Airflow lists
  16 DAGs; the DAG integrity tests (19) pass in the scheduler; `verify_chain` reports 0
  problems; the `dbt_lakehouse` and `stream_demo` DAGs rerun green with 0 parity mismatches.
- Repo hygiene: no references to the previous working folder and no absolute host paths.
- CI green on every PR into `develop` and on the release PR.

## Not in scope / follow-ups

Earlier commit messages and PR bodies that already name the other folder stay in history
(rewriting `main` would need a force push); I can edit the PR descriptions on GitHub if
wanted. Branch protection and rulesets wait until the repo goes public.
