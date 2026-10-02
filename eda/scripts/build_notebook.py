#!/usr/bin/env python3
"""Build (and optionally execute) a notebook from a `# %%` percent-format source file.

    uv run scripts/build_notebook.py notebooks/01_understanding.py --execute

Cells: `# %%` = code, `# %% [markdown]` = markdown (lines prefixed with `# `).
Writes the .ipynb next to the source and an HTML export in reports/notebooks/.
"""

import argparse
import re
import subprocess
import sys
from pathlib import Path

import nbformat

ROOT = Path(__file__).resolve().parent.parent
HTML_DIR = ROOT / "reports" / "notebooks"


def parse(src: str):
    cells, kind, buf = [], None, []

    def flush():
        if kind is None:
            return
        text = "\n".join(buf).strip("\n")
        if kind == "markdown":
            text = "\n".join(re.sub(r"^# ?", "", l) for l in text.splitlines())
            cells.append(nbformat.v4.new_markdown_cell(text))
        elif text.strip():
            cells.append(nbformat.v4.new_code_cell(text))

    for line in src.splitlines():
        m = re.match(r"^# %%(?: \[(markdown)\])?\s*$", line)
        if m:
            flush()
            kind, buf = ("markdown" if m.group(1) else "code"), []
        elif kind is not None:
            buf.append(line)
    flush()
    return cells


def build(source: Path, execute: bool = False, html_dir: Path | None = HTML_DIR) -> Path:
    """Write <source>.ipynb next to the source, optionally execute it, export HTML to html_dir."""
    nb = nbformat.v4.new_notebook(cells=parse(source.read_text()))
    nb.metadata["kernelspec"] = {
        "name": "python3",
        "display_name": "Python 3",
        "language": "python",
    }
    out = source.resolve().with_suffix(".ipynb")
    nbformat.write(nb, out)
    if execute:
        subprocess.run(
            [
                sys.executable,
                "-m",
                "jupyter",
                "nbconvert",
                "--execute",
                "--to",
                "notebook",
                "--inplace",
                "--ExecutePreprocessor.timeout=1800",
                str(out),
            ],
            check=True,
            cwd=out.parent,
        )
    if html_dir is not None:
        subprocess.run(
            [
                sys.executable,
                "-m",
                "jupyter",
                "nbconvert",
                "--to",
                "html",
                "--output-dir",
                str(html_dir),
                str(out),
            ],
            check=True,
            cwd=out.parent,
        )
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("source", type=Path)
    ap.add_argument("--execute", action="store_true")
    ap.add_argument("--html-dir", type=Path, default=HTML_DIR)
    a = ap.parse_args()
    print("built", build(a.source, a.execute, a.html_dir))


if __name__ == "__main__":
    main()
