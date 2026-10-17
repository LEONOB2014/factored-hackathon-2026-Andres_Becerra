"""The Atlas with the reports as a shelf of books: injected once, replaceable, and carrying each PDF intact."""

import base64
import importlib.util
import re
import sys

import pytest

from report_lib.paths import REPORT

spec = importlib.util.spec_from_file_location("atlas_ebook", REPORT / "scripts" / "atlas_ebook.py")
ebook = importlib.util.module_from_spec(spec)
sys.modules["atlas_ebook"] = ebook  # dataclasses look their module up here
spec.loader.exec_module(ebook)

PAGE = "<title>BETA AID · Grain Atlas</title>\n<script>\n(function(){})();\n</script>\n"
PDFS = {b.id: f"%PDF-1.5\n%fake {b.id}\n".encode() for b in ebook.SHELF}
BOOKS = [(b, PDFS[b.id]) for b in ebook.SHELF]


def test_injection_appends_the_reader_and_every_pdf():
    out = ebook.inject(PAGE, BOOKS)
    title, rest = PAGE.split("\n", 1)
    assert out.startswith(title + "\n" + ebook.EARLY + rest.rstrip("\n"))
    for b in ebook.SHELF:
        block = re.search(
            rf'<script type="application/octet-stream" id="ebkData-{b.id}"[^>]*>([^<]*)</script>',
            out,
        )
        assert base64.b64decode(block.group(1)) == PDFS[b.id], b.id
        assert f'data-id="{b.id}"' in block.group(0)
    assert 'id="ebk"' in out and "pdf.min.js" in out and 'id="ebkShelf"' in out


def test_the_shelf_holds_the_technical_report_and_both_copilot_books():
    assert [b.id for b in ebook.SHELF] == ["report", "copilot-brief", "copilot-evaluation"]
    assert [b.parts for b in ebook.SHELF] == [True, False, False]


def test_titles_are_escaped_in_their_attributes():
    b = ebook.Book("x", "Kind", 'A "quoted" <title>', "sub & more", False, ebook.BUILD / "x.pdf")
    out = ebook.inject(PAGE, [(b, b"%PDF-1.4\n")])
    assert 'data-title="A &quot;quoted&quot; &lt;title&gt;"' in out
    assert 'data-sub="sub &amp; more"' in out


def test_injecting_twice_replaces_the_first():
    once = ebook.inject(PAGE, BOOKS)
    assert ebook.inject(once, BOOKS) == once
    assert once.count(ebook.BEGIN) == 1 and once.count(ebook.EARLY) == 1


def test_refuses_a_file_that_is_not_a_pdf_and_duplicate_ids():
    with pytest.raises(ValueError):
        ebook.inject(PAGE, [(ebook.SHELF[0], b"not a pdf")])
    with pytest.raises(ValueError):
        ebook.inject(PAGE, [BOOKS[0], BOOKS[0]])
