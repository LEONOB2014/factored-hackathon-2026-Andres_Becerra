"""Fixed locations of the report project and the repository around it."""

from __future__ import annotations

from pathlib import Path

REPORT = Path(__file__).resolve().parents[2]
REPO = REPORT.parent
CONF = REPORT / "conf"
TEX = REPORT / "tex"
BUILD = REPORT / "build"
CLAIMS_DIR = BUILD / "claims"
GENERATED = BUILD / "generated"
FIGURES = BUILD / "figures"
TABLES = REPO / "eda" / "reports" / "tables"
NOTEBOOKS = REPO / "eda" / "notebooks"
