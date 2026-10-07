"""Claims ledger, estimators and LaTeX generation for the technical report.

Importing the package puts ../eda/src on sys.path, so every submodule can import latam_eda (read-only; eda is a
virtual uv project, not an installable package).
"""

import sys as _sys
from pathlib import Path as _Path

_EDA_SRC = _Path(__file__).resolve().parents[3] / "eda" / "src"
if str(_EDA_SRC) not in _sys.path:
    _sys.path.insert(0, str(_EDA_SRC))
