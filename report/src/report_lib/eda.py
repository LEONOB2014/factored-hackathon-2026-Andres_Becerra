"""Read-only access to latam_eda, which lives in ../eda/src (eda is not an installable package).

Import this module before any `latam_eda` import in scripts; pytest gets the same path from
pyproject.toml.
"""

from __future__ import annotations

import sys
from pathlib import Path

EDA_SRC = Path(__file__).resolve().parents[3] / "eda" / "src"
if str(EDA_SRC) not in sys.path:
    sys.path.insert(0, str(EDA_SRC))
