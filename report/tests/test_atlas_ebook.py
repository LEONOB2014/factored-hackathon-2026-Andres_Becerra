"""The Atlas with the report as a book: injected once, replaceable, and carrying the PDF intact."""

import base64
import importlib.util
import re

from report_lib.paths import REPORT

spec = importlib.util.spec_from_file_location("atlas_ebook", REPORT / "scripts" / "atlas_ebook.py")
ebook = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ebook)

PAGE = "<title>BETA AID · Grain Atlas</title>\n<script>\n(function(){})();\n</script>\n"
PDF = b"%PDF-1.5\n%fake\n"


def test_injection_appends_the_reader_and_the_pdf():
    out = ebook.inject(PAGE, PDF)
    title, rest = PAGE.split("\n", 1)
    assert out.startswith(title + "\n" + ebook.EARLY + rest.rstrip("\n"))
    data = re.search(
        r'<script type="application/octet-stream" id="ebkData">([^<]*)</script>', out
    ).group(1)
    assert base64.b64decode(data) == PDF
    assert 'id="ebk"' in out and "pdf.min.js" in out


def test_injecting_twice_replaces_the_first():
    once = ebook.inject(PAGE, PDF)
    assert ebook.inject(once, PDF) == once
    assert once.count(ebook.BEGIN) == 1 and once.count(ebook.EARLY) == 1


def test_refuses_a_file_that_is_not_a_pdf():
    try:
        ebook.inject(PAGE, b"not a pdf")
    except ValueError:
        return
    raise AssertionError("accepted a non-PDF")
