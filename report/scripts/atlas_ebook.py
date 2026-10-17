"""Add the reports to the Grain Atlas as a shelf of books: the built Atlas page plus the reader and the PDFs.

The Atlas itself is not rebuilt or changed: the reader (report/atlas/) is appended after the page's own script, with
each PDF embedded as base64 in its own block, and hooks into the page only through its markup (a header button, a
rail entry, the #library and #<book> links and the r key). Running it again replaces an earlier injection.

    make -C report atlas      # build/report.pdf and build/copilot/{brief,evaluation}.pdf must exist
    uv run python scripts/atlas_ebook.py [--atlas PATH] [--book ID=PATH ...] [--out PATH]
"""

from __future__ import annotations

import argparse
import base64
import html
import re
import shutil
from dataclasses import dataclass
from pathlib import Path

from report_lib.paths import REPO, REPORT

ASSETS = REPORT / "atlas"
BUILD = REPORT / "build"  # both documents' build directories, whichever REPORT_DOC is set
ATLAS = REPO / "eda" / "reports" / "dashboards" / "grain_atlas" / "grain_atlas.html"
BEGIN, END = "<!-- technical-report reader: begin -->", "<!-- technical-report reader: end -->"
# The Atlas rewrites the hash to its own route as it starts, so a #<book> link is read before the Atlas runs.
EARLY = "<script>window.__ebkHash=location.hash;</script><!-- technical-report reader: hash -->\n"
LIMIT = 16 * 2**20  # the artifact page limit


@dataclass(frozen=True)
class Book:
    id: str  # the route: #<id> and #<id>/<page>
    kind: str
    title: str
    sub: str
    parts: bool  # the outline groups chapters into parts
    pdf: Path


SHELF = (
    Book("report", "Technical report", "The Statistical Foundations of the Grain Atlas",
         "The methods behind BETA AID's data platform and readiness gates", True, BUILD / "report.pdf"),
    Book("copilot-brief", "Brief", "The BETA AID Card Copilot",
         "What it is, how it works, what was trained and which language models were tested", False,
         BUILD / "copilot" / "brief.pdf"),
    Book("copilot-evaluation", "Evaluation report", "Evaluating the BETA AID Card Copilot",
         "Intent recognition, governed retrieval, a frozen challenge set, attacks and the language models tested",
         False, BUILD / "copilot" / "evaluation.pdf"),
)  # fmt: skip


def data_block(book: Book, pdf: bytes) -> str:
    if not pdf.startswith(b"%PDF"):
        raise ValueError(f"{book.id}: the file is not a PDF")
    attrs = {"id": f"ebkData-{book.id}", "class": "ebk-data", "data-id": book.id, "data-kind": book.kind,
             "data-title": book.title, "data-sub": book.sub, "data-parts": "1" if book.parts else "0"}  # fmt: skip
    a = " ".join(f'{k}="{html.escape(v, quote=True)}"' for k, v in attrs.items())
    return f'<script type="application/octet-stream" {a}>{base64.b64encode(pdf).decode()}</script>'


def inject(atlas: str, books: list[tuple[Book, bytes]]) -> str:
    if not books:
        raise ValueError("no books to shelve")
    if len({b.id for b, _ in books}) != len(books):
        raise ValueError("book ids must be unique")
    base = re.sub(
        re.escape(BEGIN) + r".*?" + re.escape(END) + r"\n?", "", atlas, flags=re.S
    ).replace(EARLY, "")
    block = "\n".join([
        BEGIN,
        "<style>\n" + (ASSETS / "reader.css").read_text() + "</style>",
        (ASSETS / "reader.html").read_text().rstrip(),
        *(data_block(b, pdf) for b, pdf in books),
        "<script>\n" + (ASSETS / "reader.js").read_text() + "</script>",
        END,
    ])  # fmt: skip
    head, sep, rest = base.partition("</title>\n")
    if not sep:
        raise ValueError("the Atlas page has no <title> line to anchor the early script")
    return head + sep + EARLY + rest.rstrip("\n") + "\n" + block + "\n"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--atlas", type=Path, default=ATLAS)
    ap.add_argument("--book", action="append", default=[], metavar="ID=PATH",
                    help="override the PDF of a shelved book (ids: " + ", ".join(b.id for b in SHELF) + ")")  # fmt: skip
    ap.add_argument("--out", type=Path, default=BUILD / "atlas" / "grain_atlas.html")
    a = ap.parse_args()
    paths = {b.id: b.pdf for b in SHELF}
    for spec in a.book:
        key, _, value = spec.partition("=")
        if key not in paths or not value:
            raise SystemExit(f"--book {spec!r}: expected one of {', '.join(paths)} = a PDF path")
        paths[key] = Path(value)
    books = [(b, paths[b.id].read_bytes()) for b in SHELF]
    page = inject(a.atlas.read_text(), books)
    size = len(page.encode())
    if size > LIMIT:
        raise SystemExit(f"page is {size / 2**20:.1f} MiB, over the artifact limit")
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(page)
    netlify = a.out.parent / "netlify" / "index.html"  # the copy the Atlas site serves
    netlify.parent.mkdir(exist_ok=True)
    shutil.copyfile(a.out, netlify)
    print(f"wrote {a.out} and {netlify} ({size / 2**20:.2f} MiB, {len(books)} books)")


if __name__ == "__main__":
    main()
