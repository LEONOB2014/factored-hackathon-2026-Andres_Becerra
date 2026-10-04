"""Generate every scoped series from one template: notebooks/country_template → notebooks/<prefix>_<scope>.

Two dimensions, eight series:
* **dataset**: `main` (prefix `country`) or `backup` (prefix `backup`: data_backup_20260831 run as if it were main);
* **scope**: `ALL` (the whole bank, no cut), `MX`, `CO`, `AR` (one country, its own lake).

The template is the only place to edit. A generated source differs from it only in tokens and in conditional
markdown blocks, so the series cannot drift apart in method; their executed outputs (and the decisions they compute)
differ because the data does.

Tokens: `__COUNTRY__` (scope code), `__COUNTRY_NAME__`, `__DATASET__`, `__PREFIX__`, `__SERIES__`.
Conditional blocks (whole lines, for prose that only one scope or dataset should read)::

    # <ALL>          kept for the whole-bank scope only
    # <COUNTRY>      kept for single-country scopes only
    # <MAIN>         kept for the main dataset only
    # <BACKUP>       kept for the backup dataset only
    # </ALL> ...     closes the block (blocks do not nest)

    uv run scripts/build_country_notebooks.py            # regenerate the .py sources
    for nb in notebooks/backup_mx/[0-9][0-9]_*.py; do
        uv run scripts/build_country_notebooks.py --execute "$nb"; done
"""

import argparse
import re
from pathlib import Path

import build_notebook

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "notebooks" / "country_template"
NAMES = {"ALL": "All countries", "MX": "Mexico", "CO": "Colombia", "AR": "Argentina"}
DATASETS = {
    "main": ("country", "Country series"),
    "backup": ("backup", "Backup-as-main series"),
}
SERIES = [(dataset, code) for dataset in DATASETS for code in NAMES]
BLOCK = re.compile(r"^# </?(ALL|COUNTRY|MAIN|BACKUP)>$")


def folder(dataset: str, code: str) -> Path:
    return ROOT / "notebooks" / f"{DATASETS[dataset][0]}_{code.lower()}"


def render(text: str, code: str, dataset: str = "main") -> str:
    keep = {"ALL" if code == "ALL" else "COUNTRY", "MAIN" if dataset == "main" else "BACKUP"}
    out, block = [], None
    for line in text.splitlines(keepends=True):
        m = BLOCK.match(line.rstrip("\n"))
        if m:
            opening = not line.startswith("# </")
            assert opening == (block is None), f"unbalanced block at {line!r}"
            block = m.group(1) if opening else None
            continue
        if block is None or block in keep:
            out.append(line)
    assert block is None, f"block {block} never closed"
    prefix, series = DATASETS[dataset]
    return (
        "".join(out)
        .replace("__COUNTRY_NAME__", NAMES[code])
        .replace("__COUNTRY__", code)
        .replace("__DATASET__", dataset)
        .replace("__PREFIX__", prefix)
        .replace("__SERIES__", series)
    )


def generate() -> list[Path]:
    out = []
    for dataset, code in SERIES:
        dst_dir = folder(dataset, code)
        dst_dir.mkdir(exist_ok=True)
        for src in sorted(TEMPLATE.glob("[0-9][0-9]_*.py")):
            dst = dst_dir / src.name
            dst.write_text(render(src.read_text(), code, dataset))
            out.append(dst)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--execute", type=Path, help="execute one generated notebook and export its HTML"
    )
    a = ap.parse_args()
    if a.execute:
        src = a.execute.resolve()
        build_notebook.build(
            src, execute=True, html_dir=ROOT / "reports" / "notebooks" / src.parent.name
        )
        return
    for p in generate():
        print(p.relative_to(ROOT))


if __name__ == "__main__":
    main()
