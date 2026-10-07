"""Generated tables: source hash in the caption, recorded in a manifest, and the privacy guard (A2)."""

import csv

import pandas as pd
import pytest

from report_lib import sources, texgen
from report_lib.paths import GENERATED, REPO
from report_lib.privacy import PrivacyError, check_frame


def test_table_carries_its_source_hash(tmp_path):
    src = tmp_path / "t.csv"
    pd.DataFrame({"market": ["MX", "CO"], "n": [120, 98], "rate": [0.123456, 0.2]}).to_csv(
        src, index=False
    )
    out = texgen.render_table(src, "markets", "Rates by market.", out_dir=tmp_path, min_cell=10)
    text = out.read_text()
    digest = sources.sha256(src)
    assert digest[:12] in text and r"\label{tab:markets}" in text and r"\num{0.123}" in text
    with (tmp_path / "tables" / "manifest.csv").open() as f:
        assert list(csv.DictReader(f))[0]["sha256"] == digest


@pytest.mark.parametrize(
    "frame, kw",
    [
        (pd.DataFrame({"customer_id": [1], "x": [2]}), {}),
        (pd.DataFrame({"email": ["a"], "x": [2]}), {}),
        (pd.DataFrame({"segment": ["a", "b"], "n": [120, 3]}), {}),
        (pd.DataFrame({"segment": ["a"], "people": [4]}), {"count_cols": ["people"]}),
    ],
)
def test_privacy_guard_refuses(frame, kw):
    with pytest.raises(PrivacyError):
        check_frame(frame, 10, **kw)


def test_privacy_guard_allows_aggregates():
    check_frame(pd.DataFrame({"name": ["model a"], "n": [0], "customers": [150]}), 10)


def test_generated_tables_match_their_sources():
    manifest = GENERATED / "tables" / "manifest.csv"
    if not manifest.exists():
        return
    with manifest.open() as f:
        for row in csv.DictReader(f):
            path = REPO / row["source_path"]
            assert sources.sha256(path) == row["sha256"], row["label"]


def test_unicode_math_in_headers_is_typeset():
    assert texgen.tex_escape("χ²/dof ≥ 1 × 2") == (
        r"\ensuremath{\chi}\textsuperscript{2}/dof \ensuremath{\ge} 1 \ensuremath{\times} 2"
    )
