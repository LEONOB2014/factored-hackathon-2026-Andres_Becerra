"""The copilot documents: each master includes only files that exist, and every chapter, appendix and brief section
is included by one of them. Runs only with REPORT_DOC=copilot (see conftest.py)."""

import re

from report_lib.paths import TEX


def included(master: str) -> set[str]:
    text = (TEX / master).read_text()
    return set(
        re.findall(
            r"\\(?:include|input)\{((?:chapters|appendices|frontmatter|brief)/[^}]+)\}", text
        )
    )


def test_every_include_exists_and_every_section_is_included():
    names = included("evaluation.tex") | included("brief.tex")
    for name in names:
        assert (TEX / f"{name}.tex").is_file(), name
    on_disk = {f"{p.parent.name}/{p.stem}" for p in TEX.glob("*/*.tex")}
    assert on_disk == names


def test_no_document_names_a_hosting_platform():
    """The copilot documents describe the system and its evaluations, not where it is hosted."""
    text = "\n".join(p.read_text() for p in TEX.rglob("*.tex"))
    for name in ("Modal", "Cloud Run", "Stripe"):
        assert name not in text, name
