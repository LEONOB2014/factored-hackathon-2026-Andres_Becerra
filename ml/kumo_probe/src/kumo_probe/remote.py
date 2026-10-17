"""Build the two scenario frames on the lake, then score saved frames.

`materialise_frames` follows `eda/scripts/readiness_check.py`: country session,
gold layer, hour star. It imports `latam_eda.country` only after `LATAM_EDA_DATA`
is set. `compile_project` looks for `platform/.venv/bin/dbt`; on an image that
installed dbt onto `PATH`, this module symlinks that binary into place.

`score_saved` does not open the lake. The GPU function calls it.
"""

from __future__ import annotations

import logging
import os
import shutil
from pathlib import Path

import pandas as pd

from kumo_probe.loaders import prepare
from kumo_probe.scenarios import SCENARIOS
from kumo_probe.score import score_predictions

logger = logging.getLogger("kumo_probe")

FRAMES_DIR_NAME = Path("derived") / "kumo_probe"


def frames_dir(data_root: Path | None = None) -> Path:
    root = data_root or Path(os.environ["LATAM_EDA_DATA"])
    return root / FRAMES_DIR_NAME


def ensure_dbt_on_venv_path(repo: Path) -> None:
    """Satisfy `latam_eda.pipeline.compile_project`, which hardcodes this path."""
    expected = repo / "platform" / ".venv" / "bin" / "dbt"
    if expected.exists():
        return
    found = shutil.which("dbt")
    if found is None:
        raise FileNotFoundError(
            "dbt is not on PATH and platform/.venv/bin/dbt is missing. "
            "The hour-star build needs that binary."
        )
    expected.parent.mkdir(parents=True, exist_ok=True)
    expected.symlink_to(found)


def materialise_frames(scope: str = "ALL", dataset: str = "main") -> Path:
    """Write one parquet per scenario under `$LATAM_EDA_DATA/derived/kumo_probe/`."""
    if "LATAM_EDA_DATA" not in os.environ:
        raise RuntimeError("Set LATAM_EDA_DATA to the dataset root before materialise_frames.")
    data_root = Path(os.environ["LATAM_EDA_DATA"])
    os.environ.setdefault("LATAM_LAKE_DIR", str(data_root / "lake"))
    os.environ.setdefault("LATAM_PIPELINE_DIR", str(data_root / "tmp" / "kumo_probe"))

    from kumo_probe.eda_path import ensure_eda_src, repo_root

    ensure_eda_src()
    repo = repo_root()
    ensure_dbt_on_venv_path(repo)

    from latam_eda import country
    from latam_eda import granularity as gate

    pipeline = country.session(scope, dataset, cwd=repo)
    country.prepare(pipeline, "gold")
    star = gate.open_star(pipeline, [gate.SQL_DIR_TIME, gate.SQL_DIR_HOUR])
    star.build(verbose=False)
    out = frames_dir(data_root)
    out.mkdir(parents=True, exist_ok=True)
    try:
        for spec in SCENARIOS:
            # Raw SQL output. `prepare` derives the target, so the label is built once.
            raw = star.q(spec.sql)
            dest = out / f"{spec.key}.parquet"
            raw.to_parquet(dest, index=False)
            logger.info("wrote %s rows to %s", len(raw), dest)
    finally:
        pipeline.close()
    return out


def score_saved(directory: Path, *, device: str = "cuda") -> list[dict]:
    """Run both models on the saved frames and write `kumo_readiness.csv`."""
    from kumo_probe.sdm_backend import predict_relational, predict_tabular

    rows: list[dict] = []
    for spec in SCENARIOS:
        path = directory / f"{spec.key}.parquet"
        if not path.is_file():
            raise FileNotFoundError(f"missing scenario frame {path}")
        prepared = prepare(spec, pd.read_parquet(path))
        predictions = {
            "kumo tabular": predict_tabular(prepared, device=device),
            "kumo relational": predict_relational(prepared, device=device),
        }
        rows.extend(score_predictions(prepared, predictions))
    dest = directory / "kumo_readiness.csv"
    pd.DataFrame(rows).to_csv(dest, index=False)
    logger.info("wrote %s readiness rows to %s", len(rows), dest)
    return rows
