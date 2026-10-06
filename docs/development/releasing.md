# Versioning and releases

## Policy

- [Semantic Versioning 2.0.0](https://semver.org/). Until the hackathon submission the
  project stays in **0.x**, where "anything may change at any time".
- Every release from `develop` bumps MINOR (`0.1.0` → `0.2.0`); a hotfix on `main` bumps
  PATCH (`0.2.0` → `0.2.1`). Breaking changes also bump MINOR while in 0.x
  (`major_version_zero = true` in commitizen).
- `1.0.0` is cut for the submitted, stable system.
- Versions live in the root `pyproject.toml` (`[tool.commitizen]`), tags are `vX.Y.Z`, and
  [`CHANGELOG.md`](../../CHANGELOG.md) follows the
  [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) layout, generated from the
  Conventional Commits history by commitizen.

| Version | Content |
|---|---|
| `v0.1.0` | Exploratory data analysis phase |
| `v0.2.0` | Compliance-grade data platform (lossless bronze to audit, Airflow 3 + Cosmos, streaming, four-eyes corrections, reproducible gold) and the analysis series that judged it (pipeline walkthrough, country series, backup as main) |
| `v0.3.0` | Close of the exploratory and evaluation phase. The Airflow and dbt platform was used to judge the predictive power of every data mart at the grains a bank decides on (granularity series I–III), with these results: the business clock ([ADR-014](../platform/adr/ADR-014.md)), the campaign decision cell, the bank at the hour, readiness gates for every model, and the data-collection audit ([strategy 13](../strategy/13_data_readiness_audit.md)). It also adds the Modal compute plan |
| `v0.4.0` | BETA AID: the card-service copilot (policy, verified actions, handoff, RAG and GraphRAG), its frozen held-out evaluation, the lateral pipelines by scope and grain (ADR-015 to ADR-020), and deployment on Modal and per residency region on Cloud Run (ADR-021) |
| `v0.5.0` | The AI readiness factory: the Grain Atlas published as the decision dashboard, the console wired to the real copilot and scorecard, the read-only Data API, the fully documented lakehouse and published dbt docs, the grain-by-country architecture, and documented security layers |

## Cut a release

```bash
git fetch origin
git worktree add -b release/v0.2.0 ../antigravity-worktrees/release-v0.2.0 origin/develop
cd ../antigravity-worktrees/release-v0.2.0
uvx --from commitizen cz bump --increment MINOR --yes --files-only   # version in pyproject.toml
uvx --from commitizen cz changelog --incremental --unreleased-version v0.2.0
git add pyproject.toml CHANGELOG.md
git commit -m "bump: version 0.1.0 → 0.2.0"
```

1. Review `CHANGELOG.md`; edit wording if needed in the same commit.
2. Push (approved), open the PR `release/v0.2.0` → `main`, wait for CI, merge with a
   **merge commit**.
3. Tag the merge commit on `main` and publish (each push approved):

```bash
cd ../../antigravity && git pull --ff-only
git tag -a v0.2.0 -m "v0.2.0: <one-line summary>"
git push origin v0.2.0
gh release create v0.2.0 --title "v0.2.0" --notes-file <changelog section>
```

4. Bring the release commit back: open a PR `main` → `develop` (merge commit).

## Hotfix

```bash
git worktree add -b hotfix/<desc> ../antigravity-worktrees/hotfix-<desc> origin/main
# fix, test, commit; then:
uvx --from commitizen cz bump --increment PATCH --yes --files-only
uvx --from commitizen cz changelog --incremental --unreleased-version vX.Y.Z
```

PR into `main` (merge commit), tag `vX.Y.Z+1`, release, then PR `main` → `develop`.
