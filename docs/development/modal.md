# Remote compute on Modal: plan and setup guide

**Status:** proposal, not yet implemented. **Written:** 2026-10-05. Prices and limits are as published by Modal and
NVIDIA on that date ([sources](#sources)); check them again before relying on a number.

**In one sentence:** keep the Mac as the control plane (VS Code, Claude Code, plugins, git), and use Modal as a
**compute plane** for pipeline rebuilds, notebook execution and GPU models. Modal is not a rented VM: it runs
containers on demand and bills per second.

## Contents

1. [Why remote compute](#1-why-remote-compute)
2. [Machines and estimated cost](#2-machines-and-estimated-cost)
3. [Recommended architecture](#3-recommended-architecture)
4. [VS Code, plugins and Claude Code](#4-vs-code-plugins-and-claude-code)
5. [Guaranteeing the information is available remotely](#5-guaranteeing-the-information-is-available-remotely)
6. [Implementation plan](#6-implementation-plan)
7. [Cost guardrails](#7-cost-guardrails)
8. [What stays local](#8-what-stays-local)
9. [Sources](#sources)

## 1. Why remote compute

| Local today | Consequence |
|---|---|
| Apple M1 Pro, 10 cores, 16 GB RAM | each whole-bank scratch lakehouse is about 6 GB and the builds are memory-bound |
| disk 94 % used (about 27 GB free) | every experiment needs 5–6 GB of scratch, deleted after use |
| no NVIDIA GPU | the NVIDIA Kumo models (`nvidia/Kumo-Relational`, `Kumo-Tabular`) require CUDA ([strategy 07 §7.4](../strategy/07_graph_and_foundation_models.md)) |
| `data/` is 27 GB | lake 9.9 GB, raw 9.4 GB, warehouse 3.8 GB, parquet 0.8 GB, model cache 0.5 GB |

**The Modal account.** On 2026-10-05 the account showed $530 of credits and a $200 "workspace usage" line. The
second is most likely a workspace spending limit; confirm it in *Usage & Billing Settings*. The Starter plan includes
$30 a month of credits, 100 containers and 10 concurrent GPUs.

## 2. Machines and estimated cost

**Modal list prices (2026-10-05):**
- CPU: $0.0000131 per physical core per second (about $0.047 per core-hour);
- memory: $0.00000222 per GiB per second (about $0.008 per GiB-hour);
- volumes: $0.09 per GiB-month, with the first 1 TiB free;
- network egress: $0.04 per GiB, with 1 TiB a month free on Starter.

| GPU | $/second | ≈ $/hour | GPU memory |
|---|---|---|---|
| T4 | 0.000164 | 0.59 | 16 GB |
| L4 | 0.000222 | 0.80 | 24 GB |
| A10 | 0.000306 | 1.10 | 24 GB |
| L40S | 0.000542 | 1.95 | 48 GB |
| A100 40 GB | 0.000583 | 2.10 | 40 GB |
| A100 80 GB | 0.000694 | 2.50 | 80 GB |
| RTX PRO 6000 | 0.000842 | 3.03 | 96 GB |
| H100 | 0.001097 | 3.95 | 80 GB |
| H200 | 0.001261 | 4.54 | 141 GB |
| B200 | 0.001736 | 6.25 | 192 GB |

### Sizing per workload

| Workload | Machine | ≈ $/hour | Typical hours/month | ≈ $/month |
|---|---|---|---|---|
| pipeline rebuilds and notebook execution | 8 cores, 64 GiB | 0.89 | 40 | 36 |
| large runs (all scopes in parallel) | 16 cores, 128 GiB | 1.78 | 10 | 18 |
| Kumo and GNN iteration | **L40S** (48 GB) + 8 cores, 32 GiB | 2.60 | 30 | 78 |
| Kumo on small samples | L4 (24 GB) + 4 cores, 16 GiB | 1.12 | 10 | 11 |
| Kumo at full scale (1.1 M rows) | H100 (80 GB) + 8 cores, 32 GiB | 4.60 | 10 | 46 |
| optional remote dev box, only while connected | 4 cores, 32 GiB | 0.44 | 40 | 18 |

**Total:** about **$150–210 a month**, so the $530 of credits lasts about **three months** at this pace.

**The Kumo GPU choice.** NVIDIA lists A10G, L4, L40S and H100 as supported hardware for Kumo-Relational; the
`structured-data-models` package requires Python ≥ 3.11 and PyTorch ≥ 2.7. No published VRAM requirement was found.
Start on an **L40S** and move to an **H100** only if a run runs out of memory or is too slow.

## 3. Recommended architecture

```
Mac (unchanged): VS Code + Claude Code + plugins + MCP + git worktrees
   │  modal run infrastructure/modal/app.py::<job> --<args>
   ▼
Modal compute plane
   ├─ CPU containers: dbt/DuckDB replays, notebook series, readiness_check.py
   ├─ GPU containers: Kumo-Relational / Kumo-Tabular, PyG / TGN
   ├─ Volume "latam-data": lake, raw, parquet, warehouse, derived outputs
   └─ Secret "latam-env": the keys of the root .env
   │  results pulled back (modal volume get) → committed through git as usual
```

**Design decisions:**
- **Code travels with each run.** `Image.add_local_dir` ships the current worktree, uncommitted changes included, so
  there is no push or clone. This is what makes runs seamless.
- **One environment.** Images are built from the locked dependencies (`eda/uv.lock`, the platform project). The
  container runs the same versions as the Mac.
- **Data is uploaded once.** It goes to a Modal Volume, with incremental updates afterwards.
- **Scratch lives on the container's own disk.** Each container has 512 GiB of ephemeral disk by default (up to
  3 TiB). The repository already supports this through `LATAM_SCOPE_DIR`. Building a DuckDB file directly on a network
  volume would be slow.
- **The Mac's disk is freed.** No scratch lakehouse is needed locally.

### Sketch of the app

To be validated during implementation, against the current Modal SDK.

```python
import modal

app = modal.App("latam-bank")
data = modal.Volume.from_name("latam-data", create_if_missing=True)
env = [modal.Secret.from_name("latam-env")]
IGNORE = ["data", ".git", "**/.venv", "**/__pycache__", "**/node_modules"]

cpu = (
    modal.Image.debian_slim(python_version="3.12")
    .pip_install_from_requirements("eda/requirements.modal.txt")  # from: uv export --frozen --project eda
    .add_local_dir(".", "/repo", ignore=IGNORE)
)
gpu = (
    modal.Image.from_registry("nvidia/cuda:12.4.1-runtime-ubuntu22.04", add_python="3.12")
    .pip_install("torch>=2.7", "structured-data-models", "duckdb", "pandas", "pyarrow")
    .add_local_dir(".", "/repo", ignore=IGNORE)
)


@app.function(image=cpu, cpu=8, memory=64 * 1024, volumes={"/vol": data}, secrets=env, timeout=6 * 3600)
def notebooks(series: str):
    # LATAM_EDA_DATA=/vol (inputs), LATAM_SCOPE_DIR=/tmp/scope (scratch); run scripts/build_notebook.py;
    # copy reports/ outputs to /vol/derived/<run>; data.commit()
    ...


@app.function(image=gpu, gpu="L40S", volumes={"/vol": data}, secrets=env, timeout=4 * 3600, retries=2)
def kumo(task: str):
    # read /vol/lake/features/ml_kumo_*.parquet; fit sdm.models.KumoRelational(device="cuda");
    # write metrics and the readiness gate to /vol/derived/kumo/<task>; checkpoint for pre-emption
    ...
```

**Usage:** `modal run infrastructure/modal/app.py::notebooks --series granularity_hour`, typed in a terminal or run
by Claude Code through Bash.

## 4. VS Code, plugins and Claude Code

### Recommended: everything stays local

Claude Code and VS Code keep running on the Mac, so everything keeps working as it does today:
- the user settings in `~/.claude`;
- the gstack hooks;
- auto-memory;
- the 9 enabled plugins: code-review, frontend-design, hookify, skill-creator, claude-md-management, commit-commands,
  mcp-server-dev, mcp-tunnels and plugin-dev;
- local MCP servers (desktop-commander);
- the Chrome extension;
- claude.ai connectors (Claude Docs);
- the project's `CLAUDE.md` and `AGENTS.md`;
- the worktrees.

Claude Code launches Modal jobs and reads their outputs. **Nothing has to migrate.**

### Optional: a remote dev box for interactive GPU debugging

**How it works:**
- A Modal **Sandbox** runs `sshd`, exposed with `modal.forward(22, unencrypted=True)`.
- VS Code connects with **Remote-SSH**.
- GPU sandboxes are supported.

**Limits:**
- A sandbox lives at most **24 hours**.
- `idle_timeout` stops it when unused, and filesystem snapshots let a new sandbox resume where the last one stopped.
- The forwarded host and port change on every start, so the launch script rewrites `~/.ssh/config`.
- It bills every second it runs, idle or not.

### Running Claude Code on the remote box

This is compatible, with caveats:

| Item | Remote behaviour |
|---|---|
| installation | Claude Code must be installed in the sandbox image |
| login | no browser there: run `claude setup-token` on the Mac and store the token as a Modal Secret (`CLAUDE_CODE_OAUTH_TOKEN`) |
| VS Code extension | runs on the remote host over Remote-SSH |
| plugins | the remote `~/.claude` is empty; reinstall from the marketplace |
| gstack hooks | point to `/Users/andresbecerra/...` paths that do not exist remotely; do not copy `settings.json` blindly |
| auto-memory | keyed by project path; the remote repo path gets a separate, empty memory |
| Chrome extension | does not work (the browser is on the Mac) |
| desktop-commander | would control the remote machine, not the Mac |
| claude.ai connectors | work after login |
| project instructions | `CLAUDE.md` and `AGENTS.md` travel with the repo |

## 5. Guaranteeing the information is available remotely

| What | How | Verification |
|---|---|---|
| code | shipped with each run (`add_local_dir`); GitHub stays the source of truth | the job log prints the commit and whether the worktree is dirty |
| data | `modal volume put latam-data data/lake /lake` (also raw, parquet, warehouse) | sha256 against the repository's manifests (`data/lake/manifests`) |
| secrets | `modal secret create latam-env --from-dotenv .env` | never baked into an image; never printed |
| environment | images built from the locked dependencies | `pytest -m "not data"` green inside the container |
| outputs | written to `/vol/derived/<run>`, pulled back with `modal volume get` | tables and notebooks committed through git, as today |

**Data rules still apply:**
- data never enters git;
- secrets live only in git-ignored `.env` files and Modal Secrets;
- outputs are reproducible from the documented commands.

**Residency.** The dataset is synthetic, so storing it on Modal (US) is acceptable. Real customer data falls under
the residency strategy ([ADR-007](../platform/adr/ADR-007.md)): Modal could only be used with region selection, at
1.15–1.75× the base prices, or not at all.

## 6. Implementation plan

| Step | Who | What | Done when |
|---|---|---|---|
| 0 | maintainer (about 15 min) | `uv tool install modal`; `modal setup` (browser login); confirm the meaning of the $200 line; set a budget alert | `modal profile current` shows the workspace |
| 1 | agent | create the volume and the secrets; upload `data/`; verify checksums against the manifests | every manifest entry matches |
| 2 | agent (PR) | `infrastructure/modal/` (CPU and GPU images; jobs for notebooks, pipeline replays and `readiness_check.py`); Makefile targets `modal-sync`, `modal-notebooks`, `modal-kumo`; this guide updated from proposal to procedure | a notebook series and the readiness scorecard reproduce on Modal byte for byte |
| 3 | agent | first Kumo probe on an L4 or L40S, sized from the measured memory; cost logged against the credits | metrics and a readiness gate written to `derived/kumo/` |
| 4 | optional | remote dev box script (sshd, `idle_timeout`, snapshot resume, `~/.ssh/config` writer) and VS Code Remote-SSH setup | VS Code opens the repo on a GPU sandbox |

Each step follows the repository rules: a worktree per branch, a PR against `develop`, and no push without approval.

## 7. Cost guardrails

- **No paid multipliers.** Never select a region (1.15–1.75×) and never request non-preemptible execution (3×).
  Long jobs checkpoint to the volume and use `retries` instead.
- **Timeouts.** Every function sets a `timeout`; dev boxes set `idle_timeout`.
- **Right-sizing.** Start small: L4 or L40S before H100, 8 cores before 16. Measure, then scale.
- **Shutdown.** `modal app list` and `modal app stop <app>` stop anything left running.
- **Monitoring.** A budget alert in *Usage & Billing*, and the dashboard checked weekly against the plan in §2.
- **Concurrency.** The Starter plan allows 10 GPUs at once; parallel runs should stay well below that.

## 8. What stays local

Modal cannot run Docker Compose inside a container, so these stay on the Mac (or would need a separate cloud VM):
- the platform's Docker stack (Airflow, Postgres + pgvector, Neo4j, Flink, Kafka);
- the browser-based tools (the Chrome extension);
- the desktop MCP servers.

The dbt-duckdb replays, the EDA notebook series, `readiness_check.py` and the GPU models all run on Modal.

## Sources

- [Modal pricing](https://modal.com/pricing): GPU, CPU, memory, volume and plan prices; region and non-preemptible
  multipliers.
- [Modal GPU pricing 2026, per-second billing](https://www.spheron.network/blog/modal-gpu-pricing-2026-per-second-billing/):
  hourly conversions.
- [Modal resources guide](https://modal.com/docs/guide/resources): CPU and memory requests, ephemeral disk
  (512 GiB default, 3 TiB maximum).
- [Modal sandboxes](https://modal.com/docs/guide/sandbox): 24-hour maximum lifetime, idle timeout, filesystem
  snapshots, GPU sandboxes.
- [Modal tunnels](https://modal.com/docs/guide/tunnels) and [`modal.forward`](https://modal.com/docs/reference/modal.forward):
  SSH into a container.
- [`modal shell`](https://modal.com/docs/cli/latest/shell): interactive shell in a function's image.
- [NVIDIA structured-data-models](https://nvidia.github.io/structured-data-models/overview.html): supported GPUs and
  software requirements.
- [Kumo-Relational model card](https://build.nvidia.com/nvidia/kumo-relational/modelcard) and
  [API reference](https://docs.api.nvidia.com/nim/re/reference/nvidia-kumo-relational).
