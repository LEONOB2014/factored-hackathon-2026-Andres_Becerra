"""Per-chapter claim files and the strict merge that every build reads.

Each chapter script overwrites its own build/claims/NN.parquet, so re-running a chapter is idempotent. The merge
validates every row and fails on a duplicate id; texgen then fails on any \\est id without a row.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from report_lib.manifest import Claim
from report_lib.paths import CLAIMS_DIR


def write_chapter(chapter: int, claims: list[Claim], directory: Path = CLAIMS_DIR) -> Path:
    for c in claims:
        if c.chapter != chapter:
            raise ValueError(f"{c.id} belongs to chapter {c.chapter}, not {chapter}")
    ids = [c.id for c in claims]
    dup = sorted({i for i in ids if ids.count(i) > 1})
    if dup:
        raise ValueError(f"duplicate claim ids in chapter {chapter}: {', '.join(dup)}")
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{chapter:02d}.parquet"
    frame = pd.DataFrame([c.model_dump() for c in claims], columns=list(Claim.model_fields))
    frame.to_parquet(path, index=False)
    return path


def load_all(directory: Path = CLAIMS_DIR) -> dict[str, Claim]:
    out: dict[str, Claim] = {}
    for path in sorted(directory.glob("*.parquet")):
        frame = pd.read_parquet(path)
        for row in frame.to_dict("records"):
            clean = {k: v for k, v in row.items() if not _missing(v)}
            claim = Claim(**clean)
            if claim.id in out:
                raise ValueError(
                    f"claim id {claim.id} appears in more than one chapter file ({path.name})"
                )
            out[claim.id] = claim
    return out


def _missing(v) -> bool:
    try:
        return v is None or bool(pd.isna(v))
    except (TypeError, ValueError):
        return False
