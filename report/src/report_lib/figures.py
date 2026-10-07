"""Saving figures: vector PDF with embedded fonts, the privacy guard, and a manifest of input hashes."""

from __future__ import annotations

import csv
from collections.abc import Mapping
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
matplotlib.rcParams.update({"pdf.fonttype": 42, "ps.fonttype": 42, "font.family": "serif"})

from report_lib import protocol, sources  # noqa: E402
from report_lib.paths import FIGURES  # noqa: E402
from report_lib.privacy import check_groups  # noqa: E402

MANIFEST = "manifest.csv"


def save(fig, name: str, inputs: list[Path], group_sizes: Mapping[str, float] | None = None,
         out_dir: Path = FIGURES, min_cell: int | None = None) -> Path:  # fmt: skip
    if group_sizes is not None:
        min_cell = min_cell if min_cell is not None else int(protocol.load()["privacy"]["min_cell"])
        check_groups(group_sizes, min_cell)
    if not inputs:
        raise ValueError(f"figure {name} must declare its input files")
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{name}.pdf"
    fig.savefig(path, bbox_inches="tight")
    manifest = out_dir / MANIFEST
    rows = []
    if manifest.exists():
        with manifest.open() as f:
            rows = [r for r in csv.DictReader(f) if r["figure"] != name]
    rows += [
        {"figure": name, "input_path": sources.rel(p), "sha256": sources.sha256(p)} for p in inputs
    ]
    with manifest.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["figure", "input_path", "sha256"])
        w.writeheader()
        w.writerows(sorted(rows, key=lambda r: (r["figure"], r["input_path"])))
    return path
