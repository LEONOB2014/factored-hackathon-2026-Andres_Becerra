"""Put `eda/src` on `sys.path` so the probe can call the readiness gate.

`latam_eda` stays a sibling package. This project does not depend on the full
`latam-eda` distribution (that one pulls PyTorch). Import `latam_eda.granularity`
only. Import `latam_eda.country` or `latam_eda.data` after `LATAM_EDA_DATA` is
set: `data.py` creates `data/derived` at import time.
"""

from __future__ import annotations

import sys
from pathlib import Path


def repo_root() -> Path:
    """First parent that contains both `eda/` and `platform/`, as `pipeline.repo_root` does."""
    here = Path(__file__).resolve()
    for parent in [here, *here.parents]:
        if (parent / "eda").is_dir() and (parent / "platform").is_dir():
            return parent
    raise FileNotFoundError("repository root not found (need eda/ and platform/)")


def ensure_eda_src() -> Path:
    src = repo_root() / "eda" / "src"
    entry = str(src)
    if entry not in sys.path:
        sys.path.insert(0, entry)
    return src
