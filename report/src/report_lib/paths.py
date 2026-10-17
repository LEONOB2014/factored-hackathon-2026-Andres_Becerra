"""Fixed locations of the report project and the repository around it.

The project builds two documents from the same machinery. REPORT_DOC selects one: `atlas` (the default), the
technical report on the Grain Atlas in tex/ and conf/; or `copilot`, the copilot brief and evaluation report in
copilot/tex/ and copilot/conf/. Each document has its own build directory, so their claims never mix. The shared
preamble and macros live in tex/ for both.
"""

from __future__ import annotations

import os
from pathlib import Path

REPORT = Path(__file__).resolve().parents[2]
REPO = REPORT.parent
DOCS = ("atlas", "copilot")
DOC = os.environ.get("REPORT_DOC", "atlas")
if DOC not in DOCS:
    raise ValueError(f"REPORT_DOC must be one of {', '.join(DOCS)}, not {DOC!r}")
SHARED_TEX = REPORT / "tex"
CONF = REPORT / "conf" if DOC == "atlas" else REPORT / "copilot" / "conf"
TEX = SHARED_TEX if DOC == "atlas" else REPORT / "copilot" / "tex"
BUILD = REPORT / "build" if DOC == "atlas" else REPORT / "build" / "copilot"
CLAIMS_DIR = BUILD / "claims"
GENERATED = BUILD / "generated"
FIGURES = BUILD / "figures"
TABLES = REPO / "eda" / "reports" / "tables"
NOTEBOOKS = REPO / "eda" / "notebooks"
COPILOT_REPORTS = REPO / "copilot" / "eval" / "reports"
