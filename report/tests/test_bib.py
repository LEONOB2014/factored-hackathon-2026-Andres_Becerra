"""Bibliography: cited keys exist, carry an identifier and a verification record."""

from report_lib import bib

GOOD = "@article{bh1995,\n  author = {B},\n  doi = {10.1111/x},\n}\n"
ROW = {
    "key": "bh1995",
    "identifier": "10.1111/x",
    "date_resolved": "2026-10-07",
    "resolved_title": "T",
}


def test_repository_bibliography_is_consistent():
    assert bib.check_repository() == []


def test_complete_entry_passes():
    assert bib.problems(GOOD, [ROW], [r"\textcite[p.~3]{bh1995}"]) == []


def test_missing_identifier_verification_and_key_are_reported():
    probs = bib.problems("@book{x,\n  title = {T},\n}\n", [], [r"\cite{x,y}"])
    assert any("x: needs a doi" in p for p in probs)
    assert any("x: missing from bib_verification" in p for p in probs)
    assert any("y: cited but not in refs.bib" in p for p in probs)


def test_commented_citations_are_ignored():
    assert bib.problems(GOOD, [ROW], ["% \\cite{ghost}"]) == []
