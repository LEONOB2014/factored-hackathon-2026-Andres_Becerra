"""Parity of the typed silver models with the retired typed bronze (docs/platform/09 §C.4).

Runs each generated `models/silver/typed/typed_*.sql` straight against lossless bronze (no dbt) and compares it with
the typed bronze Parquet it replaced: row count, column types, and an order-independent hash of every value. Also
reports how many rows carry a contract breach.

    cd platform && uv run python dbt/scripts/verify/typed_parity.py --out ../docs/platform/evidence/phase3/typed_parity.csv

Typed bronze is read from data/lake/bronze (or its read-only archive once retired).
"""

from __future__ import annotations

import argparse
import csv
import re
import sys
import time
from pathlib import Path

import duckdb

DBT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(DBT.parent / "libs"))
from latam_platform import config  # noqa: E402

TYPED_ZONE = {
    "bronze_raw": "bronze",
    "holdout_raw": "holdout",
}  # lossless source -> typed bronze zone


def typed_root(zone: str) -> Path:
    for base in (config.LAKE / zone, config.ARCHIVE_TYPED / zone):
        if base.exists():
            return base
    raise SystemExit(f"typed bronze zone {zone!r} not found in the lake or the archive")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()
    con = duckdb.connect()
    con.sql("SET enable_progress_bar = false")
    rows = []
    for model in sorted((DBT / "models" / "silver" / "typed").glob("typed_*.sql")):
        sql = model.read_text()
        m = re.search(r"\{\{ source\('(\w+)', '(\w+)'\) \}\}", sql)
        zone, table = m.groups()
        lossless = f"read_parquet('{config.LAKE / zone}/{table}/*/*.parquet', union_by_name=true, hive_partitioning=false)"
        typed_bronze = (
            f"read_parquet('{typed_root(TYPED_ZONE[zone])}/{table}/*/*.parquet', "
            "union_by_name=true, hive_partitioning=false)"
        )
        con.sql(f"CREATE OR REPLACE TEMP VIEW v AS {sql.replace(m.group(0), lossless)}")
        new_types = {c: t for c, t, *_ in con.sql("DESCRIBE v").fetchall() if not c.startswith("_")}
        old_types = {
            c: t for c, t, *_ in con.sql(f"DESCRIBE SELECT * FROM {typed_bronze}").fetchall()
        }
        cols = ", ".join(f'"{c}"' for c in new_types)
        t0 = time.time()
        n_new, h_new = con.sql(f"SELECT count(*), bit_xor(hash(row({cols}))) FROM v").fetchone()
        n_old, h_old = con.sql(
            f"SELECT count(*), bit_xor(hash(row({cols}))) FROM {typed_bronze}"
        ).fetchone()
        flagged, cells = con.sql(
            "SELECT count(*) FILTER (WHERE len(_dq_issues) > 0), coalesce(sum(len(_dq_issues)), 0) FROM v"
        ).fetchone()
        type_diff = [
            f"{c}:{t}->{new_types[c]}"
            for c, t in old_types.items()
            if c in new_types and t != new_types[c]
        ]
        rows.append(
            {
                "model": model.stem,
                "rows_typed_bronze": n_old,
                "rows_typed_model": n_new,
                "columns": len(new_types),
                "type_differences": ";".join(type_diff),
                "values_identical": h_new == h_old and n_new == n_old,
                "rows_flagged": flagged,
                "cells_flagged": cells,
                "seconds": round(time.time() - t0, 1),
            }
        )
        print(rows[-1], flush=True)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]), lineterminator="\n")
        w.writeheader()
        w.writerows(rows)
    bad = [r["model"] for r in rows if not r["values_identical"] or r["type_differences"]]
    print(
        f"{len(rows)} models, {sum(r['rows_typed_model'] for r in rows):,} rows; not identical: {bad or 'none'}"
    )
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
