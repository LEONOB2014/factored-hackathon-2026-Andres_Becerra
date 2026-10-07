"""Tests marked `data` need the git-ignored dataset in the repository's data/ and are skipped without it."""

import pytest

from report_lib.paths import REPO


def pytest_collection_modifyitems(config, items):
    if any((REPO / "data" / "parquet").glob("*.parquet")):
        return
    skip = pytest.mark.skip(reason="dataset not found under data/parquet")
    for item in items:
        if "data" in item.keywords:
            item.add_marker(skip)
