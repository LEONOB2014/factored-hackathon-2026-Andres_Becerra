"""Inventory the 147 stored result tables as exploratory sources: path, SHA-256, shape, p-value columns.

    uv run python scripts/claims/00_sources.py

Writes build/sources/tables.csv. Tables are sources, not claims: a value becomes a claim only when a chapter
cites it, and a whole table is rendered with its hash in the caption (report_lib.texgen.render_table).
"""

from __future__ import annotations

import csv
import re

import pandas as pd

from report_lib import sources
from report_lib.manifest import expected_status
from report_lib.paths import BUILD, TABLES

P_COLUMN = re.compile(r"^(p|p_?value|pvalue|logrank_p)$", re.I)


def main() -> None:
    out = BUILD / "sources" / "tables.csv"
    out.parent.mkdir(parents=True, exist_ok=True)
    rows = []
    for path in sorted(TABLES.glob("*.csv")):
        frame = pd.read_csv(path)
        rel = sources.rel(path)
        rows.append({
            "source_path": rel,
            "sha256": sources.sha256(path),
            "rows": len(frame),
            "columns": len(frame.columns),
            "p_columns": ";".join(c for c in frame.columns if P_COLUMN.match(str(c))),
            "status": expected_status("table", rel),
        })  # fmt: skip
    with out.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    print(f"{len(rows)} tables -> {out}")


if __name__ == "__main__":
    main()
