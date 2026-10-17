"""Score the Kumo probe on Modal. Do not import this module from the CPU tests.

The dataset stays on a Volume built from `data/` and is mounted at `/data`.
The image copies code only (`eda/src`, `platform/dbt`, this package). It does
not copy `data/`, `.git`, or `.env`.

A CPU function materialises the two scenario frames. An L4 function scores them.
Nothing here calls `train()`.

    modal volume create beta-aid-kumo-data
    modal volume put beta-aid-kumo-data /path/to/antigravity/data /
    cd ml/kumo_probe && uv sync --extra modal && modal run modal_job.py
    modal run modal_job.py --size medium

`modal run` was not executed while this entry point was added. See README.md
for the rate-card ceiling to approve first.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

import modal

logger = logging.getLogger("kumo_probe")

REPO = Path(__file__).resolve().parents[2]
PROBE = Path(__file__).resolve().parent
PYTHONPATH = "/repo/eda/src:/repo/ml/kumo_probe/src"
VOLUME_NAME = "beta-aid-kumo-data"
_IGNORE = ["**/__pycache__", "**/.user.yml", "**/target/**"]

volume = modal.Volume.from_name(VOLUME_NAME, create_if_missing=True)

cpu_image = (
    modal.Image.debian_slim(python_version="3.12")
    .pip_install(
        "dbt-core>=1.12.5",
        "dbt-duckdb>=1.11.0",
        "duckdb>=1.1",
        "numpy>=1.26",
        "pandas>=2.2",
        "pyarrow>=15",
        "scikit-learn>=1.4",
        "scipy>=1.11",
    )
    .env({"LATAM_EDA_DATA": "/data", "PYTHONPATH": PYTHONPATH})
    .add_local_dir(REPO / "eda" / "src", "/repo/eda/src", ignore=_IGNORE)
    .add_local_dir(REPO / "platform" / "dbt", "/repo/platform/dbt", ignore=_IGNORE)
    .add_local_dir(PROBE / "src", "/repo/ml/kumo_probe/src", ignore=_IGNORE)
)

# cu124 is the image default. It was not checked against the L4 driver Modal serves.
gpu_image = (
    modal.Image.debian_slim(python_version="3.12")
    .apt_install("git")
    .pip_install("torch>=2.7", index_url="https://download.pytorch.org/whl/cu124")
    .pip_install("git+https://github.com/NVIDIA/structured-data-models.git")
    .pip_install(
        "numpy>=1.26",
        "pandas>=2.2",
        "pyarrow>=15",
        "scikit-learn>=1.4",
        "scipy>=1.11",
    )
    .env({"LATAM_EDA_DATA": "/data", "PYTHONPATH": PYTHONPATH})
    .add_local_dir(REPO / "eda" / "src", "/repo/eda/src", ignore=_IGNORE)
    .add_local_dir(PROBE / "src", "/repo/ml/kumo_probe/src", ignore=_IGNORE)
)

app = modal.App("beta-aid-kumo-probe")


@app.function(image=cpu_image, volumes={"/data": volume}, cpu=8, memory=32768, timeout=7200)
def materialise() -> str:
    """Build the hour star on the volume and write the two scenario frames."""
    os.environ["LATAM_EDA_DATA"] = "/data"
    from kumo_probe.remote import materialise_frames

    out = materialise_frames()
    volume.commit()
    return str(out)


@app.function(
    image=gpu_image,
    gpu="L4",
    volumes={"/data": volume},
    memory=32768,
    timeout=7200,
)
def score(size: str = "large") -> list[dict]:
    """In-context KumoTabular and KumoRelational on the materialised frames."""
    os.environ["LATAM_EDA_DATA"] = "/data"
    os.environ["KUMO_SIZE"] = size
    volume.reload()
    from kumo_probe.remote import frames_dir, score_saved

    rows = score_saved(frames_dir(Path("/data")), device="cuda")
    volume.commit()
    return rows


@app.local_entrypoint()
def main(size: str = "large") -> None:
    written = materialise.remote()
    logger.info("scenario frames at %s", written)
    rows = score.remote(size)
    for row in rows:
        logger.info(
            "%s | %s | %s | delta=%s",
            row["scenario"],
            row["opinion"],
            row["verdict"],
            row["delta"],
        )
