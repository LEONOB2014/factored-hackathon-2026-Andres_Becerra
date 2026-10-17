"""Headings of the notebook sources the Atlas indexes, and their map to report sections."""

from __future__ import annotations

import csv
import re
from pathlib import Path

from report_lib.paths import CONF, NOTEBOOKS

# The 65 sources (design, Premise 1). country_template is the one source of the eight country executions.
SOURCE_DIRS = (
    ".", "medallion", "model_risk", "pipeline", "country_template", "country_compare", "dataset_compare",
    "granularity", "granularity_time", "granularity_hour",
)  # fmt: skip
HEADING = re.compile(r"^# (#{1,2}) (.+?)\s*$")
MAP = CONF / "notebook_map.csv"
FIELDS = ["notebook", "level", "heading", "report_label", "out_of_scope_reason", "data_window_end"]


def sources(root: Path = NOTEBOOKS) -> list[Path]:
    out = []
    for d in SOURCE_DIRS:
        out.extend(sorted((root / d).glob("*.py")))
    return out


def notebook_id(path: Path, root: Path = NOTEBOOKS) -> str:
    return path.relative_to(root).with_suffix("").as_posix()


def headings(path: Path) -> list[tuple[int, str]]:
    out, in_md = [], False
    for line in path.read_text().splitlines():
        if line.startswith("# %%"):
            in_md = "[markdown]" in line
            continue
        if in_md:
            m = HEADING.match(line)
            if m:
                out.append((len(m.group(1)), m.group(2)))
    return out


def load_map(path: Path = MAP) -> list[dict[str, str]]:
    with path.open() as f:
        return list(csv.DictReader(f))
