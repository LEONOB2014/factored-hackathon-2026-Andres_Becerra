# AGENTS.md

Instructions for coding agents (and humans) working on this repository: **BETA AID** (Banking
Evolutionary Transformation and AI Deployment), an AI customer-service copilot and the
compliance-grade data platform beneath it, built for LATAM Bank in the Factored AI & Data
Hackathon 2026. This file is the canonical source of repository standards; `CLAUDE.md`
imports it. Procedures too long for this file live in [`docs/development/`](docs/development/).

## Project map

| Path | What it is | Environment |
|---|---|---|
| `backend/` | FastAPI app (scaffold) | root `pyproject.toml`, Python 3.11+ |
| `agents/` | LangGraph orchestrator (scaffold) | root |
| `eda/` | Exploratory data analysis: notebooks, scripts, reports, tests | own uv project, Python 3.12 |
| `copilot/` | Card-service copilot (ES/PT): policy, verified actions, handoff, RAG, evaluation, Modal deploy | own uv project, Python 3.12 |
| `docs/` | Hackathon brief, dataset docs + ERD, specs, research, development guides | — |
| `ml/`, `monitoring/`, `infrastructure/`, `scripts/` | ML packages, Prometheus, Dockerfiles, DB init | root |
| `data/` | Datasets and generated artefacts, **never in git** | shared, see Data |

## Commands

```bash
make setup                       # root env (.[dev]) + pre-commit and commit-msg hooks
make test                        # backend unit tests
make eda-setup && make eda-test  # EDA env and the tests that need no dataset (what CI runs)
make copilot-setup && make copilot-test   # copilot env and its tests (what CI runs)
make stack-copilot               # only pgvector, Neo4j and MLflow (see Makefile for other stages)
make eda-test-data               # EDA tests against the real dataset
uvx pre-commit run --all-files   # the full quality gate, identical to CI
```

Run the relevant tests and the hooks before every commit. A failing hook is a real failure:
fix the cause, never bypass it (`--no-verify` is forbidden).

## Branching model

- `main`: **production**. Changes only through merged release or hotfix pull requests.
- `develop`: **integration**. Every feature lands here first and is tested here.
- Work branches are short-lived (under a day of work), named `<type>/<short-description>`
  with a Conventional Commits type and a kebab-case description:
  `feat/policy-gate`, `fix/laya-timeout`, `docs/data-contracts`, `test/dbt-unit`.
  If a tool assigns another name, keep it and follow every other rule here.
- Work branches start from the **latest `develop`** and merge back into `develop` by PR.
- `release/vX.Y.Z` starts from `develop` and merges into `main`; `hotfix/<desc>` starts from
  `main` and merges into `main`, then back into `develop`. See
  [releasing](docs/development/releasing.md).
- **Never commit on `main` or `develop`, locally or remotely.** The `no-commit-to-branch`
  hook refuses it locally; the repository is private on a free plan, so GitHub cannot
  enforce it until the repo goes public.

## Worktrees: one per branch

Every branch is checked out in its own git worktree, so branches never share a working
directory, switching is instant, and parallel work (yours or several agents') cannot collide.

```bash
git fetch origin
git worktree add -b feat/policy-gate ../antigravity-worktrees/feat-policy-gate origin/develop
cd ../antigravity-worktrees/feat-policy-gate
ln -s ../../antigravity/data data          # shared, git-ignored dataset (see Data)
```

- The main checkout (`antigravity/`) stays on `main`, is **read-only**, and is only ever
  fast-forwarded (`git pull --ff-only`). It also hosts the shared `data/` and the local
  secret files.
- Remove a worktree after its PR is merged (`git worktree remove <path>`); keep the branch.
- Details and troubleshooting: [git workflow](docs/development/git-workflow.md).

## Commits

[Conventional Commits 1.0.0](https://www.conventionalcommits.org/en/v1.0.0/), enforced by
commitizen at the `commit-msg` hook.

```
<type>(<optional scope>)<optional !>: <description>

<optional body: why, wrapped at 72 characters>

<optional footers, e.g. BREAKING CHANGE: ..., Refs: #12>
```

- **Types**: `feat` (new capability), `fix` (bug fix), `perf`, `refactor`, `docs`, `test`,
  `build` (dependencies, packaging, images), `ci`, `chore`, `style`, `revert`.
- **Scopes** (the area touched): `eda`, `dataset`, `platform`, `warehouse`, `dbt`, `bronze`,
  `airflow`, `stream`, `flink`, `audit`, `privacy`, `kb`, `strategy`, `infra`, `docker`,
  `backend`, `agents`, `ml`, `db`, `ci`, `deps`, `release`. Omit the scope when a change
  spans the whole repository.
- **Description**: imperative, lowercase, no trailing period, at most 72 characters.
- **Breaking changes**: `!` before the colon and/or a `BREAKING CHANGE:` footer explaining
  the migration. During 0.x a breaking change bumps the MINOR version.
- One logical change per commit; never mix a refactor with a behaviour change.
- Pass multi-line messages with `git commit -F <file>`.

Examples:

```
feat(dbt): add gold core, governance gates and BigQuery targets
fix(stream): flush watermarks, checkpoint to disk, fresh topics
refactor(eda)!: read the dataset from the repository data folder

BREAKING CHANGE: eda/data is no longer read; move the dataset to data/
or point LATAM_EDA_DATA at it.
```

## Day to day

1. Start a worktree from the latest `origin/develop` (above).
2. Make small commits locally; each one passes the hooks on its own.
3. **Push only after the maintainer approves that specific push** (branch or tag). Approval
   of a plan or of an earlier push does not extend to the next one.
4. Open the PR against `develop`; keep it updated until CI is green.

## Pull requests

- Title: a Conventional Commit header (`feat(airflow): add kb_sync DAG`).
- Body: the [template](.github/pull_request_template.md): what and why, how it was tested,
  data or secret impact, follow-ups.
- Base `develop` for work branches; `main` only for `release/*` and `hotfix/*`.
- CI must be green before merging. The agent merges once CI passes unless the maintainer
  asks to approve it first.
- Merge style: **merge commit** when the individual commits tell a story worth keeping
  (a feature series), **squash** for small or fix-up-heavy PRs. Never rebase shared branches.
- **Never delete branches** after merging.
- A PR stacked on another branch gets no CI until it targets `develop` or `main`; retarget
  it before merging its base.

## Versioning and releases

[SemVer 2.0.0](https://semver.org/), **0.x until the hackathon submission** ("anything may
change at any time"): each release bumps MINOR (`0.1.0` → `0.2.0`), fixes bump PATCH,
breaking changes bump MINOR. `1.0.0` is reserved for a stable, submitted system.
Releases are cut with commitizen (`cz bump`), which updates the version and
[`CHANGELOG.md`](CHANGELOG.md) (Keep a Changelog style), then tagged `vX.Y.Z` on `main`
and published as a GitHub release. Full procedure: [releasing](docs/development/releasing.md).

## Data

- Data never enters git: raw downloads, Parquet, DuckDB files, lake zones, model caches.
- One shared `data/` lives in the main checkout; worktrees symlink to it.
- Code finds it through environment variables, never hardcoded paths: `LATAM_EDA_DATA`
  for the EDA. Defaults resolve to `<repo>/data`.
- Large generated artefacts are reproducible from scripts; document the command that
  regenerates anything you add. Details: [data and secrets](docs/development/data-and-secrets.md).

## Secrets

- Secrets live only in git-ignored `.env` files (root `.env` from `.env.example`). Never
  commit, print, log or paste secret values, including in PR bodies and chat.
- New configuration keys go into the matching `.env.example` with an empty or obviously fake
  value.
- `detect-secrets` runs on every commit. A finding is never silenced on the agent's own
  authority: confirm it is a placeholder, then ask the maintainer before changing
  `.secrets.baseline` or any exclusion.

## Agent conduct

- Ask before destructive or outward-facing actions: pushes, merges into `main`, deleting
  data, editing GitHub settings, publishing releases.
- Prefer the smallest change that fully solves the task; follow existing patterns.
- Report outcomes faithfully: say what was tested, what failed and what was skipped.
- Keep this file current: when a rule changes, change it here in the same PR.
