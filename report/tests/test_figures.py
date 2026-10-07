"""Figures: every included figure has hashed inputs, and plotted groups pass the privacy guard (A2)."""

import csv
import re

import matplotlib.pyplot as plt
import pytest

from report_lib import figures, sources, texgen
from report_lib.paths import FIGURES, REPO
from report_lib.privacy import PrivacyError


def test_every_included_figure_has_current_inputs():
    included = set()
    for p in texgen.chapter_files():
        included.update(re.findall(r"\\includegraphics(?:\[[^\]]*\])?\{([^}]+)\}", p.read_text()))
    rows = []
    if (FIGURES / figures.MANIFEST).exists():
        with (FIGURES / figures.MANIFEST).open() as f:
            rows = list(csv.DictReader(f))
    names = {r["figure"] for r in rows}
    assert included - names == set()
    for r in rows:
        assert sources.sha256(REPO / r["input_path"]) == r["sha256"], r["figure"]


def test_save_records_inputs_and_refuses_small_groups(tmp_path):
    src = tmp_path / "in.csv"
    src.write_text("a,b\n1,2\n")
    fig, ax = plt.subplots()
    ax.plot([0, 1], [0, 1])
    out = figures.save(fig, "line", [src], {"g1": 50}, out_dir=tmp_path, min_cell=10)
    assert out.exists() and out.read_bytes()[:4] == b"%PDF"
    with (tmp_path / figures.MANIFEST).open() as f:
        assert list(csv.DictReader(f))[0]["sha256"] == sources.sha256(src)
    with pytest.raises(PrivacyError):
        figures.save(fig, "small", [src], {"g1": 50, "g2": 4}, out_dir=tmp_path, min_cell=10)
    plt.close(fig)
