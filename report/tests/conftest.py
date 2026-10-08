"""Tests marked `data` need the git-ignored dataset in the repository's data/ and are skipped without it.

The suite runs once per document (REPORT_DOC). The copilot document runs only the guarantees that hold for any
document built here; the Atlas report's own tests (notebooks, country tables, gates, the Atlas page) run only for it.
"""

import pytest

from report_lib.paths import DOC, REPO

GENERIC = {"test_no_bare_numbers.py", "test_manifest.py", "test_tables.py", "test_figures.py", "test_bib.py",
           "test_build.py", "test_copilot_estimators.py"}  # fmt: skip
COPILOT_ONLY = {"test_copilot_doc.py"}


def pytest_ignore_collect(collection_path, config):
    name = collection_path.name
    if not name.startswith("test_") or not name.endswith(".py"):
        return None
    if DOC == "copilot":
        return name not in GENERIC | COPILOT_ONLY or None
    return name in COPILOT_ONLY or None


def pytest_collection_modifyitems(config, items):
    if any((REPO / "data" / "parquet").glob("*.parquet")):
        return
    skip = pytest.mark.skip(reason="dataset not found under data/parquet")
    for item in items:
        if "data" in item.keywords:
            item.add_marker(skip)
