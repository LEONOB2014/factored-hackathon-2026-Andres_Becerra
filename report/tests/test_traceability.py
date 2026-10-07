"""Every heading of the 65 notebook sources maps to a report section or carries a reason (design, Premise 2)."""

import re

from report_lib import traceability as tr
from report_lib.paths import TEX


def test_there_are_sixty_five_sources():
    assert len(tr.sources()) == 65


def test_every_heading_is_mapped_and_every_row_is_current():
    rows = tr.load_map()
    mapped = {(r["notebook"], r["heading"]) for r in rows}
    actual = {(tr.notebook_id(p), h) for p in tr.sources() for _, h in tr.headings(p)}
    assert actual - mapped == set(), "headings missing from notebook_map.csv"
    assert mapped - actual == set(), "rows for headings that no longer exist"


def test_each_row_has_a_label_or_a_reason_and_labels_exist():
    labels = set()
    for p in TEX.rglob("*.tex"):
        labels.update(re.findall(r"\\label\{([^}]+)\}", p.read_text()))
    for r in tr.load_map():
        has_label, has_reason = bool(r["report_label"]), bool(r["out_of_scope_reason"])
        assert has_label != has_reason, r
        if has_label:
            assert r["report_label"] in labels, r["report_label"]
