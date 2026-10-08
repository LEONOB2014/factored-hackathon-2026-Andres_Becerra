"""Add the technical report to the Grain Atlas as a book: the built Atlas page plus the reader and the PDF.

The Atlas itself is not rebuilt or changed: the reader (report/atlas/) is appended after the page's own script, with
the PDF embedded as base64, and hooks into the page only through its markup (a header button, a rail entry, the
#report link and the r key). Running it again replaces an earlier injection.

    make -C report atlas      # build/report.pdf must exist
    uv run python scripts/atlas_ebook.py [--atlas PATH] [--pdf PATH] [--out PATH]
"""

from __future__ import annotations

import argparse
import base64
import re
from pathlib import Path

from report_lib.paths import BUILD, REPO, REPORT

ASSETS = REPORT / "atlas"
ATLAS = REPO / "eda" / "reports" / "dashboards" / "grain_atlas" / "grain_atlas.html"
BEGIN, END = "<!-- technical-report reader: begin -->", "<!-- technical-report reader: end -->"
# The Atlas rewrites the hash to its own route as it starts, so a #report link is read before the Atlas runs.
EARLY = "<script>window.__ebkHash=location.hash;</script><!-- technical-report reader: hash -->\n"
LIMIT = 16 * 2**20  # the artifact page limit


def inject(atlas: str, pdf: bytes) -> str:
    base = re.sub(
        re.escape(BEGIN) + r".*?" + re.escape(END) + r"\n?", "", atlas, flags=re.S
    ).replace(EARLY, "")
    if not pdf.startswith(b"%PDF"):
        raise ValueError("the report file is not a PDF")
    block = "\n".join([
        BEGIN,
        "<style>\n" + (ASSETS / "reader.css").read_text() + "</style>",
        (ASSETS / "reader.html").read_text().rstrip(),
        '<script type="application/octet-stream" id="ebkData">' + base64.b64encode(pdf).decode() + "</script>",
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
    ap.add_argument("--pdf", type=Path, default=BUILD / "report.pdf")
    ap.add_argument("--out", type=Path, default=BUILD / "atlas" / "grain_atlas.html")
    a = ap.parse_args()
    html = inject(a.atlas.read_text(), a.pdf.read_bytes())
    if len(html.encode()) > LIMIT:
        raise SystemExit(f"page is {len(html.encode()) / 2**20:.1f} MiB, over the artifact limit")
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(html)
    print(f"wrote {a.out} ({len(html.encode()) / 2**20:.2f} MiB)")


if __name__ == "__main__":
    main()
